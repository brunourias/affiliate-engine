import os, tempfile
from pathlib import Path
TEST_DB = Path(tempfile.gettempdir()) / "affiliate_engine_v1a_test.db"
if TEST_DB.exists(): TEST_DB.unlink()
os.environ["AFFILIATE_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
import pytest
from fastapi.testclient import TestClient
from apps.api.app.db.base import Base
from apps.api.app.db.session import engine, SessionLocal
from apps.api.app.db.models import AppSettings
from apps.api.app.main import app
@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as db: db.add(AppSettings(id=1)); db.commit()
@pytest.fixture
def client():
    with TestClient(app) as c: yield c
