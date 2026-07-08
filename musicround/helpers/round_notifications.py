"""Email notifications for blocked round package quality gates."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any

from flask import current_app

from musicround import db
from musicround.helpers.email_helper import send_email
from musicround.models import Round, SystemSetting, User


ROUND_BLOCKED_NOTIFICATION_COOLDOWN_HOURS = 24
SECRET_PATTERN = re.compile(r"(?i)\b(token|password|secret|access_token|refresh_token)=\S+")


def _round_blocked_preference_enabled(user: User | None) -> bool:
    if user is None:
        return False
    preferences = getattr(user, "preferences", None)
    if preferences is None:
        return True
    return bool(preferences.round_blocked_email_notifications)


def _setting_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _round_blocked_dedupe_key(user: User, round_id: int, quality: dict[str, Any]) -> str:
    report = quality.get("report") or {}
    raw_key = ":".join(
        (
            str(user.id),
            str(round_id),
            str(quality.get("status") or "blocked"),
            str(report.get("headline") or ""),
        )
    )
    return f"notification:round-blocked:{hashlib.sha256(raw_key.encode()).hexdigest()[:30]}"


def _already_notified(dedupe_key: str, now: datetime) -> bool:
    sent_at = _setting_datetime(SystemSetting.get(dedupe_key))
    if sent_at is None:
        return False
    return sent_at >= now - timedelta(hours=ROUND_BLOCKED_NOTIFICATION_COOLDOWN_HOURS)


def _mark_notified(dedupe_key: str, now: datetime) -> None:
    SystemSetting.set(dedupe_key, now.isoformat(timespec="seconds"))


def _round_title(round_id: int) -> str:
    round_obj = db.session.get(Round, round_id)
    if round_obj and round_obj.name:
        return round_obj.name
    return f"Round {round_id}"


def _round_blocked_body(user: User, round_id: int, quality: dict[str, Any]) -> str:
    report = quality.get("report") or {}
    headline = _safe_text(report.get("headline") or f"{_round_title(round_id)} is blocked.")
    hints = quality.get("hints") or []
    markdown = _safe_text(report.get("markdown") or "")
    lines = [
        f"Hi {user.first_name or user.username},",
        "",
        headline,
        "",
        f"Status: {quality.get('status') or 'blocked'}",
    ]
    if hints:
        lines.extend(["", "Repair hints:"])
        lines.extend(f"- {_safe_text(str(hint))}" for hint in hints[:8])
    if markdown:
        lines.extend(["", "Repair report:", markdown[:2000]])
    lines.extend(
        [
            "",
            "Open the round in Quizzical Beats, repair the listed songs or assets, regenerate MP3/PDF, and rerun Inspect Round before scheduling or sending.",
        ]
    )
    return "\n".join(lines)


def _safe_text(value: str) -> str:
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[redacted]", value)


def send_round_blocked_notification(
    *,
    user: User | None,
    round_id: int,
    quality: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Notify the quizmaster that a round failed the package quality gate."""
    current_time = now or datetime.utcnow()
    if not user or not getattr(user, "email", None):
        return {"sent": False, "skipped": True, "reason": "missing_recipient"}
    if not _round_blocked_preference_enabled(user):
        return {"sent": False, "skipped": True, "reason": "preference_disabled"}

    dedupe_key = _round_blocked_dedupe_key(user, round_id, quality)
    if _already_notified(dedupe_key, current_time):
        return {"sent": False, "skipped": True, "reason": "deduplicated"}

    subject = f"Quizzical Beats: {_round_title(round_id)} needs repair"
    body_text = _round_blocked_body(user, round_id, quality)
    try:
        success, message = send_email(
            recipient=user.email,
            subject=subject,
            body_text=body_text,
        )
    except Exception as exc:  # pylint: disable=broad-except
        success = False
        message = str(exc)

    if success:
        _mark_notified(dedupe_key, current_time)
        return {"sent": True, "skipped": False, "reason": None}

    current_app.logger.warning(
        "Round blocked notification for round %s user %s failed: %s",
        round_id,
        user.id,
        message,
    )
    return {"sent": False, "skipped": False, "reason": "delivery_failed"}
