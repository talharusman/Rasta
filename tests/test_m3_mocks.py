# OWNER: Member 3. Tests for the mock NADRA / Raast / SMS services.
# Run from the repo root:  python -m pytest tests/test_m3_mocks.py -v
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.agent import platform_bridge  # noqa: E402
from app.integrations.mocks import control  # noqa: E402
from app.integrations.mocks.fixtures import seed_mocks  # noqa: E402
from app.integrations.mocks.models import MOCK_MODELS, MockTransaction  # noqa: E402
from app.integrations.mocks.router import admin_router, internal_router, router  # noqa: E402
from shared import db as shared_db  # noqa: E402

# SQLite has no native Decimal; SQLAlchemy warns but the values are correct.
pytestmark = pytest.mark.filterwarnings("ignore:Dialect sqlite")

NADRA = {"X-Mock-Api-Key": "nadra-test"}
RAAST = {"X-Mock-Api-Key": "raast-test"}
SMS = {"X-Mock-Api-Key": "sms-test"}
INTERNAL = {"X-Service-Key": "internal-test"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("NADRA_MOCK_KEY", "nadra-test")
    monkeypatch.setenv("RAAST_MOCK_KEY", "raast-test")
    monkeypatch.setenv("SMS_MOCK_KEY", "sms-test")
    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "internal-test")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mocks.db'}", connect_args={"check_same_thread": False}
    )
    shared_db.Base.metadata.create_all(engine, tables=[m.__table__ for m in MOCK_MODELS])
    factory = sessionmaker(bind=engine, autoflush=False)
    # get_db and the control module both look up shared.db.SessionLocal at call time.
    monkeypatch.setattr(shared_db, "SessionLocal", factory)
    seed_mocks(reset=True)
    platform_bridge.STUB_AUDIT_LOG.clear()
    yield factory
    engine.dispose()


@pytest.fixture()
def client(env):
    app = FastAPI()
    app.include_router(router)
    app.include_router(internal_router)
    app.include_router(admin_router)
    return TestClient(app)


def verify(client, cit_id="MOCK-123456", name="Muhammad Ali"):
    return client.post("/mock/nadra/verify", json={"cit_id": cit_id, "full_nm": name}, headers=NADRA)


def disburse(client, key="disburse-case-1", amt=5000, acct="MOCK-ACCOUNT-001", **over):
    body = {"case_id": "case-1", "amt": amt, "acct": acct, "approval_ref": "APR-1", **over}
    headers = dict(RAAST)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post("/mock/raast/disburse", json=body, headers=headers)


# --- auth ------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,body",
    [
        ("/mock/nadra/verify", {"cit_id": "MOCK-123456", "full_nm": "x"}),
        ("/mock/raast/account-validate", {"acct": "MOCK-ACCOUNT-001", "beneficiary_nm": "x"}),
        ("/mock/sms/send", {"to": "+920000000000", "text": "hi", "ref": "c1"}),
    ],
)
def test_wrong_or_missing_key_is_401(client, path, body):
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers={"X-Mock-Api-Key": "wrong"}).status_code == 401
    # A key for a different service must not work either.
    assert client.post(path, json=body, headers={"X-Mock-Api-Key": "internal-test"}).status_code == 401


def test_401_uses_native_format(client):
    r = client.post("/mock/nadra/verify", json={"cit_id": "MOCK-123456", "full_nm": "x"})
    assert r.json()["resp_code"] == "99" and r.json()["citizens"] == []
    r = client.post("/mock/raast/disburse", json={})
    assert r.status_code == 401 and r.json()["stat"] == "RJCT"


# --- NADRA -----------------------------------------------------------------
def test_verify_clean_identity_found(client):
    r = verify(client)
    body = r.json()
    assert r.status_code == 200 and body["resp_code"] == "00"
    assert body["citizens"][0]["cit_id"] == "MOCK-123456"
    assert body["citizens"][0]["full_nm"] == "Muhammad Ali"
    assert body["citizens"][0]["rec_status"] == "ACTIVE"


def test_verify_zenab_found(client):
    body = verify(client, "MOCK-200001", "Zenab Bibi").json()
    assert body["resp_code"] == "00"
    assert "Zenab" in body["citizens"][0]["full_nm"]


def test_verify_unknown_not_found(client):
    assert verify(client, "MOCK-999999").json()["resp_code"] == "01"


def test_records_endpoint_and_special_seeds(client):
    assert client.get("/mock/nadra/records/MOCK-200002", headers=NADRA).json()["citizens"][0]["birth_dt"] is None
    assert client.get("/mock/nadra/records/MOCK-200005", headers=NADRA).json()["citizens"][0]["rec_status"] == "BLOCKED"


def test_malformed_fixture_id_returns_invalid_json(client):
    r = verify(client, "MOCK-MALFORMED-01")
    with pytest.raises(ValueError):
        r.json()


def test_timeout_fixture_id_sleeps(client, monkeypatch):
    monkeypatch.setattr(control, "TIMEOUT_SECONDS", 0.3)
    import time

    start = time.monotonic()
    assert verify(client, "MOCK-TIMEOUT-01").status_code == 200
    assert time.monotonic() - start >= 0.3


def test_duplicated_response_returns_two_citizens(client):
    client.put("/internal/mock-control", json={"duplicated_response": True}, headers=INTERNAL)
    citizens = verify(client).json()["citizens"]
    assert len(citizens) == 2 and citizens[0] == citizens[1]


def test_identity_mismatch_changes_name(client):
    client.put("/internal/mock-control", json={"identity_mismatch": True}, headers=INTERNAL)
    assert verify(client).json()["citizens"][0]["full_nm"] != "Muhammad Ali"


def test_nadra_outage_and_malformed_switch(client):
    client.put("/internal/mock-control", json={"nadra_outage": True}, headers=INTERNAL)
    assert verify(client).status_code == 503
    client.put("/internal/mock-control", json={"nadra_outage": False, "malformed_response": True}, headers=INTERNAL)
    with pytest.raises(ValueError):
        verify(client).json()


# --- Raast -----------------------------------------------------------------
def test_account_validate(client):
    def check(acct, name):
        return client.post(
            "/mock/raast/account-validate", json={"acct": acct, "beneficiary_nm": name}, headers=RAAST
        ).json()["stat"]

    assert check("MOCK-ACCOUNT-001", "muhammad  ali") == "MATCH"
    assert check("MOCK-ACCOUNT-006", "Ayesha Siddiqui") == "NOMATCH"
    assert check("MOCK-ACCOUNT-404", "x") == "NOTFOUND"


def test_disburse_same_key_twice_returns_same_txn_one_row(client, env):
    first, second = disburse(client), disburse(client)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["stat"] == "ACSC" and first.json()["txnRef"]
    with env() as s:
        assert s.scalar(select(func.count()).select_from(MockTransaction)) == 1


def test_disburse_same_key_different_amount_is_409(client, env):
    original = disburse(client).json()
    r = disburse(client, amt=9999)
    assert r.status_code == 409
    assert r.json()["txnRef"] == original["txnRef"]
    assert disburse(client, acct="MOCK-ACCOUNT-002").status_code == 409
    with env() as s:
        assert s.scalar(select(func.count()).select_from(MockTransaction)) == 1


def test_disburse_missing_idempotency_key_is_400(client):
    assert disburse(client, key=None).status_code == 400


def test_disburse_missing_approval_ref_is_400(client):
    assert disburse(client, approval_ref=None).status_code == 400
    assert disburse(client, key="k2", approval_ref="  ").status_code == 400


def test_disburse_unknown_account_stores_nothing(client, env):
    assert disburse(client, acct="MOCK-ACCOUNT-404").status_code == 422
    with env() as s:
        assert s.scalar(select(func.count()).select_from(MockTransaction)) == 0


def test_transaction_lookup_by_ref_and_by_key(client):
    txn = disburse(client).json()
    by_ref = client.get(f"/mock/raast/transactions/{txn['txnRef']}", headers=RAAST)
    by_key = client.get("/mock/raast/transactions", params={"idempotency_key": "disburse-case-1"}, headers=RAAST)
    assert by_ref.json() == by_key.json() == txn
    miss = client.get("/mock/raast/transactions", params={"idempotency_key": "nope"}, headers=RAAST)
    assert miss.status_code == 404


def test_raast_outage_is_503(client):
    client.put("/internal/mock-control", json={"raast_outage": True}, headers=INTERNAL)
    assert disburse(client).status_code == 503
    assert client.get("/mock/raast/transactions/x", headers=RAAST).status_code == 503


# --- SMS -------------------------------------------------------------------
def send_sms(client):
    return client.post("/mock/sms/send", json={"to": "+920000000000", "text": "hi", "ref": "c1"}, headers=SMS)


def test_sms_delivered_by_default(client):
    sent = send_sms(client).json()
    assert sent["dlr"] == "ACCEPTD"
    assert client.get(f"/mock/sms/messages/{sent['msg_id']}", headers=SMS).json()["dlr"] == "DELIVRD"


def test_sms_failure_switch_gives_undeliv(client):
    client.put("/internal/mock-control", json={"sms_failure": True}, headers=INTERNAL)
    sent = send_sms(client).json()
    assert sent["dlr"] == "ACCEPTD"
    assert client.get(f"/mock/sms/messages/{sent['msg_id']}", headers=SMS).json()["dlr"] == "UNDELIV"
    # Switching it off later does not change an already-sent message.
    client.put("/internal/mock-control", json={"sms_failure": False}, headers=INTERNAL)
    assert client.get(f"/mock/sms/messages/{sent['msg_id']}", headers=SMS).json()["dlr"] == "UNDELIV"


# --- control ---------------------------------------------------------------
def test_control_requires_internal_key(client):
    for headers in ({}, {"X-Service-Key": "wrong"}, NADRA):
        r = client.get("/internal/mock-control", headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_control_validation_and_reset(client):
    bad = client.put("/internal/mock-control", json={"nope": True}, headers=INTERNAL)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.put("/internal/mock-control", json={"latency_ms": "slow"}, headers=INTERNAL).status_code == 422
    client.put("/internal/mock-control", json={"raast_outage": True, "latency_ms": 5}, headers=INTERNAL)
    assert client.get("/internal/mock-control", headers=INTERNAL).json()["raast_outage"] is True
    after = client.delete("/internal/mock-control", headers=INTERNAL).json()
    assert after == control.DEFAULT_CONDITIONS


def test_switch_changes_are_audited(client):
    client.put("/internal/mock-control", json={"sms_failure": True}, headers=INTERNAL)
    client.delete("/internal/mock-control", headers=INTERNAL)
    actions = [e["action"] for e in platform_bridge.STUB_AUDIT_LOG]
    assert actions == ["mock_conditions.update", "mock_conditions.reset"]
    assert platform_bridge.STUB_AUDIT_LOG[0]["metadata"]["changed"]["sms_failure"] == {"from": False, "to": True}


def test_admin_route_uses_admin_dependency(client):
    assert client.get("/api/v1/admin/mock-conditions").status_code == 403
    r = client.put("/api/v1/admin/mock-conditions", json={"nadra_outage": True}, headers=INTERNAL)
    assert r.status_code == 200 and r.json()["nadra_outage"] is True
    assert platform_bridge.STUB_AUDIT_LOG[-1]["actor_type"] == "admin"
