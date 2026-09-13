from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from apps.api.app.core.config import settings
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        cursor = connection.cursor(); cursor.execute("PRAGMA foreign_keys=ON"); cursor.execute("PRAGMA journal_mode=WAL"); cursor.execute("PRAGMA busy_timeout=5000"); cursor.close()
SessionLocal = sessionmaker(engine, expire_on_commit=False)
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
