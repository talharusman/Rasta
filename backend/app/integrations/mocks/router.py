# OWNER: Member 3
# One entry point for everything the mocks expose. Whoever owns backend/main.py
# plugs these in (we may not edit it):
#
#   from app.integrations.mocks.router import (
#       router as m3_mock_router, internal_router as m3_control_router,
#       admin_router as m3_admin_router)
#   app.include_router(m3_mock_router)
#   app.include_router(m3_control_router)
#   app.include_router(m3_admin_router)
from fastapi import APIRouter

from . import nadra, raast, sms
from .control import admin_router, internal_router

router = APIRouter(prefix="/mock")  # /mock/nadra/*, /mock/raast/*, /mock/sms/*
router.include_router(nadra.router)
router.include_router(raast.router)
router.include_router(sms.router)

__all__ = ["router", "internal_router", "admin_router"]
