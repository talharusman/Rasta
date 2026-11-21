# OWNER: Member 2
# Read-only access to data owned by other members. The AI service NEVER writes here.
#   - platform tables (Member 1): cases, citizens, rules, case_documents
#   - mock registry tables (Member 3): mock_identity_records, mock_accounts
# Every function returns a Source(ok, rows, origin, error) and never raises, so a
# caller can decide honestly what to do when a source is missing.
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

logger = logging.getLogger("m2.ai.data")

DB_RETRY_AFTER = 30.0   # seconds to skip the database after a connection failure
DB_CONNECT_TIMEOUT = 1.0  # seconds per address for the reachability probe
_db_down_until = 0.0


@dataclass
class Source:
    ok: bool
    rows: List[Dict[str, Any]] = field(default_factory=list)
    origin: str = ""
    error: Optional[str] = None
    unreachable: bool = False  # True only when the database itself could not be reached


def reset_cache() -> None:
    global _db_down_until
    _db_down_until = 0.0


def _query(sql: str, params: Optional[Dict[str, Any]] = None, origin: str = "database") -> Source:
    global _db_down_until
    if time.monotonic() < _db_down_until:
        return Source(False, origin=origin, error="database unreachable (cached)", unreachable=True)
    from shared import db as shared_db  # looked up at call time so tests can swap it

    try:
        session = shared_db.SessionLocal()
    except Exception as exc:  # pragma: no cover - misconfiguration
        return Source(False, origin=origin, error=f"no database session: {type(exc).__name__}", unreachable=True)
    try:
        try:
            _probe(session)
            session.connection()
        except (DBAPIError, SQLAlchemyError, OSError) as exc:
            _db_down_until = time.monotonic() + DB_RETRY_AFTER
            logger.warning("database unreachable: %s", type(exc).__name__)
            return Source(False, origin=origin, error=f"database unreachable: {type(exc).__name__}", unreachable=True)
        try:
            rows = [dict(r) for r in session.execute(text(sql), params or {}).mappings().all()]
        except (DBAPIError, SQLAlchemyError) as exc:  # e.g. table not created in this database
            return Source(False, origin=origin, error=f"query failed: {type(exc).__name__}")
        return Source(True, rows=rows, origin=origin)
    finally:
        session.close()


def _probe(session) -> None:
    """Fail fast if a network database is not listening. The shared engine has no
    connect timeout, and psycopg can wait forever on Windows when Postgres is down,
    which would blow the caller's 10 s budget. Raises OSError when unreachable."""
    try:
        url = session.get_bind().url
    except Exception:
        return
    if url.get_backend_name() in ("sqlite",) or not url.host:
        return
    default_port = {"postgresql": 5432, "mysql": 3306}.get(url.get_backend_name(), 5432)
    with socket.create_connection((url.host, url.port or default_port), timeout=DB_CONNECT_TIMEOUT):
        pass


def _json(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value if value is not None else {}


# ---------------------------------------------------------------------------
# Member 3's synthetic identity registry
# ---------------------------------------------------------------------------
def registry_records() -> Source:
    """All synthetic identity records: {mock_identity_id, name, father_name, dob, status, account_id}."""
    src = _query(
        "SELECT r.cit_id, r.full_nm, r.father_nm, r.birth_dt, r.rec_status, a.acct "
        "FROM mock_identity_records r LEFT JOIN mock_accounts a ON a.cit_id = r.cit_id",
        origin="mock_registry_db")
    if src.ok and src.rows:
        return Source(True, origin=src.origin, rows=[
            {"mock_identity_id": r["cit_id"], "name": r["full_nm"], "father_name": r["father_nm"],
             "dob": str(r["birth_dt"]) if r["birth_dt"] else None, "status": r["rec_status"],
             "account_id": r["acct"]} for r in src.rows])
    # The registry IS synthetic fixture data, so the fixture list is a faithful fallback.
    try:
        from app.integrations.mocks.fixtures import all_rows
    except Exception as exc:  # pragma: no cover
        return Source(False, origin="mock_registry_fixtures", error=f"fixtures unavailable: {exc}")
    return Source(True, origin="mock_registry_fixtures", rows=[
        {"mock_identity_id": cit, "name": name, "father_name": father, "dob": dob, "status": status,
         "account_id": acct} for cit, name, father, dob, _g, _d, status, acct, _h in all_rows()])


def registry_record(mock_identity_id: str) -> Optional[Dict[str, Any]]:
    src = registry_records()
    for row in src.rows:
        if row["mock_identity_id"] == mock_identity_id:
            return row
    return None


# ---------------------------------------------------------------------------
# Member 1's platform tables
# ---------------------------------------------------------------------------
INACTIVE_CASE_STATUSES = ("draft", "rejected", "closed")


def platform_claims(tenant_id: Optional[str] = None) -> Source:
    """Open claims from the platform: {case_id, status, citizen_id, mock_identity_id, name, dob, account_id}."""
    sql = ("SELECT c.id, c.status, c.data, c.citizen_id, c.tenant_id, c.claim_type, z.mock_identity_id AS citizen_identity "
           "FROM cases c LEFT JOIN citizens z ON z.id = c.citizen_id "
           "WHERE c.status NOT IN ('draft', 'rejected', 'closed')")
    params: Dict[str, Any] = {}
    if tenant_id:
        sql += " AND CAST(c.tenant_id AS VARCHAR) = :tenant"
        params["tenant"] = str(tenant_id)
    src = _query(sql, params, origin="platform_cases")
    if not src.ok:
        return src
    rows = []
    for r in src.rows:
        data = _json(r.get("data")) or {}
        rows.append({
            "case_id": str(r["id"]), "status": r["status"], "claim_type": r["claim_type"], "citizen_id": str(r["citizen_id"]) if r["citizen_id"] else None,
            "mock_identity_id": data.get("mock_identity_id") or r.get("citizen_identity"),
            "name": data.get("name") or data.get("applicant_name"), "dob": data.get("dob"),
            "account_id": data.get("payment_account") or data.get("account_id"),
        })
    return Source(True, rows=rows, origin=src.origin)


def rule(version: Any = None, tenant_id: Optional[str] = None) -> Source:
    """The rule row for `version` (any state, so old decisions keep their rules), else the active one."""
    sql = "SELECT version, conditions_json, active, rule_name FROM rules WHERE 1=1"
    params: Dict[str, Any] = {}
    numeric = _version_number(version)
    if numeric is not None:
        sql += " AND version = :v"
        params["v"] = numeric
    else:
        sql += " AND active = :a"
        params["a"] = True
    if tenant_id:
        sql += " AND CAST(tenant_id AS VARCHAR) = :tenant"
        params["tenant"] = str(tenant_id)
    src = _query(sql + " ORDER BY version DESC", params, origin="platform_rules")
    if src.ok:
        src.rows = [{**r, "conditions_json": _json(r["conditions_json"])} for r in src.rows[:1]]
    return src


def document_file(document_id: str, *, case_id: Any = None, tenant_id: Optional[str] = None) -> Source:
    sql = "SELECT file_path, content_type, type FROM case_documents WHERE CAST(id AS VARCHAR) = :id"
    params = {"id": str(document_id)}
    if tenant_id is not None:
        sql += " AND CAST(case_id AS VARCHAR) = :case_id AND CAST(tenant_id AS VARCHAR) = :tenant"
        params.update(case_id=str(case_id), tenant=tenant_id)
    return _query(sql, params, origin="platform_documents")


def _version_number(version: Any) -> Optional[int]:
    """2, "2", "v2", "rules-v2" -> 2. Anything else -> None."""
    if isinstance(version, bool) or version is None:
        return None
    if isinstance(version, int):
        return version
    m = re.fullmatch(r"(?:rules?[-_ ]?)?v?(\d+)", str(version).strip().lower())
    return int(m.group(1)) if m else None
