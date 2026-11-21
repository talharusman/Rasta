# OWNER: Member 3
# Table for the payment adapter. No Alembic migration is written here: Member 1
# adds PaymentRequest to the next migration (DDL printed in the task report).
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text

from shared.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentRequest(Base):
    """One row per case: the durable record of our intent to pay, written BEFORE
    Raast is called, so a crash or timeout can never lose or duplicate a payment."""

    __tablename__ = "payment_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), unique=True, nullable=False)
    idempotency_key = Column(String(128), unique=True, nullable=False)  # "disburse-" + case_id
    amount = Column(Numeric(12, 2), nullable=False)
    account_id = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="requested")  # requested|success|pending|failed|unknown
    transaction_id = Column(String(64), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)  # POST /disburse calls made
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


PROVIDER_MODELS = [PaymentRequest]
