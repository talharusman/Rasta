import importlib.util
from pathlib import Path
import sys
import platform  # Load the standard library module before exposing the backend path.

from alembic import context

backend = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(backend))
folder = backend / 'platform'
spec = importlib.util.spec_from_file_location(
    'rasta_platform', folder / '__init__.py', submodule_search_locations=[str(folder)],
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from rasta_platform import models
from app.agent.models import AGENT_MODELS
from app.integrations.mocks.models import MOCK_MODELS
from app.integrations.providers.models import PROVIDER_MODELS
from app.jobs.models import JOB_MODELS
from shared import db

if context.is_offline_mode():
    context.configure(url=db.engine.url, target_metadata=models.Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=models.Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
