# OWNER: shared. Change only after telling the team.
# Database connection. Every table class should inherit from Base.
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from shared.config import DATABASE_URL

# The engine does not connect until you really use it,
# so the app starts even if Postgres is not running yet.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    """Use in a route: db: Session = Depends(get_db)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
