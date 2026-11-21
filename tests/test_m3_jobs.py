# OWNER: Member 3. Tests for the job queue, worker and handlers (real mock services in-process).
# Run from the repo root:  python -m pytest tests/test_m3_jobs.py -v
import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent import ai_client, platform_bridge  # noqa: E402
from app.agent.models import AGENT_MODELS  # noqa: E402
from app.integrations.mocks import control  # noqa: E402
from app.integrations.mocks.fixtures import seed_mocks  # noqa: E402
from app.integrations.mocks.models import MOCK_MODELS, MockSmsMessage, MockTransaction  # noqa: E402
from app.integrations.mocks.router import router as mock_router  # noqa: E402
from app.integrations.providers import http as provider_http  # noqa: E402
from app.integrations.providers import registry  # noqa: E402
from app.integrations.providers.base import NotificationResult, NotificationStatus  # noqa: E402
from app.integrations.providers.http import ServiceClient  # noqa: E402
from app.integrations.providers.identity import MockNadraIdentityProvider  # noqa: E402
from app.integrations.providers.models import PROVIDER_MODELS, PaymentRequest  # noqa: E402
from app.integrations.providers.notification import MockSmsNotificationProvider  # noqa: E402
from app.integrations.providers.payment import MockRaastPaymentProvider  # noqa: E402
from app.jobs import handlers, queue, worker  # noqa: E402
from app.jobs.models import JOB_MODELS, Job, WorkerHeartbeat  # noqa: E402
from app.jobs.router import router as jobs_router  # noqa: E402
from shared import db as shared_db  # noqa: E402

pytestmark = [pytest.mark.asyncio, pytest.mark.filterwarnings("ignore:Dialect sqlite")]

ACCT = "MOCK-ACCOUNT-001"
PHONE = "+920000000001"
KEY = {"X-Service-Key": "internal-test"}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    for var, val in [("NADRA_MOCK_KEY", "nadra-test"), ("SMS_MOCK_KEY", "sms-test"),
                     ("RAAST_MOCK_KEY", "raast-test"), ("INTERNAL_SERVICE_KEY", "internal-test"),
                     ("AI_STUB", "true")]:
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("RUN_JOB_WORKER", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'j.db'}", connect_args={"check_same_thread": False})
    shared_db.Base.metadata.create_all(
        engine, tables=[m.__table__ for m in MOCK_MODELS + PROVIDER_MODELS + AGENT_MODELS + JOB_MODELS])
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(shared_db, "SessionLocal", factory)
    seed_mocks(reset=True)
    platform_bridge.stub_reset()
    monkeypatch.setattr(provider_http, "RETRY_BACKOFF", (0.01, 0.01, 0.01))
    monkeypatch.setattr(ai_client, "RETRY_DELAY", 0.01)
    monkeypatch.setattr(handlers, "CHECK_DELIVERY_DELAY", 0.0)
    monkeypatch.setattr(handlers, "RECONCILE_DELAY", 0.0)

    app = FastAPI()
    app.include_router(mock_router)
    transport = httpx.ASGITransport(app=app)

    def client(service, key):
        return ServiceClient(service, "http://mock", key, timeout=0.5, transport=transport)

    raast = MockRaastPaymentProvider(client("raast", "raast-test"))
    sms = MockSmsNotificationProvider(client("sms", "sms-test"))
    nadra = MockNadraIdentityProvider(client("nadra", "nadra-test"))
    monkeypatch.setattr(registry, "get_payment_provider", lambda: raast)
    monkeypatch.setattr(registry, "get_notification_provider", lambda: sms)
    monkeypatch.setattr(registry, "get_identity_provider", lambda: nadra)

    def count(model):
        with factory() as s:
            return s.scalar(select(func.count()).select_from(model))

    yield SimpleNamespace(count=count, factory=factory, raast=raast, sms=sms)
    engine.dispose()


def add_case(case_id="case-1", **over):
    return platform_bridge.stub_add_case({
        "id": case_id, "status": "approved", "citizen_id": "cit-1", "account_id": ACCT, "amount": 5000,
        "citizen_phone": PHONE, "mock_identity_id": "MOCK-123456", "applicant_name": "Muhammad Ali",
        "dob": "1990-05-12", "monthly_income": 20000, "submission_count": 1,
        "documents": [{"id": "d1", "type": "identity_document", "quality": 0.95}], **over})


def make_due(world):
    """Pretend the retry backoff has elapsed."""
    with world.factory() as s:
        s.execute(update(Job).where(Job.status == "queued").values(run_after=datetime.now(timezone.utc)))
        s.commit()


async def drain(world, rounds=30):
    claimed = 0
    for _ in range(rounds):
        make_due(world)
        n = await worker.run_once()
        if n == 0:
            return claimed
        claimed += n
    raise AssertionError("jobs never settled")


def jobs_of(kind=None):
    return queue.list_jobs(kind=kind)


def audits(action):
    return [e for e in platform_bridge.STUB_AUDIT_LOG if e["action"] == action]


def open_breaker_cooldown(client):
    real = time.monotonic
    client.breaker.clock = lambda: real() + 31


def naive(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=None)


# --- queue -------------------------------------------------------------------------------
async def test_enqueue_and_dedupe(world):
    a = queue.enqueue("x", {"n": 1}, dedupe_key="k1")
    b = queue.enqueue("x", {"n": 2}, dedupe_key="k1")
    c = queue.enqueue("x", {"n": 3})
    d = queue.enqueue("x", {"n": 4})  # no key: always a new job
    assert a["id"] == b["id"] and b["deduplicated"] and not a["deduplicated"]
    assert b["payload"] == {"n": 1}  # the original job, untouched
    assert c["id"] != d["id"] and world.count(Job) == 3
    with pytest.raises(ValueError):
        queue.enqueue("")
    with pytest.raises(ValueError):
        queue.enqueue("x", max_attempts=0)


async def test_delay_and_claim_once(world):
    queue.enqueue("noop", delay_seconds=3600)
    due = queue.enqueue("noop")
    assert [j["id"] for j in worker.claim(5)] == [due["id"]]  # the delayed job is not due
    assert worker.claim(5) == []  # and a claimed job cannot be claimed twice


# --- retries / failure -------------------------------------------------------------------
async def test_failing_handler_retries_then_fails_and_is_audited(world, monkeypatch):
    calls = []

    async def boom(payload, job):
        calls.append(job["attempts"])
        raise RuntimeError("kaboom")

    monkeypatch.setitem(handlers.HANDLERS, "boom", boom)
    job = queue.enqueue("boom", {"case_id": "case-1"}, max_attempts=3)

    await worker.run_once()  # first failure: retry with backoff, not failed yet
    first = queue.get_job(job["id"])
    assert first["status"] == "queued" and first["attempts"] == 1 and "kaboom" in first["last_error"]
    wait = (naive(first["run_after"]) - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
    assert 8 < wait < 12  # 5 * 2**1
    assert audits("job_failed") == []

    await drain(world)
    final = queue.get_job(job["id"])
    assert final["status"] == "failed" and final["attempts"] == 3 and len(calls) == 3
    failed = audits("job_failed")
    assert len(failed) == 1
    entry = failed[0]
    assert (entry["actor_type"], entry["actor_id"], entry["resource"]) == ("system", "job_worker", f"job:{job['id']}")
    assert "kaboom" in entry["metadata"]["last_error"] and entry["metadata"]["case_id"] == "case-1"
    assert entry["metadata"]["attempts"] == 3


async def test_retry_delay_formula():
    assert [worker.retry_delay(n) for n in (1, 2, 3, 4, 5, 6, 20)] == [10, 20, 40, 80, 160, 300, 300]


async def test_unknown_kind_fails_at_once(world):
    job = queue.enqueue("no_such_kind")
    await worker.run_once()
    got = queue.get_job(job["id"])
    assert got["status"] == "failed" and "unknown job kind" in got["last_error"] and got["attempts"] == 1
    assert len(audits("job_failed")) == 1


async def test_stuck_running_jobs_are_reset(world):
    stuck, doomed = queue.enqueue("noop"), queue.enqueue("noop", max_attempts=1)
    old = datetime.now(timezone.utc) - timedelta(minutes=6)
    with world.factory() as s:
        s.execute(update(Job).where(Job.id.in_([stuck["id"], doomed["id"]])).values(status="running", updated_at=old))
        s.commit()
    assert worker.reset_stuck() == 2
    assert queue.get_job(stuck["id"])["status"] == "queued" and queue.get_job(stuck["id"])["attempts"] == 1
    assert queue.get_job(doomed["id"])["status"] == "failed"  # out of attempts: recorded, not looped forever
    assert len(audits("job_failed")) == 1


# --- disbursement ------------------------------------------------------------------------
async def test_dedupe_key_prevents_second_disburse_job(world):
    add_case()
    first, second = queue.enqueue_disbursement("case-1"), queue.enqueue_disbursement("case-1")
    assert first["id"] == second["id"] and second["deduplicated"]
    assert first["dedupe_key"] == "disburse-case-1" and len(jobs_of("disburse_case")) == 1
    await drain(world)
    assert queue.get_job(first["id"])["status"] == "done"
    assert world.count(MockTransaction) == 1
    third = queue.enqueue_disbursement("case-1")  # even after it finished
    assert third["id"] == first["id"] and third["deduplicated"]
    await drain(world)
    assert world.count(MockTransaction) == 1 and len(jobs_of("disburse_case")) == 1
    assert audits("payment_sent")[0]["metadata"]["idempotency_key"] == "disburse-case-1"


async def test_disburse_on_non_approved_case_fails_without_retry(world):
    add_case(status="cleared")  # automated checks passed, but no officer approval
    job = queue.enqueue_disbursement("case-1")
    await worker.run_once()
    got = queue.get_job(job["id"])
    assert got["status"] == "failed" and got["attempts"] == 1 and "not approved" in got["last_error"]
    assert await drain(world) == 0  # nothing is retried
    assert queue.get_job(job["id"])["attempts"] == 1
    assert world.count(MockTransaction) == 0 and world.count(PaymentRequest) == 0
    assert len(audits("disburse_blocked_not_approved")) == 1  # by the payment adapter
    assert len(audits("disburse_job_rejected_not_approved")) == 1
    assert len(audits("job_failed")) == 1


async def test_raast_outage_schedules_reconcile_then_exactly_one_payment(world):
    add_case()
    control.set_conditions({"raast_outage": True})
    job = queue.enqueue_disbursement("case-1")

    await worker.run_once()  # only the disburse job
    assert queue.get_job(job["id"])["status"] == "done"  # finished: reconcile takes over
    reconcile = jobs_of("reconcile_payment")
    assert len(reconcile) == 1 and reconcile[0]["status"] == "queued"
    assert reconcile[0]["dedupe_key"] == "reconcile-case-1"
    assert world.count(MockTransaction) == 0
    assert world.count(PaymentRequest) == 0  # the account could not be checked, so nothing was attempted

    control.set_conditions({"raast_outage": False})  # recovery
    open_breaker_cooldown(world.raast.http)
    await drain(world)
    assert world.count(MockTransaction) == 1  # exactly one payment
    assert queue.get_job(reconcile[0]["id"])["status"] == "done"
    assert audits("payment_sent") and not audits("job_failed")
    await drain(world)
    assert world.count(MockTransaction) == 1 and len(jobs_of("disburse_case")) == 1
    assert any(n["message"] == handlers.PAYMENT_SENT_MESSAGE and n["state"] == "delivered"
               for n in platform_bridge.STUB_NOTIFICATIONS)


async def test_outage_during_the_payment_call_itself_leaves_an_unknown_row_then_reconciles(world):
    """The account check passes, then Raast goes down exactly when we send the payment."""
    add_case()
    real_disburse = world.raast.http.request

    async def outage_on_disburse(method, path, **kw):
        if path == "/mock/raast/disburse":
            control.set_conditions({"raast_outage": True})
        return await real_disburse(method, path, **kw)

    world.raast.http.request = outage_on_disburse
    job = queue.enqueue_disbursement("case-1")
    await worker.run_once()
    assert queue.get_job(job["id"])["status"] == "done"
    assert jobs_of("reconcile_payment")[0]["status"] == "queued" and world.count(MockTransaction) == 0
    with world.factory() as s:
        assert s.execute(select(PaymentRequest)).scalar_one().status == "unknown"

    control.set_conditions({"raast_outage": False})
    world.raast.http.request = real_disburse
    open_breaker_cooldown(world.raast.http)
    await drain(world)
    assert world.count(MockTransaction) == 1


@pytest.mark.parametrize("account,name,expected", [
    ("MOCK-ACCOUNT-006", "Ayesha Siddiqui", "nomatch"),  # held by "A. Siddiqi Traders"
    ("MOCK-ACCOUNT-404", "Muhammad Ali", "not_found"),
])
async def test_payment_account_mismatch_blocks_payment_and_goes_to_officer(world, account, name, expected):
    add_case(account_id=account, applicant_name=name)
    job = queue.enqueue_disbursement("case-1")
    await worker.run_once()
    got = queue.get_job(job["id"])
    assert got["status"] == "failed" and got["attempts"] == 1  # no retry
    assert "does not match" in got["last_error"]
    assert world.count(MockTransaction) == 0 and world.count(PaymentRequest) == 0
    blocked = audits("disburse_blocked_account_mismatch")
    assert len(blocked) == 1 and blocked[0]["metadata"]["account_id"] == account
    assert len(audits("job_failed")) == 1
    assert platform_bridge.get_case("case-1")["status"] == "human_review"  # back to an officer
    assert "Payment blocked" in platform_bridge.get_case("case-1")["last_note"]
    assert await drain(world) == 0


async def test_payment_without_beneficiary_name_fails_closed(world):
    add_case(applicant_name=None)
    job = queue.enqueue_disbursement("case-1")
    await worker.run_once()
    assert queue.get_job(job["id"])["status"] == "failed" and world.count(MockTransaction) == 0


async def test_reconcile_retries_while_outage_continues(world):
    add_case()
    control.set_conditions({"raast_outage": True})
    queue.enqueue_disbursement("case-1")
    await worker.run_once()
    await worker.run_once()  # the reconcile job fails too: it raises and retries, it does not give up
    rec = jobs_of("reconcile_payment")[0]
    assert rec["status"] == "queued" and rec["attempts"] == 1 and world.count(MockTransaction) == 0


async def test_reconcile_adopts_a_payment_that_actually_went_through(world):
    """Disburse reached Raast but we lost the answer: reconcile finds it, never pays again."""
    add_case()
    await world.raast.http.request(
        "POST", "/mock/raast/disburse",
        json_body={"case_id": "case-1", "amt": "5000.00", "acct": ACCT, "approval_ref": "case-1"},
        headers={"Idempotency-Key": "disburse-case-1"})
    with world.factory() as s:
        from decimal import Decimal
        s.add(PaymentRequest(case_id="case-1", idempotency_key="disburse-case-1", amount=Decimal("5000.00"),
                             account_id=ACCT, status="unknown", attempts=1))
        s.commit()
    queue.enqueue("reconcile_payment", {"case_id": "case-1"})
    await drain(world)
    assert world.count(MockTransaction) == 1 and audits("payment_sent")


# --- notifications -----------------------------------------------------------------------
async def test_notification_is_sent_and_confirmed_delivered(world):
    queue.enqueue_notification("case-1", PHONE, "hello")
    await drain(world)
    note = platform_bridge.STUB_NOTIFICATIONS[0]
    assert note["state"] == "delivered" and note["message_id"]
    assert world.count(MockSmsMessage) == 1
    assert [j["status"] for j in jobs_of()] == ["done", "done"]  # send + check_delivery


async def test_sms_failure_resends_once_then_records_failed(world):
    control.set_conditions({"sms_failure": True})
    queue.enqueue_notification("case-1", PHONE, "hello")
    await drain(world)
    assert world.count(MockSmsMessage) == 2  # the original + exactly one re-send
    assert platform_bridge.STUB_NOTIFICATIONS[0]["state"] == "failed"
    assert len(audits("notification_failed")) == 1
    checks = jobs_of("check_delivery")
    assert len(checks) == 2 and all(j["status"] == "done" for j in checks)
    assert not audits("job_failed")  # the notification failed, the jobs themselves worked


async def test_provider_unavailable_retries_without_duplicate_in_app_notification(world, monkeypatch):
    real_send, state = world.sms.send, {"calls": 0}

    async def flaky(recipient, message, case_id):
        state["calls"] += 1
        if state["calls"] == 1:
            return NotificationResult(status=NotificationStatus.unavailable, error="gateway down")
        return await real_send(recipient, message, case_id)

    monkeypatch.setattr(world.sms, "send", flaky)
    job = queue.enqueue_notification("case-1", PHONE, "hello")
    await worker.run_once()
    got = queue.get_job(job["id"])
    assert got["status"] == "queued" and got["attempts"] == 1 and "gateway down" in got["last_error"]
    await drain(world)
    assert queue.get_job(job["id"])["status"] == "done"
    assert len(platform_bridge.STUB_NOTIFICATIONS) == 1  # the retry reused the first notification
    assert platform_bridge.STUB_NOTIFICATIONS[0]["state"] == "delivered"


# --- process_case ------------------------------------------------------------------------
async def test_start_case_processing_enqueues_one_job_and_agent_runs(world):
    add_case(status="submitted")
    a, b = queue.start_case_processing("case-1"), queue.start_case_processing("case-1")
    assert a["id"] == b["id"] and a["dedupe_key"] == "process-case-1-1"
    await drain(world)
    assert platform_bridge.get_case("case-1")["status"] == "cleared"
    assert queue.get_job(a["id"])["status"] == "done"
    assert world.count(MockTransaction) == 0  # processing never moves money


# --- routes ------------------------------------------------------------------------------
def _app():
    app = FastAPI()
    app.include_router(jobs_router)
    return app


async def test_job_routes(world):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://m3") as c:
        body = {"case_id": "case-1", "recipient": PHONE, "message": "secret text"}
        assert (await c.post("/internal/jobs/notifications", json=body)).status_code == 403
        assert (await c.post("/internal/jobs/notifications", json={"case_id": "x"}, headers=KEY)).status_code == 422
        ok = await c.post("/internal/jobs/notifications", json=body, headers=KEY)
        assert ok.status_code == 202 and ok.json()["status"] == "queued"
        assert (await c.get("/internal/jobs")).status_code == 403
        listing = await c.get("/internal/jobs", params={"kind": "send_notification"}, headers=KEY)
        job = listing.json()["jobs"][0]
        assert job["id"] == ok.json()["job_id"]
        assert job["payload"]["recipient"] == "***0001" and "secret" not in str(job["payload"])
        assert (await c.get("/internal/jobs", params={"status": "bogus"}, headers=KEY)).status_code == 422
        assert (await c.get("/internal/jobs", params={"status": "done"}, headers=KEY)).json()["jobs"] == []
        assert (await c.get("/api/v1/admin/jobs")).status_code == 403
        admin = await c.get("/api/v1/admin/jobs", headers=KEY)
        assert admin.status_code == 200 and len(admin.json()["jobs"]) == 1
        assert (await c.get("/health")).json() == {"status": "ok"}


async def test_ready_checks_worker_heartbeat(world, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://m3") as c:
        ready = await c.get("/ready")  # worker not enabled: only the database matters
        assert ready.status_code == 200 and ready.json()["checks"]["worker"] == "disabled"

        monkeypatch.setenv("RUN_JOB_WORKER", "true")
        none_yet = await c.get("/ready")
        assert none_yet.status_code == 503 and none_yet.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

        await asyncio.to_thread(worker.heartbeat)
        assert (await c.get("/ready")).status_code == 200

        with world.factory() as s:
            s.get(WorkerHeartbeat, 1).last_seen = datetime.now(timezone.utc) - timedelta(seconds=45)
            s.commit()
        stale = await c.get("/ready")
        assert stale.status_code == 503 and "stale" in stale.json()["checks"]["worker"]


async def test_worker_starts_from_router_hook_only_when_enabled(world, monkeypatch):
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.05)

    def run(enabled: bool):
        monkeypatch.setenv("RUN_JOB_WORKER", "true" if enabled else "false")
        queue.enqueue("noop_marker")
        with TestClient(_app()):
            time.sleep(0.6)
            return worker.heartbeat_age_seconds()

    assert await asyncio.to_thread(run, False) is None  # disabled: no worker, no heartbeat
    age = await asyncio.to_thread(run, True)
    assert age is not None and age < 5  # enabled: the router hook started the loop
    assert worker._task is None  # and the shutdown hook stopped it
    assert all(j["status"] == "failed" for j in jobs_of("noop_marker"))  # it really processed jobs
