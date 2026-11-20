# OWNER: Member 1 (platform: login, roles, cases, rules, consent, audit log)
from fastapi import APIRouter

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/health")
def health():
    return {"service": "platform", "status": "ok"}
