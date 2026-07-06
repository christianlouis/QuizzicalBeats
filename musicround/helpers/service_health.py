"""Reusable service-health payloads for routes, automation, and MCP."""

from __future__ import annotations

from typing import Any

from flask import current_app
from sqlalchemy import text

from musicround.helpers.database_config import database_summary
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

    summary = database_summary(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    return {
        "status": _status_from_issues(issues),
        "ok": not issues,
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


def spotify_service_health(user: Any | None = None) -> dict[str, Any]:
    """Return Spotify configuration and optional user-connection health."""
    issues: list[dict[str, Any]] = []
    if not current_app.config.get("SPOTIFY_CLIENT_ID") or not current_app.config.get("SPOTIFY_CLIENT_SECRET"):
        issues.append(
            _issue(
                "spotify_credentials_missing",
                "Spotify API credentials are not configured.",
                severity="warning",
                hint="Configure SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
            )
        )

    if user is not None and getattr(user, "spotify_id", None) and not getattr(user, "spotify_refresh_token", None):
        issues.append(
            _issue(
                "spotify_reconnect_required",
                "Spotify connection is linked but cannot refresh.",
                severity="warning",
                hint="Reconnect Spotify from the profile page.",
            )
        )

    return {
        "status": _status_from_issues(issues),
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "connected": bool(user is not None and getattr(user, "spotify_refresh_token", None)),
        "issues": issues,
    }


def dropbox_service_health(user: Any | None = None) -> dict[str, Any]:
    """Return Dropbox optional connection health for a user."""
    issues: list[dict[str, Any]] = []
    if user is not None and getattr(user, "dropbox_id", None) and not getattr(user, "dropbox_refresh_token", None):
        issues.append(
            _issue(
                "dropbox_reconnect_required",
                "Dropbox connection is linked but cannot refresh.",
                severity="warning",
                hint="Reconnect Dropbox from the profile page before exporting rounds.",
            )
        )
    return {
        "status": _status_from_issues(issues),
        "ok": True,
        "connected": bool(user is not None and getattr(user, "dropbox_refresh_token", None)),
        "issues": issues,
    }


def application_health_payload(include_storage: bool = True) -> dict[str, Any]:
    """Return a public-safe health payload for uptime checks."""
    services = {
        "database": database_service_health(),
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
