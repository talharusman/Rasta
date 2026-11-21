# OWNER: Member 3
# Mock SMS adapter. Native dlr: ACCEPTD | DELIVRD | UNDELIV. No real SMS is sent.
# The integrated worker supplies a stable key for each send or resend.
import os
from typing import Optional

import httpx
from pydantic import BaseModel, ValidationError

from .base import NotificationResult, NotificationStatus
from .http import HttpOutcome, ServiceClient

_DLR = {
    "ACCEPTD": NotificationStatus.sent,
    "DELIVRD": NotificationStatus.delivered,
    "UNDELIV": NotificationStatus.failed,
}


class _Sms(BaseModel):
    msg_id: Optional[str] = None
    dlr: str


def _normalize(outcome: HttpOutcome, fallback_id: Optional[str] = None) -> NotificationResult:
    if not outcome.is_success:
        return NotificationResult(
            status=NotificationStatus.unavailable, message_id=fallback_id, latency_ms=outcome.duration_ms,
            error=outcome.error or f"SMS gateway rejected the request (HTTP {outcome.status_code})")
    try:
        body = _Sms.model_validate(outcome.json())
    except (ValueError, ValidationError, TypeError):
        return NotificationResult(status=NotificationStatus.unavailable, message_id=fallback_id,
                                  latency_ms=outcome.duration_ms, error="SMS response malformed")
    status = _DLR.get(body.dlr)
    if status is None:
        return NotificationResult(status=NotificationStatus.unavailable, message_id=body.msg_id or fallback_id,
                                  latency_ms=outcome.duration_ms, error=f"unknown SMS dlr {body.dlr!r}")
    if status is not NotificationStatus.failed and not (body.msg_id or fallback_id):
        return NotificationResult(status=NotificationStatus.unavailable, latency_ms=outcome.duration_ms,
                                  error="SMS response had no msg_id")
    return NotificationResult(status=status, message_id=body.msg_id or fallback_id, latency_ms=outcome.duration_ms,
                              error="SMS undeliverable" if status is NotificationStatus.failed else None)


class MockSmsNotificationProvider:
    def __init__(self, http: ServiceClient):
        self.http = http

    @classmethod
    def from_env(cls, transport: Optional[httpx.AsyncBaseTransport] = None) -> "MockSmsNotificationProvider":
        return cls(
            ServiceClient(
                "sms",
                os.getenv("MOCK_BASE_URL", "http://localhost:8000"),
                os.getenv("SMS_MOCK_KEY", ""),
                transport=transport,
            )
        )

    async def send(self, recipient: str, message: str, case_id: str, *, idempotency_key: str | None = None) -> NotificationResult:
        try:
            outcome = await self.http.request(
                "POST", "/mock/sms/send",
                json_body={"to": recipient, "text": message, "ref": case_id},
                headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
                safe=False, case_id=case_id)
            return _normalize(outcome)
        except Exception as exc:
            return NotificationResult(status=NotificationStatus.unavailable,
                                      error=f"notification adapter error: {type(exc).__name__}")

    async def status(self, message_id: str) -> NotificationResult:
        try:
            outcome = await self.http.request("GET", f"/mock/sms/messages/{message_id}", safe=True)
            return _normalize(outcome, fallback_id=message_id)
        except Exception as exc:
            return NotificationResult(status=NotificationStatus.unavailable, message_id=message_id,
                                      error=f"notification adapter error: {type(exc).__name__}")
