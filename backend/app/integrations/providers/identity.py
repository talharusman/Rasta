# OWNER: Member 3
# Mock NADRA identity adapter. Normalizes NADRA's native format.
# NO fuzzy name matching here (Member 2 does that); record.name is returned so the
# caller can send it to Member 2. A timeout / outage / bad response is NEVER "verified".
import os
from datetime import date
from typing import List, Optional, Union

import httpx
from pydantic import BaseModel, ValidationError

from .base import IdentityRecord, IdentityResult, IdentityStatus
from .http import HttpOutcome, ServiceClient


class _Citizen(BaseModel):
    cit_id: str
    full_nm: str
    father_nm: Optional[str] = None
    birth_dt: Optional[str] = None
    gndr: Optional[str] = None
    dist: Optional[str] = None
    rec_status: str


class _NadraResponse(BaseModel):
    resp_code: str
    citizens: List[_Citizen]
    trace_no: Optional[str] = None


def _norm_date(value: Union[str, date, None]) -> Optional[str]:
    if value is None:
        return None
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text


def _result(status: IdentityStatus, outcome: HttpOutcome, **kw) -> IdentityResult:
    return IdentityResult(status=status, latency_ms=outcome.duration_ms, **kw)


def normalize_nadra(
    outcome: HttpOutcome, requested_id: str, requested_dob: Union[str, date, None] = None
) -> IdentityResult:
    """Pure function: HTTP outcome + request -> IdentityResult."""
    if not outcome.is_response:
        return _result(IdentityStatus.unavailable, outcome, error=outcome.error or "NADRA unavailable")
    if not outcome.is_success:
        return _result(
            IdentityStatus.unavailable, outcome, error=f"NADRA rejected the request (HTTP {outcome.status_code})"
        )
    try:
        parsed = _NadraResponse.model_validate(outcome.json())
    except (ValueError, ValidationError, TypeError) as exc:
        return _result(IdentityStatus.malformed, outcome, error=f"NADRA response malformed: {type(exc).__name__}")

    code = parsed.resp_code
    if code == "99":
        return _result(IdentityStatus.unavailable, outcome, error="NADRA reported a service error (99)")
    if code == "01":
        return _result(IdentityStatus.not_found, outcome, issues=["identity_not_found"])
    if code != "00":
        return _result(IdentityStatus.malformed, outcome, error=f"unknown NADRA resp_code {code!r}")
    if not parsed.citizens:
        return _result(IdentityStatus.malformed, outcome, error="NADRA said found (00) but returned no citizens")

    first = parsed.citizens[0]
    record = IdentityRecord(
        mock_identity_id=first.cit_id,
        name=first.full_nm,
        father_name=first.father_nm,
        dob=first.birth_dt,
        gender=first.gndr,
        district=first.dist,
        rec_status=first.rec_status,
    )
    if len(parsed.citizens) >= 2:
        return _result(IdentityStatus.duplicate, outcome, record=record, issues=["multiple_citizens_returned"])

    issues: List[str] = []
    if first.cit_id != requested_id:
        issues.append("identity_id_mismatch")
    if first.rec_status.upper() != "ACTIVE":
        issues.append(f"record_{first.rec_status.lower()}")
    reg_dob, want_dob = _norm_date(first.birth_dt), _norm_date(requested_dob)
    if reg_dob is None:
        issues.append("dob_missing_in_registry")
    elif want_dob is not None and reg_dob != want_dob:
        issues.append("dob_mismatch")

    blocking = [i for i in issues if i != "dob_missing_in_registry"]
    status = IdentityStatus.mismatch if blocking else IdentityStatus.verified
    return _result(status, outcome, record=record, issues=issues)


class MockNadraIdentityProvider:
    def __init__(self, http: ServiceClient):
        self.http = http

    @classmethod
    def from_env(cls, transport: Optional[httpx.AsyncBaseTransport] = None) -> "MockNadraIdentityProvider":
        return cls(
            ServiceClient(
                "nadra",
                os.getenv("MOCK_BASE_URL", "http://localhost:8000"),
                os.getenv("NADRA_MOCK_KEY", ""),
                transport=transport,
            )
        )

    async def verify(
        self,
        mock_identity_id: str,
        name: str,
        dob: Union[str, date, None] = None,
        case_id: Optional[str] = None,
    ) -> IdentityResult:
        try:
            outcome = await self.http.request(
                "POST",
                "/mock/nadra/verify",
                json_body={"cit_id": mock_identity_id, "full_nm": name, "birth_dt": _norm_date(dob)},
                safe=True,  # a lookup: no side effects, retries allowed
                case_id=case_id,
            )
            return normalize_nadra(outcome, mock_identity_id, dob)
        except Exception as exc:  # never raise to callers
            return IdentityResult(status=IdentityStatus.unavailable, error=f"identity adapter error: {type(exc).__name__}")

    async def get_record(self, mock_identity_id: str, case_id: Optional[str] = None) -> IdentityResult:
        try:
            outcome = await self.http.request(
                "GET", f"/mock/nadra/records/{mock_identity_id}", safe=True, case_id=case_id
            )
            return normalize_nadra(outcome, mock_identity_id, None)
        except Exception as exc:
            return IdentityResult(status=IdentityStatus.unavailable, error=f"identity adapter error: {type(exc).__name__}")
