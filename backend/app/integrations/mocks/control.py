# OWNER: Member 3
# Fixture switches, API-key checks, switch effects, and the control routes.
import asyncio
import logging
import os
import secrets
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.agent import platform_bridge
from shared import db as shared_db

from .models import MockFixtureState

logger = logging.getLogger("m3.mocks.control")

# Seconds a "timeout" fixture sleeps. Longer than any sane client timeout.
TIMEOUT_SECONDS = 15.0

DEFAULT_CONDITIONS: Dict[str, Any] = {
    "identity_mismatch": False,
    "nadra_timeout": False,
    "nadra_outage": False,
    "duplicated_response": False,
    "malformed_response": False,
    "raast_outage": False,
    "sms_failure": False,
    "latency_ms": 0,
}
MAX_LATENCY_MS = 60_000


# ---------------------------------------------------------------------------
# Errors: raised from dependencies, rendered by MockRoute in the service's own
# native format (or the standard error shape for internal routes).
# ---------------------------------------------------------------------------
class MockServiceError(Exception):
    def __init__(self, status: int, body: Dict[str, Any]):
        self.status = status
        self.body = body


class MockRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except MockServiceError as exc:
                return JSONResponse(exc.body, status_code=exc.status)

        return handler


def standard_error(code: str, message: str, retryable: bool = False) -> Dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "retryable": retryable},
        "request_id": uuid.uuid4().hex,
    }


# ---------------------------------------------------------------------------
# Conditions (stored as a single JSON row)
# ---------------------------------------------------------------------------
@contextmanager
def _session(db=None):
    if db is not None:
        yield db
        return
    session = shared_db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _validate(updates: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in updates.items():
        if key not in DEFAULT_CONDITIONS:
            raise ValueError(f"unknown switch: {key}")
        if key == "latency_ms":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("latency_ms must be an integer")
            if not 0 <= value <= MAX_LATENCY_MS:
                raise ValueError(f"latency_ms must be 0..{MAX_LATENCY_MS}")
        elif not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        clean[key] = value
    return clean


def get_conditions(db=None) -> Dict[str, Any]:
    with _session(db) as s:
        row = s.get(MockFixtureState, 1)
        stored = dict(row.state) if row and row.state else {}
    return {**DEFAULT_CONDITIONS, **{k: v for k, v in stored.items() if k in DEFAULT_CONDITIONS}}


def set_conditions(updates: Dict[str, Any], db=None) -> Dict[str, Any]:
    clean = _validate(updates)
    with _session(db) as s:
        row = s.get(MockFixtureState, 1)
        merged = {**DEFAULT_CONDITIONS, **(dict(row.state) if row and row.state else {}), **clean}
        if row is None:
            s.add(MockFixtureState(id=1, state=merged))
        else:
            row.state = merged  # reassign whole dict so the JSON change is detected
        s.commit()
    return get_conditions(db)


def reset_conditions(db=None) -> Dict[str, Any]:
    with _session(db) as s:
        row = s.get(MockFixtureState, 1)
        if row is None:
            s.add(MockFixtureState(id=1, state=dict(DEFAULT_CONDITIONS)))
        else:
            row.state = dict(DEFAULT_CONDITIONS)
        s.commit()
    return get_conditions(db)


def _audit(actor_type: str, actor_id: str, action: str, before: Dict, after: Dict) -> None:
    changed = {k: {"from": before.get(k), "to": after.get(k)} for k in after if before.get(k) != after.get(k)}
    logger.warning("mock switch change by %s:%s action=%s changed=%s", actor_type, actor_id, action, changed)
    platform_bridge.log_audit(
        actor_type, actor_id, action, "mock_conditions", {"changed": changed, "conditions": after}
    )


# ---------------------------------------------------------------------------
# Per-service guard: API key -> latency -> outage -> timeout.
# ---------------------------------------------------------------------------
def _key_ok(expected: str, given: Optional[str]) -> bool:
    # Fail closed: if the env key is not configured, nothing gets in.
    return bool(expected) and bool(given) and secrets.compare_digest(given, expected)


def make_guard(
    service: str,
    env_key: str,
    error_body: Callable[[int, str], Dict[str, Any]],
    outage_switch: Optional[str] = None,
    timeout_switch: Optional[str] = None,
):
    """Build the FastAPI dependency for one mock service.
    error_body(status, reason) must return that service's NATIVE error body."""

    async def guard(x_mock_api_key: Optional[str] = Header(None)) -> Dict[str, Any]:
        if not _key_ok(os.getenv(env_key, ""), x_mock_api_key):
            raise MockServiceError(401, error_body(401, "AUTH"))
        cond = await run_in_threadpool(get_conditions)
        if cond["latency_ms"]:
            await asyncio.sleep(cond["latency_ms"] / 1000)
        if outage_switch and cond[outage_switch]:
            logger.info("%s outage switch active", service)
            raise MockServiceError(503, error_body(503, "SVC_DOWN"))
        if timeout_switch and cond[timeout_switch]:
            logger.info("%s timeout switch active: sleeping %ss", service, TIMEOUT_SECONDS)
            await asyncio.sleep(TIMEOUT_SECONDS)
        return cond

    return guard


# ---------------------------------------------------------------------------
# Control routes
# ---------------------------------------------------------------------------
def require_internal_key(x_service_key: Optional[str] = Header(None)) -> str:
    if not _key_ok(os.getenv("INTERNAL_SERVICE_KEY", ""), x_service_key):
        raise MockServiceError(403, standard_error("FORBIDDEN", "internal service key required"))
    return "mock-control"


def _apply(updates: Dict[str, Any], actor_type: str, actor_id: str) -> Dict[str, Any]:
    before = get_conditions()
    try:
        after = set_conditions(updates)
    except ValueError as exc:
        raise MockServiceError(422, standard_error("VALIDATION_ERROR", str(exc)))
    _audit(actor_type, actor_id, "mock_conditions.update", before, after)
    return after


internal_router = APIRouter(
    prefix="/internal/mock-control",
    tags=["mock-control"],
    route_class=MockRoute,
    dependencies=[Depends(require_internal_key)],
)


@internal_router.get("")
def internal_get():
    return get_conditions()


@internal_router.put("")
def internal_put(updates: Dict[str, Any] = Body(...)):
    return _apply(updates, "service", "mock-control")


@internal_router.delete("")
def internal_delete():
    before = get_conditions()
    after = reset_conditions()
    _audit("service", "mock-control", "mock_conditions.reset", before, after)
    return after


admin_router = APIRouter(prefix="/api/v1/admin/mock-conditions", tags=["admin-mock"], route_class=MockRoute)


@admin_router.get("")
def admin_get(admin: Dict[str, str] = Depends(platform_bridge.require_admin)):
    return get_conditions()


@admin_router.put("")
def admin_put(
    updates: Dict[str, Any] = Body(...),
    admin: Dict[str, str] = Depends(platform_bridge.require_admin),
):
    return _apply(updates, "admin", str(admin.get("id", "unknown")))
