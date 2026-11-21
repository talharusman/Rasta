# OWNER: Member 3
# Mock Raast payment adapter. Safety rules (M3_CONTEXT.md):
#  - pays ONLY for case status "approved" (officer-approved); "cleared" has no authority
#  - idempotency key = "disburse-" + case_id, persisted in payment_requests BEFORE calling Raast
#  - POST /disburse is attempted ONCE per call (never auto-retried); after a timeout or
#    other unknown outcome we look the transaction up by idempotency key instead
#  - never raises: every error becomes a status
import asyncio
import inspect
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple, Union

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent import platform_bridge
from shared import db as shared_db

from .base import AccountResult, AccountStatus, PaymentResult, PaymentStatus
from .http import HttpOutcome, ServiceClient
from .models import PaymentRequest

logger = logging.getLogger("m3.providers.payment")

_STAT_TO_STATUS = {"ACSC": PaymentStatus.success, "PDNG": PaymentStatus.pending, "RJCT": PaymentStatus.failed}


class _RaastTxn(BaseModel):
    txnRef: Optional[str] = None
    stat: str
    amt: Optional[float] = None
    acct: Optional[str] = None
    rsnCd: Optional[str] = None


class _RaastValidate(BaseModel):
    acct: Optional[str] = None
    holder_nm: Optional[str] = None
    stat: str


@dataclass
class _Row:
    case_id: str
    idempotency_key: str
    amount: Decimal
    account_id: str
    status: str
    transaction_id: Optional[str]
    attempts: int
    last_error: Optional[str]


# ---- payment_requests access (sync; always called through asyncio.to_thread) -------------
@contextmanager
def _session():
    session = shared_db.SessionLocal()  # looked up at call time
    try:
        yield session
    finally:
        session.close()


def _snapshot(r: PaymentRequest) -> _Row:
    return _Row(r.case_id, r.idempotency_key, Decimal(r.amount), r.account_id, r.status,
                r.transaction_id, r.attempts, r.last_error)


def _db_get(case_id: str) -> Optional[_Row]:
    with _session() as s:
        r = s.execute(select(PaymentRequest).where(PaymentRequest.case_id == case_id)).scalar_one_or_none()
        return _snapshot(r) if r else None


def _db_insert(case_id: str, key: str, amount: Decimal, account_id: str) -> _Row:
    with _session() as s:
        s.add(PaymentRequest(case_id=case_id, idempotency_key=key, amount=amount,
                             account_id=account_id, status="requested", attempts=0))
        try:
            s.commit()
        except IntegrityError:  # a concurrent call created the row first: use it
            s.rollback()
        r = s.execute(select(PaymentRequest).where(PaymentRequest.case_id == case_id)).scalar_one()
        return _snapshot(r)


def _db_update(case_id: str, status: Optional[str] = None, transaction_id: Optional[str] = None,
               last_error: Optional[str] = None, bump_attempts: bool = False,
               clear_error: bool = False) -> None:
    with _session() as s:
        r = s.execute(select(PaymentRequest).where(PaymentRequest.case_id == case_id)).scalar_one()
        if status is not None:
            r.status = status
        if transaction_id is not None:
            r.transaction_id = transaction_id
        if last_error is not None:
            r.last_error = last_error
        elif clear_error:
            r.last_error = None
        if bump_attempts:
            r.attempts = (r.attempts or 0) + 1
        s.commit()


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---- helpers ------------------------------------------------------------------------------
def _parse_txn(outcome: HttpOutcome) -> Optional[_RaastTxn]:
    try:
        txn = _RaastTxn.model_validate(outcome.json())
    except (ValueError, ValidationError, TypeError):
        return None
    if txn.stat not in _STAT_TO_STATUS:
        return None
    if txn.stat != "RJCT" and not txn.txnRef:
        return None
    return txn


def _to_amount(value: Union[Decimal, int, float, str]) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid amount: {value!r}")
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"amount must be positive: {value!r}")
    return amount


def _case_status(case: Any) -> str:
    raw = case.get("status") if isinstance(case, dict) else getattr(case, "status", None)
    raw = getattr(raw, "value", raw)  # enum -> value
    return str(raw).strip().lower() if raw is not None else ""


async def _call_bridge(fn, *args):
    result = await asyncio.to_thread(fn, *args)
    return await result if inspect.isawaitable(result) else result


def _safe_audit(*args, **kwargs) -> None:
    try:
        platform_bridge.log_audit(*args, **kwargs)
    except Exception:  # auditing must not break the adapter's no-raise contract
        logger.exception("log_audit failed")


def _from_row(row: _Row, **kw) -> PaymentResult:
    status = {"success": PaymentStatus.success, "pending": PaymentStatus.pending,
              "failed": PaymentStatus.failed}.get(row.status, PaymentStatus.unavailable)
    return PaymentResult(status=status, transaction_id=row.transaction_id,
                         idempotency_key=row.idempotency_key, **kw)


class MockRaastPaymentProvider:
    def __init__(self, http: ServiceClient):
        self.http = http

    @classmethod
    def from_env(cls, transport: Optional[httpx.AsyncBaseTransport] = None) -> "MockRaastPaymentProvider":
        return cls(
            ServiceClient(
                "raast",
                os.getenv("MOCK_BASE_URL", "http://localhost:8000"),
                os.getenv("RAAST_MOCK_KEY", ""),
                transport=transport,
            )
        )

    # ---- safe reads -------------------------------------------------------------------
    async def validate_account(
        self, account_id: str, beneficiary_name: str, case_id: Optional[str] = None
    ) -> AccountResult:
        try:
            outcome = await self.http.request(
                "POST", "/mock/raast/account-validate",
                json_body={"acct": account_id, "beneficiary_nm": beneficiary_name},
                safe=True, case_id=case_id,
            )
            if not outcome.is_success:
                return AccountResult(status=AccountStatus.unavailable, account_id=account_id,
                                     latency_ms=outcome.duration_ms,
                                     error=outcome.error or f"Raast rejected the request (HTTP {outcome.status_code})")
            try:
                body = _RaastValidate.model_validate(outcome.json())
            except (ValueError, ValidationError, TypeError):
                return AccountResult(status=AccountStatus.unavailable, account_id=account_id,
                                     latency_ms=outcome.duration_ms, error="Raast response malformed")
            mapped = {"MATCH": AccountStatus.matched, "NOMATCH": AccountStatus.mismatched,
                      "NOTFOUND": AccountStatus.not_found}.get(body.stat)
            if mapped is None:
                return AccountResult(status=AccountStatus.unavailable, account_id=account_id,
                                     latency_ms=outcome.duration_ms, error=f"unknown Raast stat {body.stat!r}")
            return AccountResult(status=mapped, account_id=account_id, holder_name=body.holder_nm,
                                 latency_ms=outcome.duration_ms)
        except Exception as exc:
            return AccountResult(status=AccountStatus.unavailable, account_id=account_id,
                                 error=f"payment adapter error: {type(exc).__name__}")

    async def get_transaction(self, transaction_id: str) -> PaymentResult:
        try:
            outcome = await self.http.request(
                "GET", f"/mock/raast/transactions/{transaction_id}", safe=True)
            if outcome.is_response and outcome.status_code == 404:
                return PaymentResult(status=PaymentStatus.failed, transaction_id=transaction_id,
                                     latency_ms=outcome.duration_ms, error="transaction_not_found")
            if not outcome.is_success:
                return PaymentResult(status=PaymentStatus.unavailable, transaction_id=transaction_id,
                                     latency_ms=outcome.duration_ms,
                                     error=outcome.error or f"Raast rejected the request (HTTP {outcome.status_code})")
            txn = _parse_txn(outcome)
            if txn is None:
                return PaymentResult(status=PaymentStatus.unavailable, transaction_id=transaction_id,
                                     latency_ms=outcome.duration_ms, error="Raast response malformed")
            return PaymentResult(status=_STAT_TO_STATUS[txn.stat], transaction_id=txn.txnRef or transaction_id,
                                 latency_ms=outcome.duration_ms, error=txn.rsnCd if txn.stat == "RJCT" else None)
        except Exception as exc:
            return PaymentResult(status=PaymentStatus.unavailable, transaction_id=transaction_id,
                                 error=f"payment adapter error: {type(exc).__name__}")

    # ---- lookup by idempotency key (safe read) -----------------------------------------
    async def _lookup_by_key(self, case_id: str, key: str) -> Tuple[str, Optional[PaymentResult]]:
        """Returns ("found", result) | ("not_found", None) | ("unavailable", result).
        Updates the payment_requests row when the transaction is found."""
        outcome = await self.http.request(
            "GET", "/mock/raast/transactions", params={"idempotency_key": key}, safe=True, case_id=case_id)
        if outcome.is_response and outcome.status_code == 404:
            return "not_found", None
        if not outcome.is_success:
            await _db(_db_update, case_id, last_error=f"lookup failed: {outcome.error or outcome.status_code}")
            return "unavailable", PaymentResult(
                status=PaymentStatus.unavailable, idempotency_key=key, reconcile_required=True,
                latency_ms=outcome.duration_ms,
                error=f"could not look up transaction: {outcome.error or 'HTTP ' + str(outcome.status_code)}")
        txn = _parse_txn(outcome)
        if txn is None:
            await _db(_db_update, case_id, last_error="lookup returned malformed response")
            return "unavailable", PaymentResult(
                status=PaymentStatus.unavailable, idempotency_key=key, reconcile_required=True,
                latency_ms=outcome.duration_ms, error="transaction lookup response malformed")
        return "found", await self._record_txn(case_id, key, txn, outcome.duration_ms)

    async def _record_txn(self, case_id: str, key: str, txn: _RaastTxn, latency_ms: int) -> PaymentResult:
        status = _STAT_TO_STATUS[txn.stat]
        error = f"Raast rejected the payment ({txn.rsnCd})" if txn.stat == "RJCT" else None
        await _db(_db_update, case_id, status=status.value, transaction_id=txn.txnRef,
                  last_error=error, clear_error=error is None)
        return PaymentResult(status=status, transaction_id=txn.txnRef, idempotency_key=key,
                             latency_ms=latency_ms, error=error)

    async def reconcile_unknown(self, case_id: str) -> PaymentResult:
        """Lookup only. Never sends a payment."""
        key = f"disburse-{case_id}"
        try:
            row = await _db(_db_get, case_id)
            if row is None:
                return PaymentResult(status=PaymentStatus.failed, idempotency_key=key,
                                     no_transaction_found=True,
                                     error="no payment request exists for this case")
            if row.status == "success":
                return _from_row(row)
            kind, result = await self._lookup_by_key(case_id, key)
            if kind != "not_found":
                return result  # found or unavailable
            await _db(_db_update, case_id, status="failed", last_error="no transaction at provider for this key")
            return PaymentResult(
                status=PaymentStatus.failed, idempotency_key=key, no_transaction_found=True,
                error="no transaction found at the provider for this key; disburse can be called again (idempotent)")
        except Exception as exc:
            return PaymentResult(status=PaymentStatus.unavailable, idempotency_key=key, reconcile_required=True,
                                 error=f"payment adapter error: {type(exc).__name__}")

    # ---- disburse -----------------------------------------------------------------------
    async def disburse(
        self, case_id: str, amount: Union[Decimal, int, float, str], account_id: str
    ) -> PaymentResult:
        key = f"disburse-{case_id}"
        try:
            return await self._disburse(case_id, key, amount, account_id)
        except Exception as exc:
            logger.exception("disburse failed unexpectedly for %s", case_id)
            # We may or may not have reached Raast: demand a reconcile, never a blind retry.
            return PaymentResult(status=PaymentStatus.unavailable, idempotency_key=key, reconcile_required=True,
                                 error=f"payment adapter error: {type(exc).__name__}")

    async def _disburse(self, case_id: str, key: str, amount: Any, account_id: str) -> PaymentResult:
        try:
            amt = _to_amount(amount)
        except ValueError as exc:
            return PaymentResult(status=PaymentStatus.failed, idempotency_key=key, error=str(exc))

        # (a) only officer-approved cases may be paid
        try:
            case = await _call_bridge(platform_bridge.get_case, case_id)
        except Exception as exc:
            return PaymentResult(status=PaymentStatus.unavailable, idempotency_key=key,
                                 error=f"could not load case, payment not attempted: {type(exc).__name__}")
        case_status = _case_status(case)
        if case_status != "approved":
            _safe_audit("system", "payment_adapter", "disburse_blocked_not_approved", f"case:{case_id}",
                        {"case_status": case_status, "amount": str(amt), "account_id": account_id})
            return PaymentResult(status=PaymentStatus.rejected_not_approved, idempotency_key=key,
                                 error=f"case status is '{case_status}', only 'approved' cases can be paid")

        # (b) an earlier attempt for this case?
        row = await _db(_db_get, case_id)
        if row is not None:
            if row.amount != amt or row.account_id != account_id:
                return PaymentResult(status=PaymentStatus.failed, idempotency_key=key,
                                     error="a payment request for this case exists with a different amount or account")
            if row.status == "success":
                return _from_row(row)
            # It may already have reached Raast: look it up BEFORE trying again.
            kind, result = await self._lookup_by_key(case_id, key)
            if kind != "not_found":
                return result
        else:
            # (c) record the intent BEFORE calling Raast
            row = await _db(_db_insert, case_id, key, amt, account_id)
            if row.status == "success":  # lost a creation race to a call that already paid
                return _from_row(row)
        await _db(_db_update, case_id, status="requested", bump_attempts=True, clear_error=True)

        # (d) ONE disburse call, never retried
        outcome = await self.http.request(
            "POST", "/mock/raast/disburse",
            json_body={"case_id": case_id, "amt": str(amt), "acct": account_id, "approval_ref": case_id},
            headers={"Idempotency-Key": key}, safe=False, case_id=case_id)

        if outcome.kind == "circuit_open":  # nothing was sent
            await _db(_db_update, case_id, last_error=outcome.error)
            return PaymentResult(status=PaymentStatus.unavailable, idempotency_key=key,
                                 latency_ms=outcome.duration_ms, error=f"{outcome.error}; payment not sent")

        if outcome.is_response and not outcome.is_success:  # 4xx: definitively not processed
            reason = f"Raast rejected the request (HTTP {outcome.status_code})"
            await _db(_db_update, case_id, status="failed", last_error=reason)
            return PaymentResult(status=PaymentStatus.failed, idempotency_key=key,
                                 latency_ms=outcome.duration_ms, error=reason)

        if outcome.is_success:
            txn = _parse_txn(outcome)
            if txn is not None:
                return await self._record_txn(case_id, key, txn, outcome.duration_ms)
            error = "Raast disburse response malformed"
        else:
            error = outcome.error or "unknown disburse outcome"

        # (e) timeout / 5xx / connection error / malformed: outcome UNKNOWN -> look it up
        await _db(_db_update, case_id, status="unknown", last_error=error)
        kind, result = await self._lookup_by_key(case_id, key)
        if kind == "found":
            return result
        # (f) no second disburse inside this call
        return PaymentResult(
            status=PaymentStatus.unavailable, idempotency_key=key, reconcile_required=True,
            latency_ms=outcome.duration_ms,
            error=f"{error}; outcome unknown, call reconcile_unknown or disburse again later (idempotent)")
