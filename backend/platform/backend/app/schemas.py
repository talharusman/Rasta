from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
class Refresh(Input):
    refresh_token: str = Field(min_length=1)
class ClaimData(Input):
    name: str = Field(min_length=1, max_length=120)
    mock_identity_id: str = Field(pattern=r'^MOCK-', max_length=100)
    monthly_income: int = Field(ge=0)
    household_size: int = Field(ge=1, le=100)
    payment_account: str = Field(pattern=r'^MOCK-', max_length=100)
class CreateCase(Input):
    citizen_id: UUID
    claim_type: Literal['relief_payment'] = 'relief_payment'
    idempotency_key: str = Field(min_length=1, max_length=200)
    data: ClaimData
class Revision(Input):
    expected_revision: int = Field(ge=1)
class EditCase(Revision):
    data: ClaimData
class Assign(Revision):
    officer_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
class Review(Revision):
    action: Literal['approve', 'reject', 'ask_proof']
    notes: str = Field(min_length=1, max_length=2000)
    required_documents: list[Literal['identity_proof', 'income_proof']] = Field(default_factory=list)
    override_reason: str | None = Field(default=None, max_length=2000)
class Close(Revision):
    notes: str = Field(min_length=1, max_length=2000)
class RoleEdit(Input):
    role: Literal['citizen','helper','officer','admin','auditor']
    reason: str = Field(min_length=1, max_length=2000)
class Grant(Input):
    citizen_id: UUID
    grantee_id: UUID | None = None
    purpose: Literal['processing'] | None = None
    scope: Literal['case:read','case:write','document:upload','case:submit','scam:check','identity:verify','ai:process']
    @model_validator(mode='after')
    def target(self):
        processing = self.scope in ('identity:verify','ai:process')
        if processing != (self.purpose == 'processing') or processing == (self.grantee_id is not None):
            raise ValueError('Processing scopes require purpose only; sharing scopes require grantee only')
        return self
class Policy(Input):
    max_monthly_income: int = Field(ge=0)
    required_documents: list[Literal['identity_proof','income_proof']]
    clear_confidence_min: float = Field(ge=0, le=1)
    proof_confidence_min: float = Field(ge=0, le=1)
    critical_flags: list[str]
    @model_validator(mode='after')
    def thresholds(self):
        if self.proof_confidence_min > self.clear_confidence_min:
            raise ValueError('Invalid threshold order')
        return self
class Publish(Input):
    expected_version: int = Field(ge=1)
    conditions_json: Policy
    reason: str = Field(min_length=1, max_length=2000)
class CaseRef(Input):
    case_id: UUID
class Scam(Input):
    citizen_id: UUID
    text: str = Field(min_length=1, max_length=5000)
class Result(Input):
    route: Literal['cleared','needs_proof','human_review']
    confidence: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    flags: list[str]
    rule_version: int
    model_version: str = Field(min_length=1, max_length=100)
    user_explanation: str = Field(min_length=1, max_length=2000)
    auditor_trace: dict
    identity_verified: bool
