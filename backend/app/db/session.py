# backend/app/db/session.py
"""
Database session management - thin wrapper around core/database.py.
"""

# ✅ Import from core.database - single source of truth
from app.core.database import (
    engine,
    SessionLocal,
    ScopedSession,
    get_db,
    init_schema,
    check_database_connection,
)

__all__ = [
    "engine",
    "SessionLocal", 
    "ScopedSession",
    "get_db",
    "init_schema",
    "check_database_connection",
]