# OWNER: Member 2
# Tests for the AI service. Run from backend/:  python -m pytest tests/test_ai.py -v
import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import ImageFilter
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai import data_sources, documents, duplicates, evaluation, names, scam
from main import app
from shared import db as shared_db

client = TestClient(app)
KEY = {"X-Service-Key": "svc-test"}
M1_KEY = {"X-API-Key": "m1-test"}


def _sqlite():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return engine, sessionmaker(bind=engine, autoflush=False)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Keys set, an empty in-memory database (so nothing touches a real Postgres),
    and fresh caches for every test."""
    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "svc-test")
    monkeypatch.setenv("AI_API_KEY", "m1-test")
    monkeypatch.delenv("AI_DUPLICATES_STRICT", raising=False)
    engine, factory = _sqlite()
    monkeypatch.setattr(shared_db, "SessionLocal", factory)
    data_sources.reset_cache()
    duplicates.reset_memory()
    yield engine
    engine.dispose()


def post(path, body, headers=KEY):
    return client.post(f"/internal/ai/{path}", json=body, headers=headers)


def png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# public routes
# ---------------------------------------------------------------------------
def test_health():
    assert client.get("/api/ai/health").status_code == 200


def test_decide_is_human():
    response = client.post("/api/ai/decide")
    assert response.json()["route"] == "HUMAN"


def test_decide_empty_object_is_human_with_low_confidence():
    body = client.post("/api/ai/decide", json={}).json()   # what the frontend sends
    assert body["route"] == "HUMAN" and body["confidence"] < 0.7 and body["reason"]


def test_decide_runs_the_real_pipeline():
    clean = {"identity_verified": True, "name_match_score": 1.0, "document_quality": 0.95,
             "duplicate_flag": False, "scam_flag": False, "monthly_income": 20000}
    assert client.post("/api/ai/decide", json=clean).json()["route"] == "AUTO"
    assert client.post("/api/ai/decide", json={"input": {**clean, "document_quality": None}}).json()["route"] == "ASK_MORE"
    assert client.post("/api/ai/decide", json={**clean, "name_match_score": 0.5}).json()["route"] == "HUMAN"


def test_decide_rejects_bad_values():
    r = client.post("/api/ai/decide", json={"name_match_score": 7})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# service key
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["scam-check", "match-identity", "detect-duplicates", "evaluate", "explain",
                                  "extract-document"])
def test_internal_routes_need_a_key(path):
    r = post(path, {}, headers={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert post(path, {}, headers={"X-Service-Key": "wrong"}).status_code == 403


def test_both_callers_keys_work():
    assert post("scam-check", {"text": "hello"}, headers=KEY).status_code == 200
    assert post("scam-check", {"text": "hello"}, headers=M1_KEY).status_code == 200
    assert post("scam-check", {"text": "hello"}, headers={"X-API-Key": "svc-test"}).status_code == 403


def test_fails_closed_when_no_key_is_configured(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_KEY")
    monkeypatch.delenv("AI_API_KEY")
    assert post("scam-check", {"text": "hi"}, headers={"X-Service-Key": ""}).status_code == 403


# ---------------------------------------------------------------------------
# scam check
# ---------------------------------------------------------------------------
def test_scam_spec_example_platform_shape():
    r = post("scam-check", {"text": "Dear citizen, click here to claim Rs 25,000 from BENAZIR fund. OTP: 1234. Limited time!"},
             headers=M1_KEY)
    body = r.json()
    assert r.status_code == 200 and body["label"] == "likely_scam"
    # exactly what Member 1's platform validates
    assert body["label"] in ("likely_scam", "uncertain", "no_scam_indicators")
    assert isinstance(body["confidence"], float) and 0 <= body["confidence"] <= 1
    assert isinstance(body["indicators"], list) and body["indicators"]
    assert body["explanation"] and body["recommended_action"] and "false alarms" in body["false_alarm_rate"]


def test_scam_agent_shape():
    body = post("scam-check", {"case_id": "c1", "message": "Send a processing fee to receive relief"}).json()
    assert body["scam_flag"] is True and body["score"] > 0.5 and body["reasons"] and body["case_id"] == "c1"
    clean = post("scam-check", {"case_id": "c1", "message": "Your appointment is on Monday at 10am."}).json()
    assert clean["scam_flag"] is False and clean["label"] == "no_scam_indicators"


@pytest.mark.parametrize("message", [
    "Your OTP for login is 482913. Do not share it with anyone.",
    "Warning: never share your PIN or send money to anyone claiming to be from RASTA.",
    "BISP: Your payment is ready. Visit your nearest campsite with your CNIC.",
])
def test_scam_safety_advice_is_not_flagged(message):
    assert scam.classify(message)["label"] != "likely_scam"


def test_scam_roman_urdu():
    res = scam.classify("BISP: Aap ki raqam aa gayi hai. Apna CNIC number aur OTP is number par bhejein 03001234567")
    assert res["label"] == "likely_scam" and "otp_request" in res["signal_keys"]


@pytest.mark.parametrize("body", [{}, {"text": "   "}, {"text": "x" * 5001}, {"message": 5}])
def test_scam_bad_input(body):
    r = post("scam-check", body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# name matching
# ---------------------------------------------------------------------------
def test_match_spelling_variants_confirmed():
    body = post("match-identity", {"case_id": "c1", "input_name": "Mohammad Ali", "registry_name": "Muhammad Ali"}).json()
    assert body["name_match_score"] >= 0.95 and body["verdict"] == "confirmed" and body["action"] == "proceed"


def test_match_different_person_never_auto():
    body = post("match-identity", {"case_id": "c1", "input_name": "Zainab Khatoon", "registry_name": "Zenab Bibi"}).json()
    assert body["name_match_score"] < 0.70 and body["verdict"] == "mismatch" and body["action"] == "officer_review"


def test_match_abbreviation_is_uncertain():
    body = post("match-identity", {"submitted_name": "M. Afzal", "registry_name": "Muhammad Afzal"}).json()
    assert 0.70 <= body["match_score"] < 0.95 and body["verdict"] == "uncertain" and body["action"] == "officer_review"


def test_match_looks_up_registry_by_mock_id():
    body = post("match-identity", {"submitted_name": "Muhammad Ali", "mock_identity_id": "MOCK-123456"}).json()
    assert body["verdict"] == "confirmed" and body["candidates"][0]["name"] == "Muhammad Ali"
    r = post("match-identity", {"submitted_name": "X", "mock_identity_id": "MOCK-NOPE"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "IDENTITY_NOT_FOUND"


@pytest.mark.parametrize("body", [{}, {"input_name": "A"}, {"registry_name": "A"}])
def test_match_bad_input(body):
    assert post("match-identity", body).status_code == 422


@pytest.mark.parametrize("a,b", [("", ""), ("!!!", "Ali"), ("Ali " * 30, "Ali"), ("علی", "Ali"), ("Ali", None)])
def test_match_odd_names_do_not_crash(a, b):
    res = names.match_names(a, b)
    assert 0.0 <= res["score"] <= 1.0


def test_name_order_and_extra_parts_are_not_auto_matched():
    assert names.match_names("Ali Muhammad", "Muhammad Ali")["score"] < 0.95
    assert names.match_names("Muhammad Ali", "Muhammad Ali Khan")["score"] < 0.95


# ---------------------------------------------------------------------------
# duplicates
# ---------------------------------------------------------------------------
def claim(case_id, **over):
    return {"case_id": case_id, "citizen_id": f"cit-{case_id}", "mock_identity_id": "MOCK-123456",
            "name": "Muhammad Ali", "dob": "1990-05-12", "account_id": f"MOCK-ACCOUNT-{case_id}", **over}


def test_clean_claim_has_no_duplicate():
    body = post("detect-duplicates", claim("c1")).json()
    assert body["duplicate_flag"] is False and body["action"] == "allow" and body["matches"] == []


def test_second_claim_same_identity_is_blocked_but_retry_is_not():
    post("detect-duplicates", claim("c1"))
    again = post("detect-duplicates", claim("c1")).json()     # same case re-processed
    assert again["duplicate_flag"] is False
    second = post("detect-duplicates", claim("c2")).json()    # a new case, same identity
    assert second["duplicate_flag"] is True and second["action"] == "block"
    assert second["existing_case_id"] == "c1" and second["matches"][0]["type"] == "same_identity"


def test_shared_payment_account_goes_to_officer():
    post("detect-duplicates", claim("c1", account_id="MOCK-ACCOUNT-9"))
    body = post("detect-duplicates", claim("c2", mock_identity_id="MOCK-100001", name="Hamza Qureshi",
                                          dob="1973-02-08", account_id="MOCK-ACCOUNT-9")).json()
    assert body["duplicate_flag"] is True and body["action"] == "officer_review"
    assert body["matches"][0]["type"] == "shared_payment_account"


def test_registry_near_duplicate_pair_is_caught():
    # demo data: MOCK-200003 "Mohammad Ali" and MOCK-200004 "Muhammad Ali", same birth date
    body = post("detect-duplicates", {"case_id": "c9", "mock_identity_id": "MOCK-200004",
                                      "name": "Muhammad Ali", "dob": "1985-03-14"}).json()
    assert body["duplicate_flag"] is True
    assert {"type": "possible_duplicate_identity", "mock_identity_id": "MOCK-200003"}.items() <= body["matches"][0].items()
    # name and dob can come from the registry when the caller only sends the id
    only_id = post("detect-duplicates", {"case_id": "c10", "mock_identity_id": "MOCK-200003"}).json()
    assert only_id["duplicate_flag"] is True


def test_duplicates_bad_input():
    assert post("detect-duplicates", {"case_id": "c1"}).status_code == 422


def _boom_session():
    class Boom:
        def connection(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def close(self):
            pass

    return Boom()


def test_duplicates_db_down_is_5xx_never_all_clear(monkeypatch):
    monkeypatch.setattr(shared_db, "SessionLocal", _boom_session)
    r = post("detect-duplicates", claim("c1"))
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True


def test_duplicates_db_down_non_strict_says_incomplete(monkeypatch):
    monkeypatch.setattr(shared_db, "SessionLocal", _boom_session)
    monkeypatch.setenv("AI_DUPLICATES_STRICT", "false")
    body = post("detect-duplicates", claim("c1")).json()
    assert body["complete"] is False and body["warnings"]


def test_unreachable_postgres_fails_fast_instead_of_hanging(monkeypatch):
    # Regression: psycopg can wait forever on Windows when Postgres is down.
    import time
    engine = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/x")
    monkeypatch.setattr(shared_db, "SessionLocal", sessionmaker(bind=engine))
    started = time.perf_counter()
    src = data_sources.rule("rules-v1")
    assert src.unreachable is True and time.perf_counter() - started < 5
    started = time.perf_counter()
    assert data_sources.rule("rules-v1").unreachable and time.perf_counter() - started < 0.1  # cached
    body = post("evaluate", {"case_id": "c1", "input": {}}).json()      # still answers, with defaults
    assert body["auditor_trace"]["thresholds_source"] == "built_in_defaults"


def _platform_tables(engine):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE citizens (id VARCHAR PRIMARY KEY, tenant_id VARCHAR, mock_identity_id VARCHAR)"))
        c.execute(text("CREATE TABLE cases (id VARCHAR PRIMARY KEY, tenant_id VARCHAR, citizen_id VARCHAR, "
                       "status VARCHAR, data TEXT, claim_type VARCHAR)"))
        c.execute(text("CREATE TABLE rules (id VARCHAR, tenant_id VARCHAR, version INTEGER, rule_name VARCHAR, "
                       "conditions_json TEXT, active BOOLEAN)"))
        c.execute(text("CREATE TABLE case_documents (id VARCHAR PRIMARY KEY, file_path TEXT, content_type VARCHAR, type VARCHAR)"))


def test_duplicates_read_platform_cases(env):
    _platform_tables(env)
    with env.begin() as c:
        c.execute(text("INSERT INTO citizens VALUES ('z1', 't1', 'MOCK-123456')"))
        c.execute(text("INSERT INTO cases VALUES ('old', 't1', 'z1', 'human_review', :d, 'relief_payment')"),
                  {"d": json.dumps({"name": "Muhammad Ali", "mock_identity_id": "MOCK-123456"})})
        c.execute(text("INSERT INTO cases VALUES ('gone', 't1', 'z1', 'rejected', '{}', 'relief_payment')"))
    body = post("detect-duplicates", claim("new")).json()
    assert body["duplicate_flag"] is True and body["existing_case_id"] == "old"
    assert body["existing_status"] == "human_review" and "platform_cases" in body["sources_checked"]


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------
CLEAN = {"identity_verified": True, "name_match_score": 0.93, "document_quality": 0.95,
         "duplicate_flag": False, "scam_flag": False, "monthly_income": 20000}
CONTRACT_KEYS = {"case_id", "route", "confidence", "risk_score", "flags", "rule_version", "model_version",
                 "user_explanation", "auditor_trace"}


def evaluate(inp, **extra):
    return post("evaluate", {"case_id": "c1", "rule_version": "rules-v1", "input": inp, **extra})


def test_evaluate_contract_shape():
    r = evaluate({**CLEAN, "name_match_score": 1.0})
    body = r.json()
    assert r.status_code == 200 and CONTRACT_KEYS <= body.keys()
    assert body["route"] == "cleared" and body["rule_version"] == "rules-v1" and body["model_version"] == "m2-v1"
    assert 0 <= body["confidence"] <= 1 and 0 <= body["risk_score"] <= 1
    json.dumps(body["auditor_trace"])   # stored by the platform, must serialise
    assert body["auditor_trace"]["routing_reason"] and body["auditor_trace"]["thresholds_source"] == "built_in_defaults"


def test_evaluate_uncertain_name_goes_to_officer_with_reason():
    body = evaluate(CLEAN).json()      # 0.93: close but not confirmed
    assert body["route"] == "human_review" and "name_match_uncertain" in body["flags"]
    assert "officer" in body["user_explanation"].lower()


def test_evaluate_null_is_unknown_not_good():
    assert evaluate({**CLEAN, "name_match_score": None}).json()["route"] == "human_review"
    body = evaluate({**CLEAN, "name_match_score": 1.0, "document_quality": None}).json()
    assert body["route"] == "needs_proof" and "identity_document" in body["missing_evidence"]


@pytest.mark.parametrize("flag,expected_flag", [("duplicate_flag", "duplicate_claim"), ("scam_flag", "scam_suspected")])
def test_evaluate_critical_flags_force_officer(flag, expected_flag):
    body = evaluate({**CLEAN, "name_match_score": 1.0, flag: True}).json()
    assert body["route"] == "human_review" and expected_flag in body["flags"] and body["risk_score"] > 0.5


def test_evaluate_blurry_document_needs_proof():
    body = evaluate({**CLEAN, "name_match_score": 1.0, "document_quality": 0.2}).json()
    assert body["route"] == "needs_proof" and "document_quality_low" in body["flags"]


def test_evaluate_reads_rule_thresholds_from_platform_table(env):
    _platform_tables(env)
    with env.begin() as c:
        c.execute(text("INSERT INTO rules VALUES ('r1', 't1', 1, 'relief', :c, 0)"),
                  {"c": json.dumps({"max_monthly_income": 50000, "clear_confidence_min": 0.95, "proof_confidence_min": 0.7})})
        c.execute(text("INSERT INTO rules VALUES ('r2', 't1', 2, 'relief', :c, 1)"),
                  {"c": json.dumps({"max_monthly_income": 30000, "clear_confidence_min": 0.95, "proof_confidence_min": 0.7})})
    inp = {**CLEAN, "name_match_score": 1.0, "monthly_income": 40000}
    active = post("evaluate", {"case_id": "c1", "input": inp}).json()
    assert active["route"] == "human_review" and active["rule_version"] == 2
    assert active["auditor_trace"]["thresholds_source"] == "platform_rules_table"
    # an old decision re-evaluated under version 1 keeps version 1's limit
    old = post("evaluate", {"case_id": "c1", "rule_version": 1, "input": inp}).json()
    assert old["route"] == "cleared" and old["rule_version"] == 1


def test_evaluate_rules_sent_in_request_win():
    body = evaluate({**CLEAN, "name_match_score": 1.0, "monthly_income": 48000},
                    rules={"version": "rules-v2", "rules": [{"field": "monthly_income", "op": "lte", "value": 45000}]}).json()
    assert body["route"] == "human_review" and "income_above_limit" in body["flags"]


@pytest.mark.parametrize("bad", [{"name_match_score": 1.5}, {"document_quality": -1}, {"monthly_income": -5}])
def test_evaluate_bad_input(bad):
    r = evaluate({**CLEAN, **bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("route", ["cleared", "needs_proof", "human_review"])
def test_explain_every_route_plain_and_no_money_promise(route):
    body = post("explain", {"case_id": "c1", "route": route, "flags": ["low_name_match", "document_quality_low"],
                            "rule_version": "rules-v1"}).json()
    text_ = body["user_explanation"]
    assert text_.strip() and body["user_explanation_ur"].strip()
    for banned in ("you will receive", "payment is approved", "money will", "guarantee", "flag", "_"):
        assert banned not in text_.lower()


def test_explain_cleared_says_officer_decides():
    assert "officer" in post("explain", {"route": "cleared"}).json()["user_explanation"].lower()


def test_explain_urdu_and_unknown_flags():
    body = post("explain", {"route": "human_review", "flags": ["weird_internal_flag"], "language": "ur"}).json()
    assert "افسر" in body["user_explanation"] and "weird" not in body["user_explanation"]


def test_explain_bad_route():
    assert post("explain", {"route": "approved"}).status_code == 422


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------
def upload(img_bytes, doc_type="id_card", **form):
    return client.post("/internal/ai/extract-document", headers=KEY,
                       files={"file": ("card.png", img_bytes, "image/png")}, data={"document_type": doc_type, **form})


def test_sharp_card_passes_quality():
    body = upload(png(evaluation.synthetic_card())).json()
    assert body["quality_ok"] is True and body["quality"] >= 0.6 and body["quality_note"] is None
    assert set(body["extracted_fields"]) >= {"name", "identity_number", "date_of_birth"}


def test_blurry_card_asks_for_rescan():
    body = upload(png(evaluation.synthetic_card().filter(ImageFilter.GaussianBlur(4)))).json()
    assert body["quality_ok"] is False and "blurry" in body["quality_note"].lower()
    assert body["suggested_action"] == body["quality_note"]


def test_fields_from_text_with_form_comparison():
    text_ = "Name: Muhammad Ali\nFather Name: Abdul Rahim\nIdentity Number: MOCK-123456\nDate of Birth: 12.05.1990"
    body = upload(png(evaluation.synthetic_card()), text=text_,
                  expected=json.dumps({"name": "Zainab Khatoon", "mock_identity_id": "MOCK-123456"})).json()
    f = body["extracted_fields"]
    assert f["name"]["value"] == "Muhammad Ali" and f["name"]["confidence"] > 0.8
    assert f["identity_number"]["value"] == "MOCK-123456" and f["date_of_birth"]["value"] == "1990-05-12"
    assert body["inconsistency_flags"] == ["name_differs_from_form"]


def test_unreadable_field_is_never_invented():
    body = post("extract-document", {"document_type": "id_card", "text": "Name: Rashid Khan\nDate of Birth: ----"}).json()
    dob = body["extracted_fields"]["date_of_birth"]
    assert dob["value"] is None and dob["confidence"] == 0.0 and "manually" in dob["warning"]


def test_ocr_is_used_when_available(monkeypatch):
    monkeypatch.setattr(documents, "run_ocr", lambda img: "Name: Muhammad Ali\nIdentity Number: 42101-1234567-1")
    monkeypatch.setattr(documents, "ocr_engine", lambda: "tesseract-test")
    body = upload(png(evaluation.synthetic_card())).json()
    assert body["extracted_fields"]["identity_number"]["value"] == "42101-1234567-1"
    assert body["text_source"] == "tesseract-test"


def test_agent_shape_with_reported_quality():
    body = post("extract-document", {"case_id": "c1", "document": {"id": "d1", "type": "identity_document", "quality": 0.95}}).json()
    assert body["quality"] == 0.95 and body["document_type"] == "identity_document" and "fields" in body
    assert body["quality_source"] == "reported_by_caller"


def test_agent_shape_with_base64_beats_reported_quality():
    blurry = png(evaluation.synthetic_card().filter(ImageFilter.GaussianBlur(5)))
    body = post("extract-document", {"case_id": "c1", "document": {
        "id": "d1", "type": "identity_document", "quality": 0.99,
        "content_base64": base64.b64encode(blurry).decode()}}).json()
    assert body["quality_source"] == "image_analysis" and body["quality"] < 0.6


def test_document_found_through_platform_record(env, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    (tmp_path / "abc").write_bytes(png(evaluation.synthetic_card()))
    _platform_tables(env)
    with env.begin() as c:
        c.execute(text("INSERT INTO case_documents VALUES ('d1', :p, 'image/png', 'identity_proof')"),
                  {"p": str(tmp_path / "abc")})
    body = post("extract-document", {"case_id": "c1", "document": {"id": "d1", "type": "identity_proof"}}).json()
    assert body["content_source"] == "platform_document" and body["quality_ok"] is True


def test_file_path_outside_upload_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    r = post("extract-document", {"document": {"id": "d1", "type": "id_card", "file_path": str(tmp_path / "secret.png")}})
    assert r.status_code == 422


@pytest.mark.parametrize("body,code", [
    ({"document": {"id": "d1", "type": "id_card"}}, "DOCUMENT_UNREADABLE"),               # nothing to analyse
    ({"document": {"type": "id_card", "content_base64": "%%%"}}, "VALIDATION_ERROR"),
    ({"document": {"type": "id_card", "content_base64": base64.b64encode(b"not an image").decode()}}, "DOCUMENT_UNREADABLE"),
    ({"document": {"type": "id_card", "content_base64": base64.b64encode(b"%PDF-1.4 ...").decode()}}, "DOCUMENT_UNREADABLE"),
    ({"document": {"type": "id_card", "quality": 3}}, "VALIDATION_ERROR"),
])
def test_document_errors_are_4xx_not_fake_quality(body, code):
    r = post("extract-document", body)
    assert 400 <= r.status_code < 500 and r.json()["error"]["code"] == code


def test_multipart_without_file():
    r = client.post("/internal/ai/extract-document", headers=KEY, files={"x": ("a", b"1")}, data={"document_type": "id_card"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def test_metrics_are_measured():
    body = client.get("/api/ai/metrics").json()
    s = body["scam_detection"]
    assert s["test_cases"] >= 40 and 0 <= s["false_alarm_rate"] <= 1 and 0 <= s["missed_scam_rate"] <= 1
    assert s["holdout"]["test_cases"] >= 20
    assert body["routing"]["test_cases"] >= 20 and body["routing"]["unsafe_auto_clears"] == 0
    assert body["name_matching"]["false_auto_match_rate"] == 0
    assert body["ocr"]["image_quality"]["bad_images_accepted"] == 0
    assert body["ocr"]["field_extraction"]["invented_values"] == 0
    assert body["model_version"] == "m2-v1" and "synthetic" in body["note"].lower()


def test_internal_metrics_need_key():
    assert client.get("/internal/ai/metrics").status_code == 403
    assert client.get("/internal/ai/metrics", headers=KEY).status_code == 200
