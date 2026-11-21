# OWNER: Member 3
# Result models and provider Protocols (see M3_CONTEXT.md "Adapters").
# Adapters NEVER raise to callers: every failure becomes a status + error text.
# All provider methods are async (they do network I/O).
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field


class IdentityStatus(str, Enum):
    verified = "verified"
    mismatch = "mismatch"
    not_found = "not_found"
    duplicate = "duplicate"
    unavailable = "unavailable"
    malformed = "malformed"


class AccountStatus(str, Enum):
    matched = "matched"
    mismatched = "mismatched"
    not_found = "not_found"
    unavailable = "unavailable"


class PaymentStatus(str, Enum):
    success = "success"
    pending = "pending"
    failed = "failed"
    unavailable = "unavailable"
    rejected_not_approved = "rejected_not_approved"


class NotificationStatus(str, Enum):
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    unavailable = "unavailable"


class IdentityRecord(BaseModel):
    """Normalized registry record. `name` is passed on to Member 2 for matching."""

    mock_identity_id: str
    name: str
    father_name: Optional[str] = None
    dob: Optional[str] = None  # ISO date, None if the registry has none
    gender: Optional[str] = None
    district: Optional[str] = None
    rec_status: str = "ACTIVE"


class IdentityResult(BaseModel):
    status: IdentityStatus
    record: Optional[IdentityRecord] = None
    issues: List[str] = Field(default_factory=list)
    latency_ms: int = 0
    error: Optional[str] = None


class AccountResult(BaseModel):
    status: AccountStatus
    account_id: Optional[str] = None
    holder_name: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None


class PaymentResult(BaseModel):
    status: PaymentStatus
    transaction_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    # True when the outcome at the payment provider is not known yet; call
    # reconcile_unknown(case_id) (never a blind second payment).
    reconcile_required: bool = False
    # reconcile_unknown only: the provider was reached and has NO transaction for
    # this idempotency key, so it is safe to call disburse again with the same key.
    no_transaction_found: bool = False
    latency_ms: int = 0
    error: Optional[str] = None


class NotificationResult(BaseModel):
    status: NotificationStatus
    message_id: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None


@runtime_checkable
class IdentityProvider(Protocol):
    async def verify(
        self, mock_identity_id: str, name: str, dob: Optional[str] = None
    ) -> IdentityResult: ...

    async def get_record(self, mock_identity_id: str) -> IdentityResult: ...


@runtime_checkable
class PaymentProvider(Protocol):
    async def validate_account(self, account_id: str, beneficiary_name: str) -> AccountResult: ...

    async def disburse(
        self, case_id: str, amount: Union[Decimal, int, float, str], account_id: str
    ) -> PaymentResult: ...

    async def get_transaction(self, transaction_id: str) -> PaymentResult: ...

    async def reconcile_unknown(self, case_id: str) -> PaymentResult: ...


@runtime_checkable
class NotificationProvider(Protocol):
    async def send(self, recipient: str, message: str, case_id: str, *, idempotency_key: str | None = None) -> NotificationResult: ...

    async def status(self, message_id: str) -> NotificationResult: ...
