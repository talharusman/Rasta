# OWNER: Member 3
# Mock NADRA. Native format: {"resp_code","citizens":[...],"trace_no"}.
# resp_code: "00" found, "01" not found, "99" service/auth error.
import asyncio
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.db import get_db

from . import control
from .control import MockRoute, make_guard
from .models import MockIdentityRecord

router = APIRouter(prefix="/nadra", tags=["mock-nadra"], route_class=MockRoute)

TIMEOUT_ID = "MOCK-TIMEOUT-01"
MALFORMED_ID = "MOCK-MALFORMED-01"
MISMATCH_NAME = "Mismatched Person"


def _trace() -> str:
    return "NDR" + uuid.uuid4().hex[:10].upper()


def _error(status: int, reason: str) -> Dict[str, Any]:
    return {"resp_code": "99", "citizens": [], "trace_no": _trace()}


guard = make_guard("nadra", "NADRA_MOCK_KEY", _error, "nadra_outage", "nadra_timeout")


class VerifyRequest(BaseModel):
    cit_id: str
    full_nm: str
    birth_dt: Optional[str] = None


def _citizen(rec: MockIdentityRecord) -> Dict[str, Any]:
    return {
        "cit_id": rec.cit_id,
        "full_nm": rec.full_nm,
        "father_nm": rec.father_nm,
        "birth_dt": rec.birth_dt,
        "gndr": rec.gndr,
        "dist": rec.dist,
        "rec_status": rec.rec_status,
    }


async def _lookup(cit_id: str, cond: Dict[str, Any], db: Session):
    """Shared by verify and records. Returns a Response."""
    if cit_id == TIMEOUT_ID:
        await asyncio.sleep(control.TIMEOUT_SECONDS)
    if cit_id == MALFORMED_ID or cond["malformed_response"]:
        # Deliberately invalid JSON with a JSON content type.
        return Response('{"resp_code": "00", "citizens": [', media_type="application/json")
    rec = db.get(MockIdentityRecord, cit_id)
    if rec is None:
        return _json({"resp_code": "01", "citizens": [], "trace_no": _trace()})
    citizen = _citizen(rec)
    if cond["identity_mismatch"]:
        citizen["full_nm"] = MISMATCH_NAME
    citizens = [citizen, dict(citizen)] if cond["duplicated_response"] else [citizen]
    return _json({"resp_code": "00", "citizens": citizens, "trace_no": _trace()})


def _json(body: Dict[str, Any]):
    return JSONResponse(body)


@router.post("/verify")
async def verify(
    body: VerifyRequest,
    cond: Dict[str, Any] = Depends(guard),
    db: Session = Depends(get_db),
):
    return await _lookup(body.cit_id, cond, db)


@router.get("/records/{cit_id}")
async def records(
    cit_id: str,
    cond: Dict[str, Any] = Depends(guard),
    db: Session = Depends(get_db),
):
    return await _lookup(cit_id, cond, db)
