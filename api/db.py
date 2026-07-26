"""SQLAlchemy 2.x engine, session factory, and declarative Base."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from api.config import DATABASE_URL, DB_PATH

# Ensure the parent directory (data/) exists before SQLite tries to open the file.
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    # check_same_thread=False is required because FastAPI serves requests from a
    # threadpool and a connection may be touched by a different thread than opened it.
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a session, always closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
