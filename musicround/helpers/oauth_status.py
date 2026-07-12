"""Shared OAuth connection status helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


TOKEN_EXPIRY_WARNING_MINUTES = 15


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now()


def _token_status(
    *,
    service: str,
    linked_id: str | None,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: datetime | None,
    now: datetime | None = None,
    warning_window: timedelta | None = None,
) -> dict[str, Any]:
    current_time = _now(now)
    window = warning_window or timedelta(minutes=TOKEN_EXPIRY_WARNING_MINUTES)
    connected = bool(access_token and refresh_token)

    payload: dict[str, Any] = {
        "service": service,
        "linked": bool(linked_id),
        "connected": connected,
        "reconnect_required": False,
        "expires_at": expires_at,
        "expires_soon": False,
        "expired": False,
        "status": "not_connected",
        "level": "info",
        "title": "Not connected",
        "message": f"{service.title()} is not connected.",
        "issue_code": None,
    }

    if linked_id and not connected:
        payload.update(
            {
                "reconnect_required": True,
                "status": "reconnect_required",
                "level": "danger",
                "title": "Reconnect required",
                "message": f"Your {service.title()} account is linked, but stored credentials are missing.",
                "issue_code": f"{service}_reconnect_required",
            }
        )
        return payload

    if not connected:
        return payload

    payload.update(
        {
            "status": "connected",
            "level": "success",
            "title": "Connected",
            "message": f"{service.title()} is connected.",
        }
    )

    if expires_at is None:
        payload.update(
            {
                "status": "expiry_unknown",
                "level": "warning",
                "title": "Expiry unknown",
                "message": f"Reconnect {service.title()} if imports or exports fail.",
                "issue_code": f"{service}_token_expiry_unknown",
            }
        )
        return payload

    seconds_until_expiry = (expires_at - current_time).total_seconds()
    payload["seconds_until_expiry"] = seconds_until_expiry

    if seconds_until_expiry <= 0:
        payload.update(
            {
                "expired": True,
                # Both providers support refresh tokens. An expired access token is
                # therefore expected and is renewed on the next provider request.
                "status": "refresh_required",
                "level": "warning",
                "title": "Access token will refresh",
                "message": f"{service.title()} will refresh its access token automatically when needed.",
                "issue_code": f"{service}_token_refresh_required",
            }
        )
    elif expires_at <= current_time + window:
        payload.update(
            {
                "expires_soon": True,
                "status": "expiring",
                "level": "warning",
                "title": "Token expires soon",
                "message": f"Refresh or reconnect {service.title()} before starting a long workflow.",
                "issue_code": f"{service}_token_expiring",
            }
        )

    return payload


def spotify_token_status(user: Any, now: datetime | None = None) -> dict[str, Any]:
    """Return a reusable, secret-free Spotify connection status."""
    status = _token_status(
        service="spotify",
        linked_id=getattr(user, "spotify_id", None),
        access_token=getattr(user, "spotify_token", None),
        refresh_token=getattr(user, "spotify_refresh_token", None),
        expires_at=getattr(user, "spotify_token_expiry", None),
        now=now,
    )
    if status["status"] == "refresh_required":
        status["message"] = "Spotify will refresh automatically before playlist imports or metadata lookups."
    elif status["status"] == "expiring":
        status["message"] = "Refresh or reconnect Spotify before starting a long import."
    elif status["status"] == "expiry_unknown":
        status["message"] = "Reconnect Spotify if imports or playlist lookups fail."
    return status


def dropbox_token_status(user: Any, now: datetime | None = None) -> dict[str, Any]:
    """Return a reusable, secret-free Dropbox connection status."""
    status = _token_status(
        service="dropbox",
        linked_id=getattr(user, "dropbox_id", None),
        access_token=getattr(user, "dropbox_token", None),
        refresh_token=getattr(user, "dropbox_refresh_token", None),
        expires_at=getattr(user, "dropbox_token_expiry", None),
        now=now,
    )
    if status["status"] == "refresh_required":
        status["message"] = "Dropbox will refresh automatically before exporting round packages."
    elif status["status"] == "expiring":
        status["message"] = "Refresh or reconnect Dropbox before exporting a round package."
    elif status["status"] == "expiry_unknown":
        status["message"] = "Reconnect Dropbox if exports or folder lookups fail."
    return status


def token_notice(status: dict[str, Any]) -> dict[str, str] | None:
    """Return a compact UI notice for actionable token statuses."""
    if status.get("level") not in {"danger", "warning"}:
        return None
    return {
        "level": status["level"],
        "title": status["title"],
        "message": status["message"],
    }
