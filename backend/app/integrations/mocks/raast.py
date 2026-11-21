# OWNER: Member 3
# Mock Raast. Native format: {"txnRef","stat","amt","acct","rsnCd"}.
# stat: ACSC (settled) | PDNG (pending) | RJCT (rejected).
import re
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.db import get_db

from .control import MockRoute, MockServiceError, make_guard
from .models import MockAccount, MockTransaction

router = APIRouter(prefix="/raast", tags=["mock-raast"], route_class=MockRoute)


def _rjct(reason: str, txn_ref=None, acct=None, amt=None) -> Dict[str, Any]:
    return {"txnRef": txn_ref, "stat": "RJCT", "amt": amt, "acct": acct, "rsnCd": reason}


def _error(status: int, reason: str) -> Dict[str, Any]:
    return _rjct(reason)


guard = make_guard("raast", "RAAST_MOCK_KEY", _error, "raast_outage", None)


class ValidateRequest(BaseModel):
    acct: str
    beneficiary_nm: str


class DisburseRequest(BaseModel):
    case_id: str
    amt: Decimal = Field(gt=0)
    acct: str
    approval_ref: Optional[str] = None


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().casefold())


def _txn_body(t: MockTransaction) -> Dict[str, Any]:
    return {
        "txnRef": t.txn_ref,
        "stat": t.status,
        "amt": float(t.amount),
        "acct": t.account_id,
        "rsnCd": t.rsn_cd,
    }


def _same_request(t: MockTransaction, body: DisburseRequest, amount: Decimal) -> bool:
    return (
        t.case_id == body.case_id
        and t.account_id == body.acct
        and Decimal(t.amount) == amount
    )


def _by_key(db: Session, key: str) -> Optional[MockTransaction]:
    return db.execute(
        select(MockTransaction).where(MockTransaction.idempotency_key == key)
    ).scalar_one_or_none()


@router.post("/account-validate")
def account_validate(
    body: ValidateRequest,
    _cond=Depends(guard),
    db: Session = Depends(get_db),
):
    acct = db.get(MockAccount, body.acct)
    if acct is None:
        return {"acct": body.acct, "holder_nm": None, "stat": "NOTFOUND"}
    match = _norm(acct.holder_nm) == _norm(body.beneficiary_nm)
    return {"acct": acct.acct, "holder_nm": acct.holder_nm, "stat": "MATCH" if match else "NOMATCH"}


@router.post("/disburse")
def disburse(
    body: DisburseRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    _cond=Depends(guard),
    db: Session = Depends(get_db),
):
    if not idempotency_key or not idempotency_key.strip():
        raise MockServiceError(400, _rjct("MISSING_IDEMPOTENCY_KEY"))
    if not body.approval_ref or not body.approval_ref.strip():
        raise MockServiceError(400, _rjct("MISSING_APPROVAL_REF", acct=body.acct))
    amount = body.amt.quantize(Decimal("0.01"))

    def replay_or_conflict(existing: MockTransaction):
        if _same_request(existing, body, amount):
            return JSONResponse(_txn_body(existing))  # the ORIGINAL, unchanged
        return JSONResponse(
            _rjct("IDEMPOTENCY_CONFLICT", existing.txn_ref, existing.account_id, float(existing.amount)),
            status_code=409,
        )

    existing = _by_key(db, idempotency_key)
    if existing is not None:
        return replay_or_conflict(existing)

    if db.get(MockAccount, body.acct) is None:
        return JSONResponse(_rjct("ACCOUNT_NOT_FOUND", acct=body.acct, amt=float(amount)), status_code=422)

    txn = MockTransaction(
        txn_ref="RAAST-" + uuid.uuid4().hex[:12].upper(),
        idempotency_key=idempotency_key,
        case_id=body.case_id,
        amount=amount,
        account_id=body.acct,
        approval_ref=body.approval_ref,
        status="ACSC",
        rsn_cd=None,
    )
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same key won the UNIQUE constraint.
        db.rollback()
        existing = _by_key(db, idempotency_key)
        if existing is None:
            raise
        return replay_or_conflict(existing)
    return _txn_body(txn)


@router.get("/transactions/{txn_ref}")
def get_transaction(txn_ref: str, _cond=Depends(guard), db: Session = Depends(get_db)):
    txn = db.execute(
        select(MockTransaction).where(MockTransaction.txn_ref == txn_ref)
    ).scalar_one_or_none()
    if txn is None:
        return JSONResponse(_rjct("TXN_NOT_FOUND", txn_ref=txn_ref), status_code=404)
    return _txn_body(txn)


@router.get("/transactions")
def find_transaction(
    idempotency_key: str,
    _cond=Depends(guard),
    db: Session = Depends(get_db),
):
    """Lookup after a timeout: did the payment go through under this key?"""
    txn = _by_key(db, idempotency_key)
    if txn is None:
        return JSONResponse(_rjct("TXN_NOT_FOUND"), status_code=404)
    return _txn_body(txn)
