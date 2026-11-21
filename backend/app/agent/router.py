# OWNER: Member 3
# Internal agent routes (header X-Service-Key = INTERNAL_SERVICE_KEY):
#   POST /internal/agent/process-case {case_id} -> 202 {run_id}
#   GET  /internal/agent/runs/{id}
# plus start_case_processing(case_id) for Member 1 to call from /cases/{id}/submit.
#
# For now the run is an asyncio task / background thread inside this process.
# TODO(Phase 5): move this onto the job queue (app/jobs) so a restart cannot lose runs.
#
# backend/main.py is not ours: whoever owns it mounts this router:
#   from app.agent.router import router as m3_agent_router
#   app.include_router(m3_agent_router)
import asyncio
import logging
import os
import secrets
import threading
import uuid
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Body, Header
from fastapi.responses import JSONResponse

from . import orchestrator

logger = logging.getLogger("m3.agent.router")

router = APIRouter(prefix="/internal/agent", tags=["agent"])

_TASKS: Set["asyncio.Task[Any]"] = set()  # strong references so tasks are not garbage collected


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}, "request_id": uuid.uuid4().hex},
        status_code=status)


def _auth(x_service_key: Optional[str]) -> Optional[JSONResponse]:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or not x_service_key or not secrets.compare_digest(x_service_key, expected):
        return _error(403, "FORBIDDEN", "internal service key required")  # fail closed
    return None


def _spawn(snapshot: Dict[str, Any]) -> None:
    """Run the pipeline in the background. In an async context it is an asyncio task;
    from a plain sync thread (e.g. a sync FastAPI route) it gets its own thread + loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(orchestrator.execute_run(snapshot))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    else:
        threading.Thread(target=lambda: asyncio.run(orchestrator.execute_run(snapshot)),
                         name=f"agent-run-{snapshot['id']}", daemon=True).start()


def start_case_processing(case_id: str, triggered_by: str = "submit") -> str:
    """For Member 1: call right after a case is submitted. Returns the run id at once;
    processing continues in the background. Calling it again while a run is in progress
    returns the SAME run id and starts nothing."""
    snapshot, created = orchestrator.create_or_get_run(case_id, triggered_by)
    if created:
        _spawn(snapshot)
    return snapshot["id"]


@router.post("/process-case", status_code=202)
async def process_case_route(payload: Optional[Dict[str, Any]] = Body(default=None),
                             x_service_key: Optional[str] = Header(None)):
    denied = _auth(x_service_key)
    if denied:
        return denied
    case_id = (payload or {}).get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        return _error(422, "VALIDATION_ERROR", "case_id (string) is required")
    snapshot, created = await asyncio.to_thread(orchestrator.create_or_get_run, case_id.strip(), "internal-api")
    if created:
        _spawn(snapshot)
    return JSONResponse({"run_id": snapshot["id"], "status": snapshot["status"],
                         "already_running": not created}, status_code=202)


@router.get("/runs/{run_id}")
async def get_run_route(run_id: str, x_service_key: Optional[str] = Header(None)):
    denied = _auth(x_service_key)
    if denied:
        return denied
    run = await asyncio.to_thread(orchestrator.load_run, run_id)
    if run is None:
        return _error(404, "VALIDATION_ERROR", "run not found")
    return run
