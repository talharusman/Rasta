# OWNER: Member 3. Tests for the case-processing agent (stub platform + stub/fake AI +
# the real mock services in-process). Run from the repo root:
#   python -m pytest tests/test_m3_agent.py -v
import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent import ai_client, orchestrator, platform_bridge, router as agent_router, tools  # noqa: E402
from app.agent.consent_config import PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE  # noqa: E402
from app.agent.models import AGENT_MODELS, AgentRun  # noqa: E402
from app.integrations.mocks import control  # noqa: E402
from app.integrations.mocks.fixtures import seed_mocks  # noqa: E402
from app.integrations.mocks.models import MOCK_MODELS, MockTransaction  # noqa: E402
from app.integrations.mocks.router import router as mock_router  # noqa: E402
from app.integrations.providers import http as provider_http  # noqa: E402
from app.integrations.providers import registry  # noqa: E402
from app.integrations.providers.http import ServiceClient  # noqa: E402
from app.integrations.providers.identity import MockNadraIdentityProvider  # noqa: E402
from app.integrations.providers.models import PROVIDER_MODELS  # noqa: E402
from app.integrations.providers.notification import MockSmsNotificationProvider  # noqa: E402
from shared import db as shared_db  # noqa: E402

pytestmark = [pytest.mark.asyncio, pytest.mark.filterwarnings("ignore:Dialect sqlite")]


@pytest.fixture()
def world(monkeypatch, tmp_path):
    for var, val in [("NADRA_MOCK_KEY", "nadra-test"), ("SMS_MOCK_KEY", "sms-test"),
                     ("RAAST_MOCK_KEY", "raast-test"), ("INTERNAL_SERVICE_KEY", "internal-test"),
                     ("AI_STUB", "true"), ("AI_BASE_URL", "http://ai")]:
        monkeypatch.setenv(var, val)
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}", connect_args={"check_same_thread": False})
    shared_db.Base.metadata.create_all(
        engine, tables=[m.__table__ for m in MOCK_MODELS + PROVIDER_MODELS + AGENT_MODELS])
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(shared_db, "SessionLocal", factory)
    seed_mocks(reset=True)
    platform_bridge.stub_reset()
    monkeypatch.setattr(provider_http, "RETRY_BACKOFF", (0.01, 0.01, 0.01))
    monkeypatch.setattr(ai_client, "RETRY_DELAY", 0.01)

    app = FastAPI()
    app.include_router(mock_router)
    transport = httpx.ASGITransport(app=app)
    # Short timeouts so the "mock service is down/slow" tests are quick.
    nadra = MockNadraIdentityProvider(ServiceClient("nadra", "http://mock", "nadra-test", timeout=0.3, transport=transport))
    sms = MockSmsNotificationProvider(ServiceClient("sms", "http://mock", "sms-test", timeout=0.3, transport=transport))
    monkeypatch.setattr(registry, "get_identity_provider", lambda: nadra)
    monkeypatch.setattr(registry, "get_notification_provider", lambda: sms)

    def count(model):
        with factory() as s:
            return s.scalar(select(func.count()).select_from(model))

    yield SimpleNamespace(count=count, factory=factory)
    ai_client.set_transport(None)
    engine.dispose()


def add_case(case_id="case-1", grant_consent=True, **over):
    case = {
        "id": case_id, "status": "submitted", "citizen_id": "cit-1", "mock_identity_id": "MOCK-123456",
        "applicant_name": "Muhammad Ali", "dob": "1990-05-12", "monthly_income": 20000,
        "documents": [{"id": "doc-1", "type": "identity_document", "quality": 0.95}],
        "message": None, "citizen_phone": "+920000000001", **over,
    }
    return platform_bridge.stub_add_case(case, grant_consent=grant_consent)


def status_of(case_id="case-1"):
    return platform_bridge.get_case(case_id)["status"]


def last_decision(case_id="case-1"):
    return platform_bridge.STUB_DECISIONS[case_id][-1]


def step_names(run):
    return [s["step"] for s in run["steps"]]


async def wait_done(run_id, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        run = await asyncio.to_thread(orchestrator.load_run, run_id)
        if run["status"] != "running":
            return run
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


# --- the main paths ---------------------------------------------------------------------
async def test_clean_case_is_cleared(world):
    add_case()
    run = await orchestrator.process_case("case-1", "test")
    assert run["status"] == "cleared" and run["error"] is None and run["mode"] == "deterministic"
    assert status_of() == "cleared"  # cleared, NOT approved: no financial authority
    assert len(run["steps"]) >= 10
    names = step_names(run)
    for expected in ("get_case_details", "check_consent", "verify_mock_identity", "match_identity_name",
                     "analyze_document", "find_duplicate_claims", "evaluate_eligibility", "evaluate_route",
                     "record_decision", "mark_cleared", "send_notification"):
        assert expected in names
    decision = last_decision()
    assert decision["route"] == "cleared" and decision["rule_version"] == "rules-v1"
    assert decision["model_version"] == "stub-v1" and decision["user_explanation"]
    assert "steps" in decision["auditor_trace"] and "evaluate_route" in decision["auditor_trace"]["steps"]
    assert world.count(MockTransaction) == 0  # no money moved
    # every step is audited, always as an agent
    audited = [e["action"] for e in platform_bridge.STUB_AUDIT_LOG if e["action"].startswith("agent_step.")]
    assert len(audited) == len(run["steps"])
    assert all(e["actor_type"] == "agent" for e in platform_bridge.STUB_AUDIT_LOG)
    assert platform_bridge.STUB_NOTIFICATIONS and platform_bridge.STUB_NOTIFICATIONS[0]["case_id"] == "case-1"


async def test_low_name_score_goes_to_officer_with_notes(world):
    add_case(mock_identity_id="MOCK-200001", applicant_name="Zainab Khatoon")
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and status_of() == "human_review"
    assert "low_name_match" in last_decision()["flags"]
    note = platform_bridge.get_case("case-1")["last_note"]
    assert "name_match_score=" in note and "Zainab Khatoon" in note and "Zenab Bibi" in note
    assert "Suggested questions" in note and "Already tried" in note
    escalate = next(s for s in run["steps"] if s["step"] == "escalate_to_officer")
    assert set(escalate["output"]["packet"]) >= {"summary", "why_stopped", "evidence", "what_was_tried",
                                                 "suggested_questions"}


async def test_nadra_timeout_is_human_review_never_cleared(world):
    add_case()
    control.set_conditions({"nadra_timeout": True})
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and status_of() == "human_review"
    assert "service_unavailable" in last_decision()["flags"]
    ident = next(s for s in run["steps"] if s["step"] == "verify_mock_identity")
    assert ident["status"] == "unavailable"
    assert last_decision()["auditor_trace"]["safety_override"] is True
    assert "cleared" not in [t["to"] for t in platform_bridge.STUB_TRANSITIONS]


async def test_ai_service_down_is_human_review(world, monkeypatch):
    add_case()
    monkeypatch.delenv("AI_STUB")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(503, json={"detail": "down"})

    ai_client.set_transport(httpx.MockTransport(handler))
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and status_of() == "human_review"
    assert "service_unavailable" in last_decision()["flags"]
    assert last_decision()["confidence"] is None  # nothing was faked
    by_name = {s["step"]: s for s in run["steps"]}
    assert by_name["evaluate_route"]["status"] == "unavailable"
    assert len(calls) == 2  # one try + one retry, then the rest of the run does not wait on AI again
    assert "cleared" not in [t["to"] for t in platform_bridge.STUB_TRANSITIONS]


async def test_missing_document_needs_proof(world):
    add_case(documents=[])
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "needs_proof" and status_of() == "needs_proof"
    assert "identity_document" in last_decision()["missing_evidence"]
    names = step_names(run)
    assert "request_more_evidence" in names and "mark_cleared" not in names
    assert "identity_document" in platform_bridge.get_case("case-1")["last_note"]


@pytest.mark.parametrize("who,revoke,code", [
    ("department", True, "CONSENT_REVOKED"),
    ("department", False, "CONSENT_REQUIRED"),
])
async def test_consent_problem_stops_the_run(world, who, revoke, code):
    add_case(grant_consent=revoke)
    if revoke:
        platform_bridge.stub_revoke_consent("cit-1", PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE)
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and status_of() == "human_review"
    assert last_decision()["code"] == code and code in last_decision()["flags"]
    names = step_names(run)
    assert "verify_mock_identity" not in names and "evaluate_route" not in names  # stopped early
    assert world.count(MockTransaction) == 0
    assert platform_bridge.get_case("case-1")["last_note"].count(code) >= 1


async def test_revoked_helper_consent_stops_the_run(world):
    add_case(helper_id="helper-1")
    platform_bridge.stub_revoke_consent("cit-1", "helper-1", PROCESSING_SCOPE)
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and last_decision()["code"] == "CONSENT_REVOKED"
    consent_steps = [s for s in run["steps"] if s["step"] == "check_consent"]
    assert [s["output"]["who"] for s in consent_steps] == ["department", "helper"]


# --- other safety paths -------------------------------------------------------------------
async def test_scam_message_forces_human_review(world):
    add_case(message="Send money as a processing fee to receive your relief")
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and "scam_suspected" in last_decision()["flags"]


async def test_duplicate_identity_forces_human_review(world):
    add_case(mock_identity_id="MOCK-200003", applicant_name="Mohammad Ali", dob="1985-03-14")
    control.set_conditions({"duplicated_response": True})
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and "duplicate_claim" in last_decision()["flags"]


async def test_failed_eligibility_rule_goes_to_officer(world):
    add_case(monthly_income=900000)
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "human_review" and "eligibility_failed" in last_decision()["flags"]


async def test_missing_rule_field_needs_proof(world):
    add_case(monthly_income=None)
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "needs_proof" and "field:monthly_income" in last_decision()["missing_evidence"]


async def test_case_not_submitted_is_skipped(world):
    add_case(status="cleared")
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "skipped" and platform_bridge.STUB_TRANSITIONS == []


async def test_failure_midway_never_leaves_case_processing(world, monkeypatch):
    add_case()

    def boom(case_id, decision):
        raise RuntimeError("database down")

    monkeypatch.setattr(platform_bridge, "record_decision", boom)
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "failed" and "decision could not be recorded" in run["error"]
    assert status_of() == "human_review"  # handed to an officer, not stuck in processing
    assert "agent_error" in platform_bridge.get_case("case-1")["last_note"]


async def test_run_timeout_hands_case_to_officer(world, monkeypatch):
    add_case()
    monkeypatch.setattr(orchestrator, "RUN_TIMEOUT", 0.05)
    monkeypatch.delenv("AI_STUB")

    async def slow(request):
        await asyncio.sleep(2)

    ai_client.set_transport(httpx.MockTransport(slow))
    run = await orchestrator.process_case("case-1")
    assert run["status"] == "failed" and "timed out" in run["error"]
    assert status_of() == "human_review"


# --- double processing --------------------------------------------------------------------
async def test_submitting_twice_gives_one_run(world):
    add_case()
    a, b = await asyncio.gather(orchestrator.process_case("case-1"), orchestrator.process_case("case-1"))
    assert a["id"] == b["id"]
    assert world.count(AgentRun) == 1
    assert [t["to"] for t in platform_bridge.STUB_TRANSITIONS].count("processing") == 1


async def test_start_case_processing_twice_returns_same_run(world):
    add_case()
    first = agent_router.start_case_processing("case-1")
    second = agent_router.start_case_processing("case-1")
    assert first == second
    run = await wait_done(first)
    assert run["status"] == "cleared" and world.count(AgentRun) == 1


async def test_start_case_processing_from_a_plain_thread(world):
    """A sync FastAPI route has no running loop: it must still work."""
    add_case()
    run_id = await asyncio.to_thread(agent_router.start_case_processing, "case-1")
    assert (await wait_done(run_id))["status"] == "cleared"


# --- HTTP routes --------------------------------------------------------------------------
async def test_internal_routes(world):
    add_case()
    app = FastAPI()
    app.include_router(agent_router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as client:
        key = {"X-Service-Key": "internal-test"}
        denied = await client.post("/internal/agent/process-case", json={"case_id": "case-1"})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
        bad = await client.post("/internal/agent/process-case", json={}, headers=key)
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
        ok = await client.post("/internal/agent/process-case", json={"case_id": "case-1"}, headers=key)
        assert ok.status_code == 202
        run_id = ok.json()["run_id"]
        run = await wait_done(run_id)
        got = await client.get(f"/internal/agent/runs/{run_id}", headers=key)
        assert got.status_code == 200 and got.json()["status"] == run["status"] == "cleared"
        assert (await client.get(f"/internal/agent/runs/{run_id}")).status_code == 403
        assert (await client.get("/internal/agent/runs/nope", headers=key)).status_code == 404


# --- no approve / disburse tool -----------------------------------------------------------
async def test_agent_has_no_approve_or_disburse_tool():
    assert set(tools.TOOLS) == {
        "get_case_details", "check_consent", "verify_mock_identity", "analyze_document", "check_scam_message",
        "find_duplicate_claims", "evaluate_eligibility", "request_more_evidence", "escalate_to_officer",
        "record_decision", "send_notification", "match_identity_name", "evaluate_route", "explain",
    }
    public = [n for n, v in vars(tools).items() if inspect.isfunction(v) and not n.startswith("_")]
    for name in list(tools.TOOLS) + public:
        assert "approve" not in name.lower() and "disburse" not in name.lower() and "pay" not in name.lower(), name
    for module in (tools, orchestrator):
        source = inspect.getsource(module)
        assert "get_payment_provider" not in source and "MockRaastPaymentProvider" not in source
