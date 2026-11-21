from alembic import context
from sqlalchemy import create_engine
from app.config import settings
from app.models import Base

if not settings.database_url:
    raise RuntimeError('Configure DATABASE_URL before running migrations')
if context.is_offline_mode():
    context.configure(url=settings.database_url,target_metadata=Base.metadata,literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    with create_engine(settings.database_url).connect() as connection:
        context.configure(connection=connection,target_metadata=Base.metadata)
        with context.begin_transaction(): context.run_migrations()
