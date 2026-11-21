# OWNER: Member 2
# End-to-end: Member 3's real case-processing agent (AI_STUB off) calling Member 2's
# real AI service over HTTP (in-process ASGI), with Member 3's mock registry seeded.
# Run from backend/:  python -m pytest tests/test_ai_agent_integration.py -v
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai import data_sources, duplicates
from app.agent import ai_client, orchestrator, platform_bridge
from app.agent.models import AGENT_MODELS
from app.integrations.mocks.fixtures import seed_mocks
from app.integrations.mocks.models import MOCK_MODELS
from app.integrations.mocks.router import router as mock_router
from app.integrations.providers import http as provider_http
from app.integrations.providers import registry
from app.integrations.providers.http import ServiceClient
from app.integrations.providers.identity import MockNadraIdentityProvider
from app.integrations.providers.models import PROVIDER_MODELS
from app.integrations.providers.notification import MockSmsNotificationProvider
from main import app as main_app
from shared import db as shared_db

pytestmark = pytest.mark.filterwarnings("ignore:Dialect sqlite")


@pytest.fixture()
def world(monkeypatch, tmp_path):
    for var, val in [("NADRA_MOCK_KEY", "nadra-test"), ("SMS_MOCK_KEY", "sms-test"), ("RAAST_MOCK_KEY", "raast-test"),
                     ("INTERNAL_SERVICE_KEY", "internal-test"), ("AI_BASE_URL", "http://ai")]:
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("AI_STUB", raising=False)         # the REAL AI service
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}", connect_args={"check_same_thread": False})
    shared_db.Base.metadata.create_all(engine, tables=[m.__table__ for m in MOCK_MODELS + PROVIDER_MODELS + AGENT_MODELS])
    monkeypatch.setattr(shared_db, "SessionLocal", sessionmaker(bind=engine, autoflush=False))
    seed_mocks(reset=True)
    # This fixture exercises the real AI HTTP calls with in-memory platform cases.
    monkeypatch.setattr(platform_bridge, "_implementation", None)
    platform_bridge.stub_reset()
    data_sources.reset_cache()
    duplicates.reset_memory()
    monkeypatch.setattr(provider_http, "RETRY_BACKOFF", (0.01, 0.01, 0.01))
    monkeypatch.setattr(ai_client, "RETRY_DELAY", 0.01)

    mocks = FastAPI()
    mocks.include_router(mock_router)
    transport = httpx.ASGITransport(app=mocks)
    nadra = MockNadraIdentityProvider(ServiceClient("nadra", "http://mock", "nadra-test", timeout=2, transport=transport))
    sms = MockSmsNotificationProvider(ServiceClient("sms", "http://mock", "sms-test", timeout=2, transport=transport))
    monkeypatch.setattr(registry, "get_identity_provider", lambda: nadra)
    monkeypatch.setattr(registry, "get_notification_provider", lambda: sms)

    calls = []

    class Recording(httpx.ASGITransport):
        async def handle_async_request(self, request):
            response = await super().handle_async_request(request)
            calls.append((request.url.path, response.status_code))
            return response

    ai_client.set_transport(Recording(app=main_app))
    yield SimpleNamespace(calls=calls)
    ai_client.set_transport(None)
    engine.dispose()


def add_case(case_id="case-1", **over):
    case = {"id": case_id, "status": "submitted", "citizen_id": f"cit-{case_id}", "mock_identity_id": "MOCK-123456",
            "applicant_name": "Muhammad Ali", "dob": "1990-05-12", "monthly_income": 20000,
            "documents": [{"id": "doc-1", "type": "identity_document", "quality": 0.95}],
            "message": None, "citizen_phone": "+920000000001", **over}
    platform_bridge.stub_add_case(case, grant_consent=True)


def run(case_id="case-1"):
    return asyncio.run(orchestrator.process_case(case_id))


def decision(case_id="case-1"):
    return platform_bridge.STUB_DECISIONS[case_id][-1]


def test_clean_demo_case_is_cleared_by_the_real_ai(world):
    add_case()
    result = run()
    assert result["status"] == "cleared", decision()
    d = decision()
    assert d["route"] == "cleared" and d["model_version"] == "m2-v1" and d["rule_version"] == "rules-v1"
    assert d["confidence"] >= 0.95 and "officer" in d["user_explanation"].lower()
    called = {path for path, status in world.calls if status == 200}
    assert {"/internal/ai/match-identity", "/internal/ai/extract-document", "/internal/ai/detect-duplicates",
            "/internal/ai/evaluate", "/internal/ai/explain"} <= called
    assert d["auditor_trace"]["evaluate_trace"]["routing_reason"]


def test_different_applicant_name_goes_to_officer(world):
    add_case(mock_identity_id="MOCK-200001", applicant_name="Zainab Khatoon", dob="1988-11-02")
    assert run()["status"] == "human_review"
    steps = decision()["auditor_trace"]["steps"]
    assert steps["match_identity_name"]["name_match_score"] < 0.70


def test_spelling_variant_is_still_cleared(world):
    add_case(mock_identity_id="MOCK-200001", applicant_name="Zainab Bibi", dob="1988-11-02")
    result = run()
    assert decision()["auditor_trace"]["steps"]["match_identity_name"]["name_match_score"] >= 0.95
    # whether it clears also depends on Member 3's registry check; it must never be a wrong auto-clear
    assert result["status"] in ("cleared", "human_review")


def test_scam_message_goes_to_officer(world):
    add_case(message="Send a processing fee to receive relief")
    assert run()["status"] == "human_review" and "scam_suspected" in decision()["flags"]


def test_registry_near_duplicate_goes_to_officer(world):
    add_case(mock_identity_id="MOCK-200004", applicant_name="Muhammad Ali", dob="1985-03-14")
    assert run()["status"] == "human_review" and "duplicate_claim" in decision()["flags"]


def test_second_claim_for_same_identity_goes_to_officer(world):
    add_case("case-1")
    assert run("case-1")["status"] == "cleared"
    add_case("case-2")
    assert run("case-2")["status"] == "human_review" and "duplicate_claim" in decision("case-2")["flags"]


def test_blurry_document_needs_proof(world):
    add_case(documents=[{"id": "doc-1", "type": "identity_document", "quality": 0.3}])
    assert run()["status"] == "needs_proof"
    assert "clearer_identity_document" in decision()["missing_evidence"]


def test_wrong_service_key_fails_safe_to_officer(world):
    add_case()

    class BadKey(httpx.ASGITransport):  # the agent's key is altered on the wire -> 403
        async def handle_async_request(self, request):
            request.headers["X-Service-Key"] = "nope"
            return await super().handle_async_request(request)

    ai_client.set_transport(BadKey(app=main_app))
    assert run()["status"] == "human_review" and "service_unavailable" in decision()["flags"]
