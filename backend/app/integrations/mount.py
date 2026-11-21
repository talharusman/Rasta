"""Register the platform-backed Member 3 routes on the shared FastAPI app."""
from fastapi import APIRouter, Depends, FastAPI

from app.agent import platform_bridge
from app.agent.router import router as agent_router
from app.jobs.router import router as jobs_router
from .mocks.router import admin_router, internal_router, router as mock_router


def mount_m3(app: FastAPI):
    from rasta_platform import integration
    from rasta_platform.services import Actor, fail, settings

    platform_bridge.configure(integration)
    app.dependency_overrides[platform_bridge.require_admin] = integration.require_admin

    def demo_admin(user: Actor):
        admin = integration.require_admin(user)
        if user.tenant_id != settings.demo_tenant_id:
            fail(403, 'FORBIDDEN')
        return admin

    for router in (mock_router, internal_router, agent_router, jobs_router):
        app.include_router(router)

    # Mock controls share one fixture set; job admin remains scoped to each tenant.
    demo_router = APIRouter(dependencies=[Depends(demo_admin)])
    demo_router.include_router(admin_router)
    app.include_router(demo_router)
