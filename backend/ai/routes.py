# OWNER: Member 2 (decisions, scam check, OCR, name matching, explanations)
from fastapi import APIRouter

from shared.schemas import Decision, Route

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/health")
def health():
    return {"service": "ai", "status": "ok"}


@router.post("/decide", response_model=Decision)
def decide():
    # FAKE for now: always sends the case to a human.
    return Decision(route=Route.HUMAN, reason="Fake decision: always HUMAN", confidence=0.0)
