# OWNER: Member 3. Tests for the provider adapters (identity / payment / notification).
# The adapters talk to the REAL mock app in-process through httpx.ASGITransport.
# Run from the repo root:  python -m pytest tests/test_m3_adapters.py -v
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent import platform_bridge  # noqa: E402
from app.integrations.mocks import control  # noqa: E402
from app.integrations.mocks.fixtures import seed_mocks  # noqa: E402
from app.integrations.mocks.models import MOCK_MODELS, MockTransaction  # noqa: E402
from app.integrations.mocks.router import router as mock_router  # noqa: E402
from app.integrations.providers import http as provider_http  # noqa: E402
from app.integrations.providers import registry  # noqa: E402
from app.integrations.providers.base import (  # noqa: E402
    AccountStatus,
    IdentityProvider,
    IdentityStatus,
    NotificationProvider,
    NotificationStatus,
    PaymentProvider,
    PaymentStatus,
)
from app.integrations.providers.http import ServiceClient  # noqa: E402
from app.integrations.providers.identity import MockNadraIdentityProvider  # noqa: E402
from app.integrations.providers.models import PROVIDER_MODELS, PaymentRequest  # noqa: E402
from app.integrations.providers.notification import MockSmsNotificationProvider  # noqa: E402
from app.integrations.providers.payment import MockRaastPaymentProvider  # noqa: E402
from shared import db as shared_db  # noqa: E402

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.filterwarnings("ignore:Dialect sqlite"),
]

ACCT = "MOCK-ACCOUNT-001"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    for var, val in [("NADRA_MOCK_KEY", "nadra-test"), ("RAAST_MOCK_KEY", "raast-test"),
                     ("SMS_MOCK_KEY", "sms-test"), ("INTERNAL_SERVICE_KEY", "internal-test"),
                     ("MOCK_BASE_URL", "http://mock")]:
        monkeypatch.setenv(var, val)
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", connect_args={"check_same_thread": False})
    shared_db.Base.metadata.create_all(
        engine, tables=[m.__table__ for m in MOCK_MODELS + PROVIDER_MODELS])
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(shared_db, "SessionLocal", factory)
    seed_mocks(reset=True)
    platform_bridge.STUB_AUDIT_LOG.clear()

    # Fake Member 1's get_case through the bridge stub.
    cases = {}
    monkeypatch.setattr(platform_bridge, "get_case", lambda cid: cases[cid])
    monkeypatch.setattr(provider_http, "RETRY_BACKOFF", (0.01, 0.01, 0.01))  # fast retries

    app = FastAPI()
    app.include_router(mock_router)
    transport = httpx.ASGITransport(app=app)

    def client(service):
        key = {"nadra": "nadra-test", "raast": "raast-test", "sms": "sms-test"}[service]
        return ServiceClient(service, "http://mock", key, transport=transport)

    def count(model):
        with factory() as s:
            return s.scalar(select(func.count()).select_from(model))

    def row():
        with factory() as s:
            return s.execute(select(PaymentRequest)).scalar_one()

    yield SimpleNamespace(
        identity=MockNadraIdentityProvider(client("nadra")),
        payment=MockRaastPaymentProvider(client("raast")),
        sms=MockSmsNotificationProvider(client("sms")),
        cases=cases, count=count, row=row, client=client,
    )
    engine.dispose()


def approve(world, case_id="case-1", status="approved"):
    world.cases[case_id] = {"id": case_id, "status": status}


def open_breaker_cooldown(client: ServiceClient):
    """Pretend 31 seconds have passed so an open breaker allows a trial."""
    real = time.monotonic
    client.breaker.clock = lambda: real() + 31


# --- identity ----------------------------------------------------------------------------
async def test_clean_identity_is_verified(world):
    r = await world.identity.verify("MOCK-123456", "Muhammad Ali")
    assert r.status == IdentityStatus.verified
    assert r.record.name == "Muhammad Ali" and r.record.rec_status == "ACTIVE"
    assert r.issues == []


async def test_dob_checks(world):
    ok = await world.identity.verify("MOCK-123456", "Muhammad Ali", "1990-05-12")
    bad = await world.identity.verify("MOCK-123456", "Muhammad Ali", "1991-01-01")
    missing = await world.identity.verify("MOCK-200002", "Rashid Khan", "1990-01-01")
    assert ok.status == IdentityStatus.verified
    assert bad.status == IdentityStatus.mismatch and "dob_mismatch" in bad.issues
    assert missing.status == IdentityStatus.verified and "dob_missing_in_registry" in missing.issues


async def test_blocked_record_is_mismatch(world):
    r = await world.identity.verify("MOCK-200005", "Fatima Noor")
    assert r.status == IdentityStatus.mismatch and "record_blocked" in r.issues


async def test_unknown_identity_not_found(world):
    assert (await world.identity.verify("MOCK-999999", "Nobody")).status == IdentityStatus.not_found


async def test_get_record(world):
    r = await world.identity.get_record("MOCK-200001")
    assert r.status == IdentityStatus.verified and "Zenab" in r.record.name


async def test_duplicated_response_is_duplicate(world):
    control.set_conditions({"duplicated_response": True})
    r = await world.identity.verify("MOCK-200003", "Mohammad Ali")
    assert r.status == IdentityStatus.duplicate


async def test_identity_mismatch_switch_still_verified_but_name_differs(world):
    # Name comparison is Member 2's job; the adapter just hands over record.name.
    control.set_conditions({"identity_mismatch": True})
    r = await world.identity.verify("MOCK-123456", "Muhammad Ali")
    assert r.status == IdentityStatus.verified and r.record.name != "Muhammad Ali"


async def test_timeout_is_unavailable_never_verified(world, monkeypatch):
    monkeypatch.setattr(provider_http, "RETRY_BACKOFF", (0.5, 1.0, 2.0))  # real backoff
    start = time.monotonic()
    r = await world.identity.verify("MOCK-TIMEOUT-01", "Timeout Test")
    elapsed = time.monotonic() - start
    assert r.status == IdentityStatus.unavailable and r.status != IdentityStatus.verified
    assert "timed out" in r.error
    assert elapsed < 16, f"took {elapsed:.1f}s"  # 3 x 4s + 0.5s + 1s backoff = ~13.5s


async def test_malformed_json_is_malformed(world):
    r = await world.identity.verify("MOCK-MALFORMED-01", "Malformed Test")
    assert r.status == IdentityStatus.malformed and r.record is None


async def test_nadra_outage_is_unavailable_and_opens_circuit(world):
    control.set_conditions({"nadra_outage": True})
    first = await world.identity.verify("MOCK-123456", "Muhammad Ali")
    assert first.status == IdentityStatus.unavailable
    assert world.identity.http.breaker.is_open  # 3 failed attempts in that one call

    # Service recovers, but the open circuit still answers instantly without calling it.
    control.set_conditions({"nadra_outage": False})
    start = time.monotonic()
    second = await world.identity.verify("MOCK-123456", "Muhammad Ali")
    assert second.status == IdentityStatus.unavailable and "circuit open" in second.error
    assert time.monotonic() - start < 0.5

    open_breaker_cooldown(world.identity.http)  # after 30s a trial call is allowed
    assert (await world.identity.verify("MOCK-123456", "Muhammad Ali")).status == IdentityStatus.verified
    assert not world.identity.http.breaker.is_open


async def test_4xx_is_not_retried(world):
    bad = MockNadraIdentityProvider(ServiceClient("nadra", "http://mock", "WRONG", transport=world.identity.http._transport))
    r = await bad.verify("MOCK-123456", "Muhammad Ali")
    assert r.status == IdentityStatus.unavailable and "401" in r.error
    assert not bad.http.breaker.is_open and bad.http.breaker.failures == 0


async def test_connection_refused_never_raises(world):
    dead = MockNadraIdentityProvider(ServiceClient("nadra", "http://127.0.0.1:1", "k"))
    r = await dead.verify("MOCK-123456", "Muhammad Ali")
    assert r.status == IdentityStatus.unavailable and r.error
    await dead.http.aclose()


# --- payment: validate / get ------------------------------------------------------------
async def test_validate_account(world):
    assert (await world.payment.validate_account(ACCT, "Muhammad Ali")).status == AccountStatus.matched
    assert (await world.payment.validate_account("MOCK-ACCOUNT-006", "Ayesha Siddiqui")).status == AccountStatus.mismatched
    assert (await world.payment.validate_account("MOCK-ACCOUNT-404", "x")).status == AccountStatus.not_found


# --- payment: disburse ------------------------------------------------------------------
async def test_disburse_blocked_when_not_approved(world):
    for status in ("cleared", "submitted", "human_review"):
        approve(world, "case-1", status)
        r = await world.payment.disburse("case-1", 5000, ACCT)
        assert r.status == PaymentStatus.rejected_not_approved
    assert world.count(MockTransaction) == 0  # Raast was never called
    assert world.count(PaymentRequest) == 0
    assert [e["action"] for e in platform_bridge.STUB_AUDIT_LOG] == ["disburse_blocked_not_approved"] * 3
    entry = platform_bridge.STUB_AUDIT_LOG[0]
    assert entry["actor_type"] == "system" and entry["actor_id"] == "payment_adapter"


async def test_disburse_twice_gives_one_transaction(world):
    approve(world)
    first = await world.payment.disburse("case-1", 5000, ACCT)
    second = await world.payment.disburse("case-1", 5000, ACCT)
    assert first.status == second.status == PaymentStatus.success
    assert first.transaction_id and first.transaction_id == second.transaction_id
    assert first.idempotency_key == "disburse-case-1"
    assert world.count(MockTransaction) == 1
    row = world.row()
    assert row.status == "success" and row.attempts == 1  # the second call never reached Raast
    assert row.transaction_id == first.transaction_id


async def test_disburse_different_amount_after_payment_is_refused(world):
    approve(world)
    await world.payment.disburse("case-1", 5000, ACCT)
    r = await world.payment.disburse("case-1", 9999, ACCT)
    assert r.status == PaymentStatus.failed
    assert world.count(MockTransaction) == 1


async def test_disburse_during_raast_outage_then_recovery(world):
    approve(world)
    control.set_conditions({"raast_outage": True})
    during = await world.payment.disburse("case-1", 5000, ACCT)
    assert during.status == PaymentStatus.unavailable and during.reconcile_required
    assert world.count(MockTransaction) == 0
    assert world.row().status == "unknown" and world.row().attempts == 1

    control.set_conditions({"raast_outage": False})
    open_breaker_cooldown(world.payment.http)  # the outage opened the circuit

    recon = await world.payment.reconcile_unknown("case-1")  # lookup only: nothing was paid
    assert recon.status == PaymentStatus.failed and "no transaction" in recon.error
    assert world.count(MockTransaction) == 0

    paid = await world.payment.disburse("case-1", 5000, ACCT)
    again = await world.payment.disburse("case-1", 5000, ACCT)
    assert paid.status == again.status == PaymentStatus.success
    assert paid.transaction_id == again.transaction_id
    assert world.count(MockTransaction) == 1


async def test_reconcile_finds_payment_that_succeeded_but_response_was_lost(world):
    """The payment reached Raast but we never recorded it (e.g. timeout): reconcile adopts it."""
    approve(world)
    # Make Raast process a payment behind the adapter's back, with the adapter's key.
    raw = await world.client("raast").request(
        "POST", "/mock/raast/disburse",
        json_body={"case_id": "case-1", "amt": "5000.00", "acct": ACCT, "approval_ref": "case-1"},
        headers={"Idempotency-Key": "disburse-case-1"})
    txn_ref = raw.json()["txnRef"]
    # Our side only has an 'unknown' row (what a timeout leaves behind).
    with shared_db.SessionLocal() as s:
        from decimal import Decimal
        s.add(PaymentRequest(case_id="case-1", idempotency_key="disburse-case-1", amount=Decimal("5000.00"),
                             account_id=ACCT, status="unknown", attempts=1))
        s.commit()
    r = await world.payment.reconcile_unknown("case-1")
    assert r.status == PaymentStatus.success and r.transaction_id == txn_ref
    assert world.row().status == "success"
    # A later disburse call must not create a second transaction.
    assert (await world.payment.disburse("case-1", 5000, ACCT)).transaction_id == txn_ref
    assert world.count(MockTransaction) == 1


async def test_disburse_never_raises(world):
    # get_case raising (case not found / M1 stub not wired) -> status, no payment.
    r = await world.payment.disburse("no-such-case", 5000, ACCT)
    assert r.status == PaymentStatus.unavailable and "payment not attempted" in r.error
    assert world.count(MockTransaction) == 0
    approve(world)
    assert (await world.payment.disburse("case-1", "abc", ACCT)).status == PaymentStatus.failed
    assert (await world.payment.disburse("case-1", -5, ACCT)).status == PaymentStatus.failed
    assert world.count(PaymentRequest) == 0


async def test_get_transaction(world):
    approve(world)
    paid = await world.payment.disburse("case-1", 5000, ACCT)
    got = await world.payment.get_transaction(paid.transaction_id)
    assert got.status == PaymentStatus.success and got.transaction_id == paid.transaction_id
    assert (await world.payment.get_transaction("RAAST-NOPE")).status == PaymentStatus.failed


# --- notification -----------------------------------------------------------------------
async def test_sms_send_and_status(world):
    sent = await world.sms.send("+920000000000", "Your case moved", "case-1")
    assert sent.status == NotificationStatus.sent and sent.message_id
    assert (await world.sms.status(sent.message_id)).status == NotificationStatus.delivered


async def test_sms_failure_maps_to_failed(world):
    control.set_conditions({"sms_failure": True})
    sent = await world.sms.send("+920000000000", "hi", "case-1")
    assert sent.status == NotificationStatus.sent
    assert (await world.sms.status(sent.message_id)).status == NotificationStatus.failed


async def test_sms_gateway_down_is_unavailable(world):
    dead = MockSmsNotificationProvider(ServiceClient("sms", "http://127.0.0.1:1", "k"))
    r = await dead.send("+920000000000", "hi", "case-1")
    assert r.status == NotificationStatus.unavailable
    await dead.http.aclose()


# --- registry ---------------------------------------------------------------------------
async def test_registry_returns_singletons(world):
    registry.reset_providers()
    try:
        assert registry.get_identity_provider() is registry.get_identity_provider()
        assert registry.get_payment_provider() is registry.get_payment_provider()
        assert registry.get_notification_provider() is registry.get_notification_provider()
        assert isinstance(registry.get_identity_provider(), IdentityProvider)
        assert isinstance(registry.get_payment_provider(), PaymentProvider)
        assert isinstance(registry.get_notification_provider(), NotificationProvider)
    finally:
        registry.reset_providers()


async def test_timeouts_and_retry_limits_per_spec():
    assert provider_http.SERVICE_TIMEOUTS == {"nadra": 4.0, "raast": 6.0, "sms": 4.0}
    assert provider_http.MAX_ATTEMPTS == 3
    assert provider_http.BREAKER_THRESHOLD == 3 and provider_http.BREAKER_OPEN_SECONDS == 30.0
