# OWNER: Member 2
# Request bodies for the AI routes. Two callers use some routes with different field
# names (Member 1's platform and Member 3's agent), so both spellings are accepted.
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CaseId = Optional[Union[str, int]]


class _In(BaseModel):
    model_config = ConfigDict(extra="allow")  # unknown fields are ignored, never an error


class ScamIn(_In):
    case_id: CaseId = None
    text: Optional[str] = Field(None, max_length=5000)      # Member 1
    message: Optional[str] = Field(None, max_length=5000)   # Member 3

    @model_validator(mode="after")
    def need_text(self):
        if not (self.text or self.message or "").strip():
            raise ValueError("'text' (or 'message') must be a non-empty string")
        return self

    @property
    def content(self) -> str:
        return (self.text or self.message or "").strip()


class MatchIn(_In):
    case_id: CaseId = None
    input_name: Optional[str] = Field(None, max_length=200)       # Member 3
    registry_name: Optional[str] = Field(None, max_length=200)    # Member 3
    submitted_name: Optional[str] = Field(None, max_length=200)   # todo spec
    mock_identity_id: Optional[str] = Field(None, max_length=100)  # todo spec: look the name up

    @model_validator(mode="after")
    def need_names(self):
        if self.input_name is None and self.submitted_name is None:
            raise ValueError("'input_name' (or 'submitted_name') is required")
        if self.registry_name is None and not self.mock_identity_id:
            raise ValueError("'registry_name' or 'mock_identity_id' is required")
        return self


class DuplicatesIn(_In):
    case_id: CaseId = None
    citizen_id: Optional[str] = None
    mock_identity_id: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)
    dob: Optional[str] = Field(None, max_length=20)
    account_id: Optional[str] = Field(None, max_length=100)
    claim_type: Optional[str] = Field(None, max_length=40)
    tenant_id: Optional[str] = None

    @model_validator(mode="after")
    def need_key(self):
        if not (self.mock_identity_id or self.citizen_id or self.name or self.account_id):
            raise ValueError("send at least one of mock_identity_id, citizen_id, name, account_id")
        return self


class EvaluateInput(_In):
    identity_verified: Optional[bool] = None
    name_match_score: Optional[float] = Field(None, ge=0, le=1)
    document_quality: Optional[float] = Field(None, ge=0, le=1)
    duplicate_flag: Optional[bool] = None
    scam_flag: Optional[bool] = None
    monthly_income: Optional[float] = Field(None, ge=0)
    household_size: Optional[int] = Field(None, ge=1, le=100)


class EvaluateIn(_In):
    case_id: CaseId = None
    rule_version: Optional[Union[str, int]] = None
    input: EvaluateInput = Field(default_factory=EvaluateInput)
    rules: Optional[Dict[str, Any]] = None   # optional: thresholds sent by the caller
    flags: List[str] = Field(default_factory=list)  # optional: flags already raised upstream
    tenant_id: Optional[str] = None


class ExplainIn(_In):
    case_id: CaseId = None
    route: Literal["cleared", "needs_proof", "human_review"]
    flags: List[str] = Field(default_factory=list)
    rule_version: Optional[Union[str, int]] = None
    language: Literal["en", "ur"] = "en"


class DocumentRef(_In):
    id: Optional[str] = None
    type: Optional[str] = None
    quality: Optional[float] = Field(None, ge=0, le=1)
    file_path: Optional[str] = None
    content_base64: Optional[str] = None
    text: Optional[str] = Field(None, max_length=20000)


class ExtractIn(_In):
    case_id: CaseId = None
    tenant_id: Optional[str] = None
    document: Optional[DocumentRef] = None
    document_type: Optional[str] = None
    content_base64: Optional[str] = None
    text: Optional[str] = Field(None, max_length=20000)
    expected: Optional[Dict[str, Any]] = None   # form values to compare with
