# OWNER: shared. Nobody edits this file without asking the team first.
# It creates the app and plugs in the three routers (platform, ai, mocks).
import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI
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


app = FastAPI(title="rasta (PROTOTYPE - not an official service)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(load_platform_router())
app.include_router(ai_router)
app.include_router(mocks_router)


@app.get("/")
def root():
    return {"app": "rasta", "note": "PROTOTYPE - not an official service"}
