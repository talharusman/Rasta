# OWNER: Member 3
# Tables for the job queue. No Alembic migration is written here: Member 1 adds
# Job and WorkerHeartbeat to the next migration (DDL in the task report).
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text

from shared.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(36), primary_key=True, default=_new_id)
    kind = Column(String(64), nullable=False)  # process_case | send_notification | check_delivery | disburse_case | reconcile_payment
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="queued")  # queued | running | done | failed
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=4)
    run_after = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_error = Column(Text, nullable=True)
    # UNIQUE (NULLs allowed, many): e.g. "disburse-<case_id>" can only ever exist once.
    dedupe_key = Column(String(128), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_jobs_due", "status", "run_after"),
        Index("ix_jobs_kind", "kind"),
    )


class WorkerHeartbeat(Base):
    """Single row (id = 1): the worker loop touches last_seen on every pass."""

    __tablename__ = "worker_heartbeat"
    id = Column(Integer, primary_key=True)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=_now)


JOB_MODELS = [Job, WorkerHeartbeat]
