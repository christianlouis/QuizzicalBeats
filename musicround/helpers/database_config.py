"""Database configuration helpers with credential-safe summaries."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


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
    port = f":{parts.port}" if parts.port else ""
    username = f"{parts.username}:***@" if parts.username else ""
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
