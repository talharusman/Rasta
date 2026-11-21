# OWNER: Member 3
# The job worker: every 2 seconds it claims due jobs (SELECT ... FOR UPDATE SKIP LOCKED, so
# several workers never take the same job), runs them, and records the outcome.
#  - success            -> done
#  - exception          -> attempts + 1, run_after = now + min(5 * 2^attempts, 300) seconds
#  - out of attempts    -> failed + log_audit("system", "job_worker", "job_failed", ...)
#  - JobFailedPermanently -> failed at once, no retry, also audited
#  - jobs stuck in "running" for over 5 minutes are put back to queued
# Failures are always recorded (last_error + audit); a job is never dropped silently.
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select

from app.agent import platform_bridge

from . import handlers
from .models import Job, WorkerHeartbeat
from .queue import JobFailedPermanently, session, snapshot

logger = logging.getLogger("m3.jobs.worker")

POLL_SECONDS = 2.0
STUCK_AFTER_SECONDS = 300.0
MAX_CONCURRENT = 5
JOB_TIMEOUT = 120.0
BATCH = 5

_task: Optional["asyncio.Task[Any]"] = None
_inflight: Set["asyncio.Task[Any]"] = set()


def retry_delay(attempts: int) -> float:
    """Seconds to wait before retry, where attempts is the count INCLUDING the failure
    that just happened: 10, 20, 40, 80, 160, then 300 at most."""
    return min(5 * 2 ** attempts, 300)


def worker_enabled() -> bool:
    return os.getenv("RUN_JOB_WORKER", "").strip().lower() in ("1", "true", "yes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- database steps (sync; run through asyncio.to_thread) ---------------------------------
def heartbeat() -> None:
    with session() as s:
        row = s.get(WorkerHeartbeat, 1)
        if row is None:
            s.add(WorkerHeartbeat(id=1, last_seen=_now()))
        else:
            row.last_seen = _now()
        s.commit()


def heartbeat_age_seconds() -> Optional[float]:
    """Seconds since the worker last checked in; None if it never has."""
    with session() as s:
        row = s.get(WorkerHeartbeat, 1)
        if row is None:
            return None
        seen = row.last_seen if row.last_seen.tzinfo else row.last_seen.replace(tzinfo=timezone.utc)
        return (_now() - seen).total_seconds()


def _audit_failed(job: Dict[str, Any], error: str) -> None:
    try:
        platform_bridge.log_audit(
            "system", "job_worker", "job_failed", f"job:{job['id']}",
            {"kind": job["kind"], "attempts": job["attempts"], "max_attempts": job["max_attempts"],
             "last_error": error, "case_id": (job.get("payload") or {}).get("case_id")})
    except Exception:
        logger.exception("could not audit failed job %s", job["id"])


def reset_stuck() -> int:
    """Jobs 'running' for too long mean the worker died mid-job: queue them again
    (counting it as an attempt, so a job that kills the worker cannot loop forever)."""
    cutoff = _now() - timedelta(seconds=STUCK_AFTER_SECONDS)
    reset = 0
    with session() as s:
        stuck = s.execute(select(Job).where(Job.status == "running", Job.updated_at < cutoff)
                          .with_for_update(skip_locked=True)).scalars().all()
        failed: List[Dict[str, Any]] = []
        for job in stuck:
            job.attempts += 1
            job.last_error = "worker stopped while running this job (reset after being stuck)"
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                failed.append(snapshot(job))
            else:
                job.status, job.run_after = "queued", _now()
            reset += 1
        s.commit()
    for job in failed:
        _audit_failed(job, job["last_error"])
    return reset


def claim(limit: int) -> List[Dict[str, Any]]:
    """Take up to `limit` due jobs and mark them running, in one transaction. On Postgres the
    row locks (SKIP LOCKED) mean two workers can never claim the same job."""
    with session() as s:
        rows = s.execute(
            select(Job).where(Job.status == "queued", Job.run_after <= _now())
            .order_by(Job.run_after, Job.created_at).limit(limit).with_for_update(skip_locked=True)
        ).scalars().all()
        for job in rows:
            job.status = "running"
        s.commit()
        return [snapshot(j) for j in rows]


def _mark_done(job_id: str) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        job.status = "done"
        s.commit()


def _mark_failure(job_id: str, error: str, permanent: bool) -> Dict[str, Any]:
    with session() as s:
        job = s.get(Job, job_id)
        job.attempts += 1
        job.last_error = error[:2000]
        if permanent or job.attempts >= job.max_attempts:
            job.status = "failed"
        else:
            job.status = "queued"
            job.run_after = _now() + timedelta(seconds=retry_delay(job.attempts))
        s.commit()
        return snapshot(job)


# ---- running -----------------------------------------------------------------------------
async def run_job(job: Dict[str, Any]) -> None:
    kind = job["kind"]
    try:
        handler = handlers.HANDLERS.get(kind)
        if handler is None:
            raise JobFailedPermanently(f"unknown job kind: {kind}")
        await asyncio.wait_for(handler(job["payload"], job), timeout=JOB_TIMEOUT)
    except JobFailedPermanently as exc:
        error, permanent = f"{exc}", True
    except asyncio.CancelledError:
        raise  # shutting down: the job stays "running" and is reset after 5 minutes
    except Exception as exc:  # includes timeouts: retry with backoff
        error, permanent = f"{type(exc).__name__}: {exc}", False
    else:
        await asyncio.to_thread(_mark_done, job["id"])
        logger.info("job done kind=%s id=%s", kind, job["id"])
        return

    updated = await asyncio.to_thread(_mark_failure, job["id"], error, permanent)
    if updated["status"] == "failed":
        logger.error("job FAILED kind=%s id=%s attempts=%s error=%s", kind, job["id"], updated["attempts"], error)
        await asyncio.to_thread(_audit_failed, updated, error)
    else:
        logger.warning("job will retry kind=%s id=%s attempts=%s next=%s error=%s",
                       kind, job["id"], updated["attempts"], updated["run_after"], error)


async def run_once(wait: bool = True) -> int:
    """One worker pass: heartbeat, reset stuck jobs, claim due jobs, run them.
    wait=True returns when they finish (tests); the loop uses wait=False so a slow job
    does not hold up the others. Returns how many jobs were claimed."""
    await asyncio.to_thread(heartbeat)
    await asyncio.to_thread(reset_stuck)
    room = MAX_CONCURRENT - len(_inflight)
    if room <= 0:
        return 0
    claimed = await asyncio.to_thread(claim, min(BATCH, room))
    tasks = []
    for job in claimed:
        task = asyncio.ensure_future(run_job(job))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)
        tasks.append(task)
    if wait and tasks:
        await asyncio.gather(*tasks)
    return len(claimed)


async def run_forever() -> None:
    logger.info("job worker started (poll every %ss)", POLL_SECONDS)
    while True:
        try:
            await run_once(wait=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker pass failed")  # keep looping; the heartbeat shows if we are stuck
        await asyncio.sleep(POLL_SECONDS)


def start() -> "asyncio.Task[Any]":
    """Start the loop in the running event loop (once)."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(run_forever())
    return _task


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
