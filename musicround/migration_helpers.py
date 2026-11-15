"""Small helpers shared by legacy, SQLite-only migrations."""


def using_sqlite_database() -> bool | None:
    """Return whether the active SQLAlchemy engine is SQLite.

    ``None`` means that no application engine is available (for example when
    a legacy migration is run as a standalone script).  Callers may retain
    their historical direct-SQLite fallback in that case.
    """

    from flask import current_app, has_app_context
    from sqlalchemy.engine import make_url

    if not has_app_context():
        return None

    database_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        return None
    return make_url(database_uri).get_backend_name().lower() == "sqlite"
