# OWNER: shared. Change only after telling the team.
# Pydantic models used by more than one member.
from enum import Enum
from typing import List

from pydantic import BaseModel


class Role(str, Enum):
    CITIZEN = "CITIZEN"
    HELPER = "HELPER"
    OFFICER = "OFFICER"
    ADMIN = "ADMIN"
    AUDITOR = "AUDITOR"


class CaseState(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    CLEARED = "cleared"
    NEEDS_PROOF = "needs_proof"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"


class Route(str, Enum):
    AUTO = "AUTO"            # approve automatically
    ASK_MORE = "ASK_MORE"    # ask the citizen for more information
    HUMAN = "HUMAN"          # send to a human officer


class Decision(BaseModel):
    route: Route
    reason: str
    confidence: float = 0.0  # 0.0 to 1.0


class ScamResult(BaseModel):
    is_scam: bool
    score: float = 0.0       # 0.0 to 1.0
    reasons: List[str] = []
