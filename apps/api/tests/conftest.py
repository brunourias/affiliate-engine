import os
from pathlib import Path
TEST_DB = Path(__file__).resolve().parents[3] / "data" / "affiliate_engine_v1a_test.db"
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
    # Campaign handoff intentionally binds a candidate to an assessment while
    # assessments already bind back to candidates. SQLite needs FK checks off
    # only while its test schema is rebuilt; production migrations retain both
    # constraints.
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(conn); Base.metadata.create_all(conn)
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    with SessionLocal() as db: db.add(AppSettings(id=1)); db.commit()
@pytest.fixture
def client():
    with TestClient(app) as c: yield c
