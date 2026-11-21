# OWNER: Member 3
# Creates Member 3's tables if they do not exist yet. Hackathon fallback for when Member 1's
# Alembic migration does not include them: safe to run any number of times (existing tables
# are left alone, nothing is dropped or altered).
#
#   cd backend && python -m app.integrations.create_tables
#
# Tables: mock_* (5), payment_requests, agent_runs, jobs, worker_heartbeat.
from typing import List, Optional

from sqlalchemy.engine import Engine

from app.agent.models import AGENT_MODELS
from app.integrations.mocks.models import MOCK_MODELS
from app.integrations.providers.models import PROVIDER_MODELS
from app.jobs.models import JOB_MODELS
from shared import db as shared_db

ALL_M3_MODELS = MOCK_MODELS + PROVIDER_MODELS + AGENT_MODELS + JOB_MODELS


def create_m3_tables(engine: Optional[Engine] = None) -> List[str]:
    """Create any missing M3 tables. Returns the table names."""
    target = engine if engine is not None else shared_db.engine
    tables = [m.__table__ for m in ALL_M3_MODELS]
    shared_db.Base.metadata.create_all(target, tables=tables, checkfirst=True)
    return [t.name for t in tables]


if __name__ == "__main__":
    print("ensured tables:", ", ".join(create_m3_tables()))
