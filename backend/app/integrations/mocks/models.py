# OWNER: Member 3
# SQLAlchemy tables for the mock external services. Uses the project's Base.
# NOTE: no Alembic migration is written here; Member 1 includes MOCK_MODELS in
# the next migration (see MOCK_MODELS below).
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, Numeric, String, Text

from shared.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockIdentityRecord(Base):
    __tablename__ = "mock_identity_records"
    cit_id = Column(String(32), primary_key=True)  # e.g. MOCK-123456
    full_nm = Column(String(120), nullable=False)
    father_nm = Column(String(120), nullable=True)
    birth_dt = Column(String(10), nullable=True)  # ISO date, may be missing
    gndr = Column(String(1), nullable=True)
    dist = Column(String(60), nullable=True)
    rec_status = Column(String(16), nullable=False, default="ACTIVE")  # ACTIVE|BLOCKED


class MockAccount(Base):
    __tablename__ = "mock_accounts"
    acct = Column(String(32), primary_key=True)  # e.g. MOCK-ACCOUNT-001
    holder_nm = Column(String(120), nullable=False)
    cit_id = Column(String(32), nullable=True)


class MockTransaction(Base):
    __tablename__ = "mock_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    txn_ref = Column(String(40), unique=True, nullable=False)
    # UNIQUE: the database, not application code, stops duplicate payments.
    idempotency_key = Column(String(128), unique=True, nullable=False)
    case_id = Column(String(64), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    account_id = Column(String(32), nullable=False)
    approval_ref = Column(String(128), nullable=False)
    status = Column(String(8), nullable=False)  # ACSC | PDNG | RJCT
    rsn_cd = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class MockSmsMessage(Base):
    __tablename__ = "mock_sms_messages"
    msg_id = Column(String(40), primary_key=True)
    to_number = Column(String(32), nullable=False)
    text = Column(Text, nullable=False)
    ref = Column(String(64), nullable=True)
    dlr = Column(String(8), nullable=False)  # final: DELIVRD | UNDELIV (fixed at send)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class MockFixtureState(Base):
    """Single row (id=1) holding the fixture switches as JSON."""

    __tablename__ = "mock_fixture_state"
    id = Column(Integer, primary_key=True)
    state = Column(JSON, nullable=False, default=dict)


MOCK_MODELS = [
    MockIdentityRecord,
    MockAccount,
    MockTransaction,
    MockSmsMessage,
    MockFixtureState,
]
