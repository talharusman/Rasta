# OWNER: Member 3
# One call plugs all of Member 3's routes into the app. backend/main.py needs just:
#
#     from app.integrations.mount import mount_m3
#     mount_m3(app)
#
# What it mounts:
#   /mock/nadra|raast|sms/*             fake external services (X-Mock-Api-Key)
#   /internal/mock-control              fixture switches        (X-Service-Key)
#   /api/v1/admin/mock-conditions       fixture switches        (admin)
#   /internal/agent/*                   case-processing agent   (X-Service-Key)
#   /internal/jobs, /internal/jobs/notifications, /api/v1/admin/jobs
#   /health, /ready                     liveness / readiness
# and the job worker (starts only when RUN_JOB_WORKER=true).
#
# Optional one-env-var deployment: M3_AUTO_SETUP=true creates any missing M3 tables and
# loads the fictional demo identities on startup (never wipes anything), so a fresh
# database works without running scripts. Leave it unset once Member 1's migration owns
# the tables.
import asyncio
import logging
import os
from typing import Dict

from fastapi import FastAPI

logger = logging.getLogger("m3.mount")


def setup_database() -> Dict[str, int]:
    """Create missing M3 tables and add the demo data. Idempotent and non-destructive."""
    from app.integrations.create_tables import create_m3_tables
    from app.integrations.mocks.fixtures import seed_mocks

    create_m3_tables()
    return seed_mocks(reset=False)


async def _bootstrap() -> None:
    if os.getenv("M3_AUTO_SETUP", "").strip().lower() not in ("1", "true", "yes"):
        return
    try:
        counts = await asyncio.to_thread(setup_database)
        logger.info("M3 auto-setup done: %s", counts)
    except Exception:
        # Do not stop the whole app from booting; /ready will show the database problem.
        logger.exception("M3 auto-setup failed")


def mount_m3(app: FastAPI) -> FastAPI:
    if getattr(app.state, "m3_mounted", False):
        return app  # calling it twice is harmless
    from app.agent.router import router as agent_router
    from app.integrations.mocks.router import admin_router, internal_router
    from app.integrations.mocks.router import router as mock_router
    from app.jobs.router import router as jobs_router

    app.add_event_handler("startup", _bootstrap)  # registered first: tables exist before the worker runs
    for router in (mock_router, internal_router, admin_router, agent_router, jobs_router):
        app.include_router(router)
    app.state.m3_mounted = True
    return app
