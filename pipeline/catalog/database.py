from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from .models import Base
from pipeline.config import get_settings


def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
