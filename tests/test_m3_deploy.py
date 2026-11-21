# OWNER: Member 3. Deployment readiness: mounting, bootstrap, table creation, container files.
# Run from the repo root:  python -m pytest tests/test_m3_deploy.py -v
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.integrations.create_tables import ALL_M3_MODELS, create_m3_tables  # noqa: E402
from app.integrations.mocks.models import MockIdentityRecord  # noqa: E402
from app.integrations.mount import mount_m3  # noqa: E402
from shared import db as shared_db  # noqa: E402

M3_TABLES = {
    "mock_identity_records", "mock_accounts", "mock_transactions", "mock_sms_messages", "mock_fixture_state",
    "payment_requests", "agent_runs", "jobs", "worker_heartbeat",
}
M3_PATHS = [
    "/mock/nadra/verify", "/mock/nadra/records/{cit_id}", "/mock/raast/account-validate",
    "/mock/raast/disburse", "/mock/raast/transactions/{txn_ref}", "/mock/raast/transactions",
    "/mock/sms/send", "/mock/sms/messages/{msg_id}",
    "/internal/mock-control", "/api/v1/admin/mock-conditions",
    "/internal/agent/process-case", "/internal/agent/runs/{run_id}",
    "/internal/jobs/notifications", "/internal/jobs", "/api/v1/admin/jobs", "/health", "/ready",
]


def paths(app):
    return [getattr(r, "path", None) for r in app.routes]


@pytest.fixture()
def empty_db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'deploy.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(shared_db, "engine", engine)
    monkeypatch.setattr(shared_db, "SessionLocal", sessionmaker(bind=engine, autoflush=False))
    for var in ("RUN_JOB_WORKER", "M3_AUTO_SETUP"):
        monkeypatch.delenv(var, raising=False)
    yield engine
    engine.dispose()


def test_all_nine_m3_tables_are_known():
    assert {m.__table__.name for m in ALL_M3_MODELS} == M3_TABLES


def test_mount_into_the_real_main_app_adds_every_route_and_keeps_the_starter_ones():
    from main import app  # backend/main.py, untouched

    before = paths(app)
    assert "/api/mock/health" in before  # the starter route the judges' curl uses
    mount_m3(app)
    after = paths(app)
    for expected in M3_PATHS:
        assert expected in after, expected
    mount_m3(app)  # twice is harmless
    assert paths(app) == after
    for p in ("/api/mock/health", "/health", "/"):
        assert TestClient(app).get(p).status_code == 200


def test_create_tables_is_idempotent_and_non_destructive(empty_db):
    assert set(create_m3_tables(empty_db)) == M3_TABLES
    assert set(inspect(empty_db).get_table_names()) == M3_TABLES
    with sessionmaker(bind=empty_db)() as s:
        s.add(MockIdentityRecord(cit_id="MOCK-KEEP", full_nm="Keep Me", rec_status="ACTIVE"))
        s.commit()
    create_m3_tables(empty_db)  # again
    with sessionmaker(bind=empty_db)() as s:
        assert s.scalar(select(func.count()).select_from(MockIdentityRecord)) == 1


def test_auto_setup_creates_tables_and_seeds_on_startup(empty_db, monkeypatch):
    monkeypatch.setenv("M3_AUTO_SETUP", "true")
    app = mount_m3(FastAPI())
    with TestClient(app) as client:
        assert set(inspect(empty_db).get_table_names()) == M3_TABLES
        with sessionmaker(bind=empty_db)() as s:
            assert s.scalar(select(func.count()).select_from(MockIdentityRecord)) == 29
        assert client.get("/ready").json()["status"] == "ready"
    with TestClient(mount_m3(FastAPI())):  # a second boot neither fails nor duplicates
        with sessionmaker(bind=empty_db)() as s:
            assert s.scalar(select(func.count()).select_from(MockIdentityRecord)) == 29


def test_auto_setup_is_off_by_default(empty_db):
    with TestClient(mount_m3(FastAPI())):
        assert inspect(empty_db).get_table_names() == []


def test_scripts_run_from_backend_despite_the_platform_folder(tmp_path):
    """The real hazard: backend/platform/ shadows Python's `platform` for `python -m ...`
    run inside backend/. The documented commands must still work."""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}"}

    def run(*args):
        return subprocess.run([sys.executable, *args], cwd=BACKEND, env=env, capture_output=True,
                              text=True, timeout=120)

    created = run("-m", "app.integrations.create_tables")
    assert created.returncode == 0, created.stderr
    assert "jobs" in created.stdout and "payment_requests" in created.stdout
    seeded = run("-m", "app.integrations.mocks.fixtures", "--reset")
    assert seeded.returncode == 0, seeded.stderr
    assert "'identities': 29" in seeded.stdout


# --- container / platform files --------------------------------------------------------
def test_dockerfile_is_correct():
    text = (ROOT / "Dockerfile").read_text()
    assert "uvicorn main:app" in text and "${PORT" in text and "--host 0.0.0.0" in text
    cmd = next(line for line in text.splitlines() if line.startswith("CMD"))
    assert "python -m" not in cmd  # `python -m uvicorn` would hit the platform/ shadowing
    assert "WORKDIR /app/backend" in text
    for line in text.splitlines():  # every file the image copies for pip must exist
        if line.startswith("COPY backend/") and line.rstrip().endswith("requirements.txt"):
            assert (ROOT / line.split()[1]).exists(), line
    assert "USER appuser" in text  # not root


def test_dockerignore_keeps_secrets_and_junk_out():
    lines = (ROOT / ".dockerignore").read_text().split()
    for must in (".env", ".git", "backend/venv", "frontend", "node_modules"):
        assert must in lines, must


def test_procfile_runtime_and_railway_config():
    assert "uvicorn main:app" in (ROOT / "Procfile").read_text() and "$PORT" in (ROOT / "Procfile").read_text()
    assert (ROOT / "runtime.txt").read_text().strip().startswith("python-3.12")
    cfg = json.loads((ROOT / "railway.json").read_text())
    assert cfg["build"]["builder"] == "DOCKERFILE" and cfg["deploy"]["healthcheckPath"].startswith("/")


def test_no_secret_is_committed_in_deployment_files():
    for name in ("Dockerfile", "Procfile", "railway.json", "runtime.txt", ".dockerignore"):
        text = (ROOT / name).read_text().lower()
        for needle in ("supabase", "api_key=", "password", "secret="):
            assert needle not in text, f"{needle} in {name}"
