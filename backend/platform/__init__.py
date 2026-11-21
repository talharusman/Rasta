# OWNER: Member 1 (Platform Package)
import sys
import importlib.util
import importlib.machinery

# If third-party libraries (e.g. pydantic) import 'platform' while backend/ is on sys.path,
# re-export the standard library platform module attributes to avoid breaking stdlib lookups.
try:
    for _p in sys.path:
        if _p and 'backend' not in _p:
            _spec = importlib.machinery.PathFinder.find_spec('platform', [_p])
            if _spec and _spec.origin and 'backend' not in _spec.origin:
                _stdlib_mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_stdlib_mod)
                for _k, _v in _stdlib_mod.__dict__.items():
                    if not _k.startswith('__'):
                        globals()[_k] = _v
                break
except Exception:
    pass
