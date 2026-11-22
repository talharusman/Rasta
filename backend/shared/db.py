# OWNER: shared. Change only after telling the team.
# Database connection. Every table class should inherit from Base.
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from shared.config import DATABASE_URL

# Supabase's session pooler allows only ~15 connections for the WHOLE project,
# shared by every teammate and every running copy of the app. SQLAlchemy's
# default pool (5 + 10 overflow = 15) can use all of them by itself, which makes
# everyone else fail with "EMAXCONNSESSION max clients reached". Keep the pool
# small; raise it with DB_POOL_SIZE / DB_MAX_OVERFLOW only on a dedicated database.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "3"))
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "2"))

# The engine does not connect until you really use it,
# so the app starts even if Postgres is not running yet.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_recycle=300,   # hand idle connections back instead of holding them forever
    pool_timeout=30,    # wait for a free connection rather than opening more
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    """Use in a route: db: Session = Depends(get_db)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
