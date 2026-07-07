"""Database configuration helpers with credential-safe summaries."""

from __future__ import annotations

from urllib.parse import quote, urlencode, urlsplit, urlunsplit


def bool_from_config(value) -> bool:
    """Return a bool from common environment/config values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def database_backend(uri: str | None) -> str:
    """Return a normalized backend name for a SQLAlchemy database URI."""
    if not uri:
        return "unconfigured"
    driver = uri.split(":", 1)[0].lower()
    return driver.split("+", 1)[0]


def is_sqlite_database_uri(uri: str | None) -> bool:
    """Return whether the configured database URI points at SQLite."""
    return database_backend(uri) == "sqlite"


def is_legacy_data_sqlite_uri(uri: str | None) -> bool:
    """Return whether the URI points at the legacy production SQLite file."""
    if not is_sqlite_database_uri(uri):
        return False
    parts = urlsplit(uri or "")
    normalized_path = "/" + parts.path.lstrip("/")
    return normalized_path == "/data/song_data.db"


def managed_database_requirement_error(
    uri: str | None,
    require_managed,
) -> str | None:
    """Return a safe error message when managed DB mode is misconfigured."""
    if not bool_from_config(require_managed):
        return None
    if not uri:
        return (
            "DATABASE_REQUIRE_MANAGED is enabled, but neither "
            "SQLALCHEMY_DATABASE_URI nor a complete PGHOST/PGDATABASE/PGUSER/"
            "PGPASSWORD configuration is available."
        )
    if is_sqlite_database_uri(uri):
        return (
            "DATABASE_REQUIRE_MANAGED is enabled, but SQLALCHEMY_DATABASE_URI "
            "points at SQLite. Configure a managed SQL URI or complete PG* "
            "database credentials via secrets."
        )
    return None


def database_uri_from_postgres_env(environ) -> str | None:
    """Build a SQLAlchemy PostgreSQL URI from standard PG* environment variables.

    Args:
        environ: Mapping of environment variable names to values, typically
            ``os.environ``.

    Returns:
        A PostgreSQL SQLAlchemy URI, or ``None`` when no required PG* variables
        are configured.

    Raises:
        ValueError: If only part of the required PGHOST, PGDATABASE, PGUSER,
            and PGPASSWORD configuration is present.
    """
    values = {
        "PGHOST": environ.get("PGHOST"),
        "PGDATABASE": environ.get("PGDATABASE"),
        "PGUSER": environ.get("PGUSER"),
        "PGPASSWORD": environ.get("PGPASSWORD"),
    }
    if not any(values.values()):
        return None

    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(
            "PostgreSQL environment is incomplete; missing "
            + ", ".join(sorted(missing))
            + "."
        )

    scheme = environ.get("SQLALCHEMY_POSTGRES_SCHEME", "postgresql+psycopg2")
    host = str(values["PGHOST"]).strip()
    port = str(environ.get("PGPORT") or "5432").strip()
    database = quote(str(values["PGDATABASE"]).strip(), safe="")
    username = quote(str(values["PGUSER"]).strip(), safe="")
    password = quote(str(values["PGPASSWORD"]), safe="")
    netloc = f"{username}:{password}@{host}:{port}"

    query_params = {}
    sslmode = environ.get("PGSSLMODE")
    if sslmode:
        query_params["sslmode"] = sslmode
    query = urlencode(query_params)

    return urlunsplit((scheme, netloc, f"/{database}", query, ""))


def redact_database_uri(uri: str | None) -> str:
    """Redact credentials from a database URI without hiding the backend."""
    if not uri:
        return "unconfigured"
    if is_sqlite_database_uri(uri):
        return "sqlite:///[local-file]"

    parts = urlsplit(uri)
    if not parts.netloc:
        return f"{parts.scheme}://[configured]"

    host = parts.hostname or "configured-host"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    username = f"{quote(parts.username, safe='%')}:***@" if parts.username else ""
    netloc = f"{username}{host}{port}"
    path = parts.path or ""
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def database_summary(uri: str | None) -> dict[str, str | bool | None]:
    """Return a credential-safe database summary for logs and health checks."""
    parts = urlsplit(uri or "")
    is_sqlite = is_sqlite_database_uri(uri)
    return {
        "backend": database_backend(uri),
        "is_sqlite": is_sqlite,
        "host": None if is_sqlite else (parts.hostname or None),
        "database": None if is_sqlite else (parts.path.lstrip("/") or None),
        "redacted_uri": redact_database_uri(uri),
    }
