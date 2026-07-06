"""Reusable service-health payloads for routes, automation, and MCP."""

from __future__ import annotations

from typing import Any

from flask import current_app
from sqlalchemy import func, text

from musicround.helpers.database_config import database_summary, is_legacy_data_sqlite_uri
from musicround.helpers.oauth_status import dropbox_token_status, spotify_token_status
from musicround.helpers.storage_health import check_round_artifact_storage
from musicround.version import VERSION_INFO


def _issue(
    code: str,
    message: str,
    severity: str = "error",
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "severity": severity,
        "message": message,
        "details": details or {},
    }
    if hint:
        payload["details"]["hint"] = hint
    return payload


def _status_from_issues(issues: list[dict[str, Any]]) -> str:
    if any(issue.get("severity") == "error" for issue in issues):
        return "error"
    if issues:
        return "warning"
    return "ok"


def _ok_from_issues(issues: list[dict[str, Any]]) -> bool:
    return not any(issue.get("severity") == "error" for issue in issues)


def _token_status_payload(status: dict[str, Any] | None) -> dict[str, Any] | None:
    if status is None:
        return None
    payload = dict(status)
    if payload.get("expires_at"):
        payload["expires_at"] = payload["expires_at"].isoformat()
    return payload


def database_service_health() -> dict[str, Any]:
    """Return a credential-safe database health payload."""
    from musicround.models import db

    issues: list[dict[str, Any]] = []
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        current_app.logger.error("Database health probe failed: %s", exc, exc_info=True)
        issues.append(
            _issue(
                "database_unavailable",
                "Database health probe failed.",
                hint="Check the configured SQL database and network path.",
            )
        )

    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if is_legacy_data_sqlite_uri(db_uri):
        issues.append(
            _issue(
                "legacy_sqlite_data_store",
                "Database is still configured to use the legacy /data SQLite file.",
                severity="warning",
                hint=(
                    "Move SQLALCHEMY_DATABASE_URI to the managed database secret "
                    "and enable DATABASE_REQUIRE_MANAGED=True for production."
                ),
            )
        )

    summary = database_summary(db_uri)
    return {
        "status": _status_from_issues(issues),
        "ok": _ok_from_issues(issues),
        "backend": current_app.config.get("DATABASE_BACKEND") or summary["backend"],
        "database": summary["database"],
        "host": summary["host"],
        "issues": issues,
    }


def artifact_storage_service_health(
    include_mp3: bool = True,
    include_pdf: bool = True,
) -> dict[str, Any]:
    """Return service-health status for generated round artifact storage."""
    storage = check_round_artifact_storage(include_mp3=include_mp3, include_pdf=include_pdf)
    issues = storage.get("issues", [])
    return {
        "status": _status_from_issues(issues),
        "ok": storage["ok"],
        "checks": storage["checks"],
        "issues": issues,
        "hints": storage["hints"],
    }


def email_service_health(required: bool = False) -> dict[str, Any]:
    """Return basic SMTP configuration health without exposing credentials."""
    issues: list[dict[str, Any]] = []
    required_keys = ["MAIL_HOST", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_SENDER"]
    missing_keys = [key for key in required_keys if not current_app.config.get(key)]
    if required:
        for key in missing_keys:
            issues.append(
                _issue(
                    f"{key.lower()}_missing",
                    f"Email delivery is missing {key}.",
                    hint=f"Configure {key} before scheduling or sending round emails.",
                )
            )
    return {
        "status": _status_from_issues(issues),
        "ok": not issues,
        "configured": not missing_keys,
        "missing": missing_keys if required else [],
        "issues": issues,
    }


def import_queue_service_health() -> dict[str, Any]:
    """Return public-safe import queue and worker health."""
    from musicround.models import ImportJobRecord, db

    issues: list[dict[str, Any]] = []
    queue = current_app.config.get("import_queue") or current_app.config.get("IMPORT_QUEUE")
    workers = current_app.config.get("import_workers") or []
    workers_enabled = bool(current_app.config.get("IMPORT_WORKERS_ENABLED_RESOLVED"))
    configured_worker_count = int(current_app.config.get("IMPORT_WORKER_COUNT_RESOLVED") or 0)

    if queue is None:
        issues.append(
            _issue(
                "import_queue_not_initialized",
                "Import queue is not initialized.",
                hint="Check app startup and import queue configuration.",
            )
        )

    counts = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "dead_letter": 0,
    }
    try:
        rows = (
            db.session.query(ImportJobRecord.status, func.count(ImportJobRecord.id))
            .group_by(ImportJobRecord.status)
            .all()
        )
        for status, count in rows:
            counts[status or "unknown"] = int(count or 0)
    except Exception as exc:
        current_app.logger.error("Import queue health probe failed: %s", exc, exc_info=True)
        issues.append(
            _issue(
                "import_queue_probe_failed",
                "Import queue health probe failed.",
                hint="Check the import job table and database connectivity.",
            )
        )

    if workers_enabled and not workers:
        issues.append(
            _issue(
                "import_workers_enabled_not_running",
                "Import workers are enabled but no worker threads are registered.",
                hint="Check worker startup logs.",
            )
        )
    if counts["pending"] and not workers_enabled:
        issues.append(
            _issue(
                "import_jobs_waiting_without_local_workers",
                "Import jobs are pending while local in-process workers are disabled.",
                severity="warning",
                hint="Ensure a dedicated worker process is running or enable workers for this process.",
                details={"pending": counts["pending"]},
            )
        )
    if counts["dead_letter"]:
        issues.append(
            _issue(
                "import_jobs_need_manual_review",
                "Some import jobs are in dead-letter state.",
                severity="warning",
                hint="Review and retry or discard dead-letter import jobs.",
                details={"dead_letter": counts["dead_letter"]},
            )
        )

    return {
        "status": _status_from_issues(issues),
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "initialized": queue is not None,
        "workers_enabled": workers_enabled,
        "worker_count": len(workers),
        "configured_worker_count": configured_worker_count,
        "queue_size": queue.qsize() if queue is not None else None,
        "jobs": counts,
        "issues": issues,
    }


def spotify_service_health(user: Any | None = None) -> dict[str, Any]:
    """Return Spotify configuration and optional user-connection health."""
    issues: list[dict[str, Any]] = []
    token_status = spotify_token_status(user) if user is not None else None
    if not current_app.config.get("SPOTIFY_CLIENT_ID") or not current_app.config.get("SPOTIFY_CLIENT_SECRET"):
        issues.append(
            _issue(
                "spotify_credentials_missing",
                "Spotify API credentials are not configured.",
                severity="warning",
                hint="Configure SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
            )
        )

    if token_status and token_status.get("issue_code"):
        severity = "warning"
        issues.append(
            _issue(
                token_status["issue_code"],
                token_status["message"],
                severity=severity,
                hint="Reconnect Spotify from the profile page."
                if token_status.get("reconnect_required")
                else "Refresh or reconnect Spotify before long imports.",
                details={
                    "status": token_status["status"],
                    "expires_at": token_status["expires_at"].isoformat()
                    if token_status.get("expires_at")
                    else None,
                    "expires_soon": token_status["expires_soon"],
                    "reconnect_required": token_status["reconnect_required"],
                },
            )
        )

    payload = {
        "status": _status_from_issues(issues),
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "connected": bool(token_status and token_status["connected"]),
        "issues": issues,
    }
    if token_status is not None:
        payload["token_status"] = _token_status_payload(token_status)
    return payload


def dropbox_service_health(user: Any | None = None) -> dict[str, Any]:
    """Return Dropbox optional connection health for a user."""
    issues: list[dict[str, Any]] = []
    token_status = dropbox_token_status(user) if user is not None else None
    if token_status and token_status.get("issue_code"):
        issues.append(
            _issue(
                token_status["issue_code"],
                token_status["message"],
                severity="warning",
                hint="Reconnect Dropbox from the profile page before exporting rounds."
                if token_status.get("reconnect_required")
                else "Refresh or reconnect Dropbox before exporting rounds.",
                details={
                    "status": token_status["status"],
                    "expires_at": token_status["expires_at"].isoformat()
                    if token_status.get("expires_at")
                    else None,
                    "expires_soon": token_status["expires_soon"],
                    "reconnect_required": token_status["reconnect_required"],
                },
            )
        )
    payload = {
        "status": _status_from_issues(issues),
        "ok": True,
        "connected": bool(token_status and token_status["connected"]),
        "issues": issues,
    }
    if token_status is not None:
        payload["token_status"] = _token_status_payload(token_status)
    return payload


def application_health_payload(include_storage: bool = True) -> dict[str, Any]:
    """Return a public-safe health payload for uptime checks."""
    services = {
        "database": database_service_health(),
        "import_queue": import_queue_service_health(),
        "spotify": spotify_service_health(),
        "email": email_service_health(required=False),
    }
    if include_storage:
        services["artifact_storage"] = artifact_storage_service_health()

    ok = all(service.get("ok", False) for service in services.values())
    status = "ok" if ok else "degraded"
    return {
        "ok": ok,
        "status": status,
        "version": VERSION_INFO["version"],
        "release": VERSION_INFO["release_name"],
        "services": services,
    }
