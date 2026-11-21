# OWNER: Member 3
# Mock NADRA / Raast / SMS services. PROTOTYPE ONLY: all data is fictional.
#
# Guard for `python -m app.integrations.mocks.fixtures` run from backend/:
# the team's folder backend/platform/ shadows Python's built-in "platform"
# module (SQLAlchemy needs the real one). Import the real one first, with
# backend/ temporarily off sys.path. A no-op when it is already loaded.
import sys as _sys
from pathlib import Path as _Path

if not hasattr(_sys.modules.get("platform"), "python_implementation"):
    _backend = _Path(__file__).resolve().parents[3]
    _saved = list(_sys.path)
    _sys.modules.pop("platform", None)
    _sys.path[:] = [p for p in _saved if _Path(p or ".").resolve() != _backend]
    try:
        import platform as _platform  # noqa: F401
    finally:
        _sys.path[:] = _saved
