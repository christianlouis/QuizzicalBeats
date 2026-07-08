"""Database configuration helpers with credential-safe summaries."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit


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


def postgres_env_readiness(environ) -> dict[str, list[str] | bool]:
    """Return credential-safe readiness details for PG* database variables."""
    required_keys = ["PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    optional_keys = ["PGPORT", "PGSSLMODE", "SQLALCHEMY_POSTGRES_SCHEME"]
    present_required = [name for name in required_keys if environ.get(name)]
    missing_required = [name for name in required_keys if not environ.get(name)]
    present_optional = [name for name in optional_keys if environ.get(name)]
    return {
        "configured": bool(present_required),
        "complete": not missing_required,
        "present_required": present_required,
        "missing_required": missing_required,
        "present_optional": present_optional,
    }


def database_uri_overrides_postgres_env(environ) -> bool:
    """Return whether a full SQLAlchemy URI masks complete split PG* config."""
    if not environ.get("SQLALCHEMY_DATABASE_URI"):
        return False
    readiness = postgres_env_readiness(environ)
    return bool(readiness["configured"] and readiness["complete"])


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
    username = f"{quote(unquote(parts.username), safe='')}:***@" if parts.username else ""
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


def database_cutover_plan(diagnostics: dict) -> dict:
    """Build a credential-safe managed database cutover checklist."""
    issues = diagnostics.get("issues") or []
    issue_codes = {issue.get("code") for issue in issues}
    database = diagnostics.get("database") or {}
    backend = database.get("backend")
    postgres_env = diagnostics.get("postgres_env") or {}
    pg_complete = bool(postgres_env.get("complete"))
    pg_configured = bool(postgres_env.get("configured"))
    managed_ready = (
        backend not in {"sqlite", "unconfigured", None}
        and diagnostics.get("ok") is True
        and "database_uri_overrides_postgres_env" not in issue_codes
    )

    def step(key: str, title: str, status: str, hint: str) -> dict[str, str]:
        return {
            "key": key,
            "title": title,
            "status": status,
            "hint": hint,
        }

    configure_status = "done" if managed_ready else "blocked"
    if backend == "sqlite":
        configure_hint = (
            "Remove the legacy SQLite URI and provide managed SQL through "
            "SQLALCHEMY_DATABASE_URI or complete PG* secret keys."
        )
    elif backend == "unconfigured":
        configure_hint = "Provide managed SQL through secrets before cutover."
    elif pg_configured and not pg_complete:
        configure_hint = (
            "Complete the missing PG* secret keys before relying on split "
            "PostgreSQL configuration."
        )
    elif "database_uri_overrides_postgres_env" in issue_codes:
        configure_hint = (
            "Blank SQLALCHEMY_DATABASE_URI before relying on the split PG* "
            "managed database secret keys."
        )
    else:
        configure_hint = "Managed database configuration is selected."

    preflight_status = "ready" if managed_ready else "blocked"
    migration_status = "ready" if managed_ready else "blocked"
    smoke_status = "ready" if managed_ready else "blocked"
    guard_status = "ready" if managed_ready else "blocked"

    steps = [
        step(
            "backup_legacy_sqlite",
            "Create a fresh backup of the legacy SQLite data store",
            "ready",
            "Run the existing backup flow before any migration execution.",
        ),
        step(
            "configure_managed_database",
            "Configure the managed SQL target through secrets",
            configure_status,
            configure_hint,
        ),
        step(
            "preflight_managed_database",
            "Run database preflight in web, MCP, and scheduler contexts",
            preflight_status,
            "Use `python run.py database preflight`; it must report a non-SQLite backend.",
        ),
        step(
            "dry_run_sqlite_migration",
            "Dry-run the SQLite-to-managed-database migration",
            migration_status,
            "Run the SQLite migration command in dry-run mode against the backed-up legacy database first.",
        ),
        step(
            "execute_sqlite_migration",
            "Execute the migration after reviewing dry-run counts",
            migration_status,
            "Add `--execute` only after the dry-run row counts look correct.",
        ),
        step(
            "enable_managed_guard",
            "Keep DATABASE_REQUIRE_MANAGED enabled after cutover",
            guard_status,
            "The guard prevents accidental rollback to SQLite during future deploys.",
        ),
        step(
            "smoke_web_mcp_scheduler",
            "Smoke-test web, MCP, and scheduled-email paths",
            smoke_status,
            "Verify health output, MCP database summary, and one scheduled-email run.",
        ),
    ]
    blocked_steps = [item["key"] for item in steps if item["status"] == "blocked"]
    ready_steps = [item["key"] for item in steps if item["status"] == "ready"]
    done_steps = [item["key"] for item in steps if item["status"] == "done"]
    step_keys = [item["key"] for item in steps]
    return {
        "ok": not blocked_steps,
        "status": "ready" if not blocked_steps else "blocked",
        "database": database,
        "postgres_env": postgres_env,
        "issues": issues,
        "steps": steps,
        "blocked_steps": blocked_steps,
        "ready_steps": ready_steps,
        "done_steps": done_steps,
        "next_action": (
            "Run dry-run migration and smoke checks."
            if not blocked_steps
            else steps[step_keys.index(blocked_steps[0])]["hint"]
        ),
    }
