# OWNER: Member 3
# Enqueue side of the job queue, plus the helper functions teammates call:
#   start_case_processing(case_id), enqueue_disbursement(case_id),
#   enqueue_notification(case_id, recipient, message)
# All functions here are synchronous (plain database calls). Inside async code use
# `await aenqueue(...)`.
import asyncio
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent import platform_bridge
from shared import db as shared_db

from .models import Job

STATUSES = ("queued", "running", "done", "failed")


class JobFailedPermanently(Exception):
    """Raise from a handler to fail the job at once, with no retries."""


@contextmanager
def session():
    s = shared_db.SessionLocal()  # looked up at call time
    try:
        yield s
    finally:
        s.close()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def snapshot(j: Job) -> Dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "payload": dict(j.payload or {}), "status": j.status,
        "attempts": j.attempts, "max_attempts": j.max_attempts, "run_after": _iso(j.run_after),
        "last_error": j.last_error, "dedupe_key": j.dedupe_key,
        "created_at": _iso(j.created_at), "updated_at": _iso(j.updated_at),
    }


def enqueue(
    kind: str,
    payload: Optional[Dict[str, Any]] = None,
    delay_seconds: float = 0,
    max_attempts: int = 4,
    dedupe_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a job. If dedupe_key already exists (in ANY status) the existing job is
    returned and nothing new is created. The result has "deduplicated": bool."""
    if not kind or not str(kind).strip():
        raise ValueError("kind is required")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")

    def existing(s) -> Optional[Job]:
        if not dedupe_key:
            return None
        return s.execute(select(Job).where(Job.dedupe_key == dedupe_key)).scalar_one_or_none()

    with session() as s:
        found = existing(s)
        if found is not None:
            return {**snapshot(found), "deduplicated": True}
        job = Job(kind=kind, payload=dict(payload or {}), status="queued", attempts=0,
                  max_attempts=max_attempts, dedupe_key=dedupe_key,
                  run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds))
        s.add(job)
        try:
            s.commit()
        except IntegrityError:  # a concurrent enqueue with the same key won
            s.rollback()
            found = existing(s)
            if found is None:
                raise
            return {**snapshot(found), "deduplicated": True}
        return {**snapshot(job), "deduplicated": False}


async def aenqueue(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return await asyncio.to_thread(enqueue, *args, **kwargs)


def merge_payload(job_id: str, extra: Dict[str, Any]) -> None:
    """Remember progress inside a job (e.g. a created notification id) so a retry
    does not repeat that step."""
    with session() as s:
        job = s.get(Job, job_id)
        job.payload = {**(job.payload or {}), **extra}  # new dict so the change is detected
        s.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with session() as s:
        j = s.get(Job, job_id)
        return snapshot(j) if j else None


def list_jobs(status: Optional[str] = None, kind: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with session() as s:
        q = select(Job)
        if status:
            q = q.where(Job.status == status)
        if kind:
            q = q.where(Job.kind == kind)
        rows = s.execute(q.order_by(Job.created_at.desc(), Job.id).limit(min(limit, 100))).scalars().all()
        return [snapshot(j) for j in rows]


def public_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """A job as shown over HTTP: recipient masked, message text left out."""
    payload = dict(job.get("payload") or {})
    if payload.get("recipient"):
        payload["recipient"] = "***" + str(payload["recipient"])[-4:]
    if "message" in payload:
        payload["message"] = f"<{len(str(payload['message']))} chars>"
    return {**job, "payload": payload}


# ---------------------------------------------------------------------------
# Helpers for teammates
# ---------------------------------------------------------------------------
def start_case_processing(case_id: str) -> Dict[str, Any]:
    """Member 1: call after a case is submitted. Enqueues a process_case job (the worker
    runs the agent). The dedupe key uses the case's submission_count, so submitting
    twice enqueues once; the agent also refuses to run a case twice at the same time."""
    marker: Any = None
    try:
        marker = platform_bridge.get_case(case_id).get("submission_count")
    except Exception:
        pass
    if marker is None:  # TODO(M1): add submission_count to the case; the timestamp is the fallback
        marker = f"t{int(time.time())}"
    return enqueue("process_case", {"case_id": case_id}, dedupe_key=f"process-{case_id}-{marker}")


def enqueue_disbursement(case_id: str) -> Dict[str, Any]:
    """One disbursement job per case, ever (dedupe key "disburse-<case_id>"). The job only
    pays a case an officer has approved; anything else fails without retry."""
    return enqueue("disburse_case", {"case_id": case_id}, dedupe_key=f"disburse-{case_id}")


def enqueue_notification(case_id: str, recipient: str, message: str,
                         dedupe_key: Optional[str] = None) -> Dict[str, Any]:
    return enqueue("send_notification", {"case_id": case_id, "recipient": recipient, "message": message},
                   dedupe_key=dedupe_key)
