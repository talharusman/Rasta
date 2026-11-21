# OWNER: Member 3
# Job routes + health checks + the worker's startup hook.
#   POST /internal/jobs/notifications   (X-Service-Key) -> enqueue a notification job
#   GET  /internal/jobs?status=&kind=   (X-Service-Key) -> latest 100 jobs
#   GET  /api/v1/admin/jobs             (admin)         -> same, for Member 4's admin panel
#   GET  /health                        -> process is up
#   GET  /ready                         -> database reachable, and (if RUN_JOB_WORKER=true)
#                                          the worker heartbeat is younger than 30s
#
# The worker starts from this router's startup hook when RUN_JOB_WORKER=true, so
# backend/main.py needs only the usual mount (Member 1 / whoever owns main.py):
#   from app.jobs.router import router as m3_jobs_router
#   app.include_router(m3_jobs_router)
# (A router startup hook is ignored if the app is ever given a `lifespan=`; then call
#  app.jobs.worker.start() / stop() from that lifespan instead.)
import asyncio
import logging
import os
import secrets
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.agent import platform_bridge
from shared import db as shared_db

from . import queue, worker

logger = logging.getLogger("m3.jobs.router")

HEARTBEAT_MAX_AGE_SECONDS = 30.0


async def _startup() -> None:
    if worker.worker_enabled():
        worker.start()
    else:
        logger.info("RUN_JOB_WORKER is not true: job worker not started in this process")


async def _shutdown() -> None:
    await worker.stop()


router = APIRouter(tags=["jobs"], on_startup=[_startup], on_shutdown=[_shutdown])


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}, "request_id": uuid.uuid4().hex},
        status_code=status)


def _auth(x_service_key: Optional[str]) -> Optional[JSONResponse]:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or not x_service_key or not secrets.compare_digest(x_service_key, expected):
        return _error(403, "FORBIDDEN", "internal service key required")  # fail closed
    return None


def _list(status: Optional[str], kind: Optional[str], tenant_id=None):
    if status and status not in queue.STATUSES:
        return _error(422, "VALIDATION_ERROR", f"status must be one of {', '.join(queue.STATUSES)}")
    return {"jobs": [queue.public_view(j) for j in queue.list_jobs(status, kind, 100, tenant_id)]}


@router.post("/internal/jobs/notifications", status_code=202)
async def post_notification(payload: Optional[Dict[str, Any]] = Body(default=None),
                            x_service_key: Optional[str] = Header(None)):
    denied = _auth(x_service_key)
    if denied:
        return denied
    body = payload or {}
    fields = {k: body.get(k) for k in ("case_id", "recipient", "message")}
    missing = [k for k, v in fields.items() if not isinstance(v, str) or not v.strip()]
    if missing:
        return _error(422, "VALIDATION_ERROR", f"required (non-empty strings): {', '.join(missing)}")
    dedupe = body.get("dedupe_key") if isinstance(body.get("dedupe_key"), str) else None
    job = await asyncio.to_thread(queue.enqueue_notification, fields["case_id"], fields["recipient"],
                                  fields["message"], dedupe)
    return JSONResponse({"job_id": job["id"], "status": job["status"], "deduplicated": job["deduplicated"]},
                        status_code=202)


@router.get("/internal/jobs")
async def get_jobs(status: Optional[str] = None, kind: Optional[str] = None,
                   x_service_key: Optional[str] = Header(None)):
    denied = _auth(x_service_key)
    if denied:
        return denied
    return await asyncio.to_thread(_list, status, kind)


# TODO(M1): platform_bridge.require_admin is a fail-closed STUB (needs the internal key);
# it will be replaced by Member 1's real admin-role dependency.
@router.get("/api/v1/admin/jobs")
async def admin_jobs(status: Optional[str] = None, kind: Optional[str] = None,
                     admin: Dict[str, str] = Depends(platform_bridge.require_admin)):
    return await asyncio.to_thread(_list, status, kind, admin.get("tenant_id"))


@router.get("/health")
async def health():
    return {"status": "ok"}


def _check_ready() -> Dict[str, Any]:
    checks: Dict[str, str] = {}
    try:
        with shared_db.SessionLocal() as s:
            s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    if platform_bridge.is_live():
        from rasta_platform.services import settings

        checks["auth"] = "ok" if settings.supabase_url and settings.supabase_publishable_key else "unconfigured"
    if worker.worker_enabled():
        try:
            age = worker.heartbeat_age_seconds()
            if age is None:
                checks["worker"] = "no heartbeat yet"
            elif age > HEARTBEAT_MAX_AGE_SECONDS:
                checks["worker"] = f"stale: last heartbeat {int(age)}s ago"
            else:
                checks["worker"] = "ok"
        except Exception as exc:
            checks["worker"] = f"error: {type(exc).__name__}"
    else:
        checks["worker"] = "disabled"
    return checks


@router.get("/ready")
async def ready():
    checks = await asyncio.to_thread(_check_ready)
    if all(v in ("ok", "disabled") for v in checks.values()):
        return {"status": "ready", "checks": checks}
    body = {"error": {"code": "SERVICE_UNAVAILABLE", "message": "not ready", "retryable": True},
            "request_id": uuid.uuid4().hex, "checks": checks}
    return JSONResponse(body, status_code=503)
