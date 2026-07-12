"""Email notification helpers for OAuth connection health."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from flask import current_app

from musicround import db
from musicround.helpers.email_helper import send_email
from musicround.helpers.oauth_status import dropbox_token_status, spotify_token_status
from musicround.models import SystemSetting, User


TOKEN_NOTIFICATION_COOLDOWN_HOURS = 24
# Expiry is normal for short-lived OAuth access tokens. A refresh token lets the
# provider helpers recover on demand; only missing credentials require a user
# action and therefore an email.
ACTIONABLE_TOKEN_STATUSES = {"reconnect_required"}


@dataclass(frozen=True)
class OAuthTokenNotification:
    user_id: int
    recipient: str
    service: str
    issue_code: str
    status: str
    subject: str
    body_text: str
    dedupe_key: str


def _notification_preference_enabled(user: User) -> bool:
    preferences = getattr(user, "preferences", None)
    if preferences is None:
        return True
    return bool(preferences.oauth_token_email_notifications)


def _status_fingerprint(status: dict[str, Any]) -> str:
    expires_at = status.get("expires_at")
    if isinstance(expires_at, datetime):
        return expires_at.isoformat(timespec="minutes")
    return status.get("status") or "unknown"


def _dedupe_key(user: User, status: dict[str, Any]) -> str:
    raw_key = ":".join(
        (
            str(user.id),
            status["service"],
            status.get("issue_code") or status["status"],
            _status_fingerprint(status),
        )
    )
    return f"notification:oauth-token:{hashlib.sha256(raw_key.encode()).hexdigest()[:32]}"


def _setting_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _already_notified(dedupe_key: str, now: datetime) -> bool:
    sent_at = _setting_datetime(SystemSetting.get(dedupe_key))
    if sent_at is None:
        return False
    return sent_at >= now - timedelta(hours=TOKEN_NOTIFICATION_COOLDOWN_HOURS)


def _mark_notified(dedupe_key: str, now: datetime) -> None:
    SystemSetting.set(dedupe_key, now.isoformat(timespec="seconds"))


def _token_notification_body(user: User, status: dict[str, Any]) -> str:
    service_name = status["service"].title()
    lines = [
        f"Hi {user.first_name or user.username},",
        "",
        f"Quizzical Beats detected a {service_name} connection issue:",
        f"- Status: {status['title']}",
        f"- Detail: {status['message']}",
    ]
    expires_at = status.get("expires_at")
    if isinstance(expires_at, datetime):
        lines.append(f"- Expires at: {expires_at.strftime('%Y-%m-%d %H:%M')}")
    lines.extend(
        [
            "",
            "Please open your Quizzical Beats profile and reconnect or refresh the service before the next import/export workflow.",
            "",
            "This message contains no OAuth tokens or provider secrets.",
        ]
    )
    return "\n".join(lines)


def _notification_for_status(user: User, status: dict[str, Any]) -> OAuthTokenNotification | None:
    if status.get("status") not in ACTIONABLE_TOKEN_STATUSES:
        return None
    issue_code = status.get("issue_code")
    if not issue_code:
        return None
    recipient = getattr(user, "email", None)
    if not recipient:
        return None
    service_name = status["service"].title()
    return OAuthTokenNotification(
        user_id=user.id,
        recipient=recipient,
        service=status["service"],
        issue_code=issue_code,
        status=status["status"],
        subject=f"Quizzical Beats: {service_name} connection needs attention",
        body_text=_token_notification_body(user, status),
        dedupe_key=_dedupe_key(user, status),
    )


def collect_oauth_token_notifications(now: datetime | None = None) -> list[OAuthTokenNotification]:
    """Return pending, secret-free OAuth token warning email candidates."""
    current_time = now or datetime.now()
    notifications: list[OAuthTokenNotification] = []
    users = User.query.filter_by(active=True).all()
    for user in users:
        if not _notification_preference_enabled(user):
            continue
        for status in (
            spotify_token_status(user, now=current_time),
            dropbox_token_status(user, now=current_time),
        ):
            notification = _notification_for_status(user, status)
            if notification is None:
                continue
            if _already_notified(notification.dedupe_key, current_time):
                continue
            notifications.append(notification)
    return notifications


def send_oauth_token_notifications(
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Send or preview OAuth token warning emails."""
    current_time = now or datetime.now()
    notifications = collect_oauth_token_notifications(now=current_time)
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "candidate_count": len(notifications),
        "sent_count": 0,
        "failed_count": 0,
        "notifications": [
            {
                "user_id": item.user_id,
                "recipient": item.recipient,
                "service": item.service,
                "issue_code": item.issue_code,
                "status": item.status,
            }
            for item in notifications
        ],
    }
    if dry_run:
        return result

    for notification in notifications:
        try:
            success, message = send_email(
                recipient=notification.recipient,
                subject=notification.subject,
                body_text=notification.body_text,
            )
        except Exception as exc:  # pylint: disable=broad-except
            success = False
            message = str(exc)
        if success:
            _mark_notified(notification.dedupe_key, current_time)
            result["sent_count"] += 1
        else:
            current_app.logger.warning(
                "OAuth token notification for user %s service %s failed: %s",
                notification.user_id,
                notification.service,
                message,
            )
            result["failed_count"] += 1
    db.session.commit()
    return result
