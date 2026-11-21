# OWNER: Member 3
# Mock SMS gateway. Native format: {"msg_id","dlr"}.
# dlr: ACCEPTD | DELIVRD | UNDELIV. No real SMS is ever sent.
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.db import get_db

from .control import MockRoute, make_guard
from .models import MockSmsMessage

router = APIRouter(prefix="/sms", tags=["mock-sms"], route_class=MockRoute)


def _error(status: int, reason: str) -> Dict[str, Any]:
    return {"msg_id": None, "dlr": "UNDELIV"}


guard = make_guard("sms", "SMS_MOCK_KEY", _error)


class SendRequest(BaseModel):
    to: str
    text: str
    ref: str


@router.post("/send")
def send(body: SendRequest, cond: Dict[str, Any] = Depends(guard), db: Session = Depends(get_db)):
    msg = MockSmsMessage(
        msg_id="SMS-" + uuid.uuid4().hex[:12].upper(),
        to_number=body.to,
        text=body.text,
        ref=body.ref,
        # sms_failure is read at send time and fixed for this message.
        dlr="UNDELIV" if cond["sms_failure"] else "DELIVRD",
    )
    db.add(msg)
    db.commit()
    return {"msg_id": msg.msg_id, "dlr": "ACCEPTD"}


@router.get("/messages/{msg_id}")
def get_message(msg_id: str, _cond=Depends(guard), db: Session = Depends(get_db)):
    msg = db.get(MockSmsMessage, msg_id)
    if msg is None:
        return JSONResponse({"msg_id": msg_id, "dlr": None}, status_code=404)
    return {"msg_id": msg.msg_id, "dlr": msg.dlr}
