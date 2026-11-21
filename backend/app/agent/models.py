# OWNER: Member 3
# Table for agent runs. No Alembic migration is written here: Member 1 adds AgentRun
# (and the partial unique index below) to the next migration (DDL in the task report).
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Index, String, Text, text

from shared.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(String(36), primary_key=True, default=_new_id)
    case_id = Column(String(64), nullable=False)
    # running | cleared | needs_proof | human_review | failed | skipped
    # ("skipped" = the case was not in status submitted, so nothing was done)
    status = Column(String(16), nullable=False, default="running")
    mode = Column(String(16), nullable=False, default="deterministic")  # deterministic | llm
    steps = Column(JSON, nullable=False, default=list)  # list of step records, in order
    started_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    triggered_by = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_case_id", "case_id"),
        # The database itself refuses a second RUNNING run for the same case.
        Index(
            "uq_agent_runs_one_running",
            "case_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )


AGENT_MODELS = [AgentRun]
