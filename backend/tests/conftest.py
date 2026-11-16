import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_ARTIFACTS = tempfile.mkdtemp(prefix='ordinal-dp-test-')
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///' + os.path.join(tempfile.mkdtemp(prefix='ordinal-dp-db-'), 'test.db')
os.environ['ARTIFACTS_DIR'] = _ARTIFACTS
os.environ['SEED_DEMO'] = 'false'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6399/0'

from src.config.database import Base, Session, engine  # noqa: E402
import src.models  # noqa: E402,F401


@pytest.fixture(scope='session')
def app_module():
    from src.main import app
    Base.metadata.create_all(engine)
    return app


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as session:
        yield session


@pytest.fixture()
def client(app_module, db):
    return TestClient(app_module, raise_server_exceptions=False)


@pytest.fixture()
def seeded(db):
    from scripts.seed_demo import seed
    seed()
    return db
