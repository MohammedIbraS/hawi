"""
Re-exports database session management from the pipeline catalog.
Backend routes import from here so they don't need to know the pipeline structure.
"""
from pipeline.catalog.database import get_session, init_db, get_engine

__all__ = ["get_session", "init_db", "get_engine"]
