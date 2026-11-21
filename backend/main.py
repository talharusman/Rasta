# OWNER: shared. Nobody edits this file without asking the team first.
# It creates the app and plugs in the three routers (platform, ai, mocks).
import importlib.util
import json
import uuid
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ai.routes import router as ai_router
from mocks.routes import router as mocks_router


def load_platform_router():
    # Python already has a built-in module called "platform", so a normal
    # "import platform.routes" would fail. We load our folder under the
    # name "rasta_platform" instead. (Inside backend/platform/ use
    # relative imports, e.g. "from .models import X".)
    folder = Path(__file__).parent / "platform"
    spec = importlib.util.spec_from_file_location(
        "rasta_platform",
        folder / "__init__.py",
        submodule_search_locations=[str(folder)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rasta_platform"] = module
    spec.loader.exec_module(module)
    from rasta_platform.routes import router
    return router


platform_router = load_platform_router()
from rasta_platform.services import Problem, settings
from app.integrations.mount import mount_m3

app = FastAPI(title="rasta (PROTOTYPE - not an official service)")


def cors_origins(raw: str) -> list[str]:
    configured = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
    return list(dict.fromkeys(["http://localhost:5173", "http://127.0.0.1:5173",
                              *(origin.strip() for origin in configured if origin.strip())]))


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


def error_response(request, status, code, message, retryable=False):
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}, "request_id": request_id},
        status_code=status, headers={"X-Request-ID": request_id},
    )


@app.exception_handler(Problem)
async def platform_error(request: Request, exc: Problem):
    return error_response(request, exc.status, exc.code, exc.message, exc.retryable)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    issue = exc.errors()[0]
    location = ".".join(str(part) for part in issue["loc"])
    return error_response(request, 422, "VALIDATION_ERROR", f"{location}: {issue['msg']}")


app.include_router(platform_router)
app.include_router(ai_router)
app.include_router(mocks_router)
mount_m3(app)


@app.get("/")
def root():
    return {"app": "rasta", "note": "PROTOTYPE - not an official service"}
