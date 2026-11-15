"""Small helpers shared by legacy, SQLite-only migrations."""


def using_sqlite_database() -> bool | None:
    """Return whether the active SQLAlchemy engine is SQLite.

    ``None`` means that no application engine is available (for example when
    a legacy migration is run as a standalone script).  Callers may retain
    their historical direct-SQLite fallback in that case.
    """

    try:
        from musicround import db

        return db.engine.dialect.name.lower() == "sqlite"
    except Exception:
        return None
