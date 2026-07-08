"""Admin notification digest helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import current_app

from musicround.helpers.email_helper import send_email
from musicround.helpers.oauth_notifications import collect_oauth_token_notifications
from musicround.models import ImportJobRecord, RoundExport


def _recent_cutoff(now: datetime, hours: int) -> datetime:
    return now - timedelta(hours=hours)


def _failed_round_exports(since: datetime, limit: int) -> list[RoundExport]:
    return (
        RoundExport.query.filter(RoundExport.export_type == "email")
        .filter(RoundExport.status == "failed")
        .filter(RoundExport.timestamp >= since)
        .order_by(RoundExport.timestamp.desc())
        .limit(limit)
        .all()
    )


def _dead_letter_imports(limit: int) -> list[ImportJobRecord]:
    return (
        ImportJobRecord.query.filter_by(status="dead_letter")
        .order_by(ImportJobRecord.completed_at.desc().nullslast(), ImportJobRecord.created_at.desc())
        .limit(limit)
        .all()
    )


def _summary_body(summary: dict[str, Any]) -> str:
    lines = [
        "Quizzical Beats notification summary",
        "",
        f"Window: last {summary['window_hours']} hours",
        f"OAuth warning candidates: {summary['oauth_token_candidate_count']}",
        f"Failed round email exports: {summary['failed_round_export_count']}",
        f"Dead-letter import jobs: {summary['dead_letter_import_count']}",
    ]
    if summary["failed_round_exports"]:
        lines.extend(["", "Failed round exports:"])
        for item in summary["failed_round_exports"]:
            lines.append(
                f"- export #{item['id']} round #{item['round_id']} status={item['status']}"
            )
    if summary["dead_letter_imports"]:
        lines.extend(["", "Dead-letter imports:"])
        for item in summary["dead_letter_imports"]:
            lines.append(
                f"- job #{item['id']} {item['service_name']} {item['item_type']} attempts={item['attempt_count']}"
            )
    if summary["oauth_token_notifications"]:
        lines.extend(["", "OAuth warnings:"])
        for item in summary["oauth_token_notifications"]:
            lines.append(
                f"- user #{item['user_id']} {item['service']} {item['issue_code']} ({item['status']})"
            )
    lines.extend(["", "No credentials or provider tokens are included in this digest."])
    return "\n".join(lines)


def notification_admin_summary(
    *,
    now: datetime | None = None,
    window_hours: int = 24,
    limit: int = 10,
) -> dict[str, Any]:
    """Return a credential-safe summary of actionable notification work."""
    current_time = now or datetime.utcnow()
    since = _recent_cutoff(current_time, window_hours)
    oauth_notifications = collect_oauth_token_notifications(now=current_time)
    failed_exports = _failed_round_exports(since, limit)
    dead_letters = _dead_letter_imports(limit)
    summary = {
        "generated_at": current_time.isoformat(timespec="seconds"),
        "window_hours": window_hours,
        "oauth_token_candidate_count": len(oauth_notifications),
        "failed_round_export_count": len(failed_exports),
        "dead_letter_import_count": len(dead_letters),
        "oauth_token_notifications": [
            {
                "user_id": item.user_id,
                "service": item.service,
                "issue_code": item.issue_code,
                "status": item.status,
            }
            for item in oauth_notifications[:limit]
        ],
        "failed_round_exports": [
            {
                "id": item.id,
                "round_id": item.round_id,
                "user_id": item.user_id,
                "status": item.status,
                "timestamp": item.timestamp.isoformat(timespec="seconds") if item.timestamp else None,
            }
            for item in failed_exports
        ],
        "dead_letter_imports": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "service_name": item.service_name,
                "item_type": item.item_type,
                "attempt_count": item.attempt_count,
                "completed_at": item.completed_at.isoformat(timespec="seconds")
                if item.completed_at
                else None,
            }
            for item in dead_letters
        ],
    }
    summary["actionable_count"] = (
        summary["oauth_token_candidate_count"]
        + summary["failed_round_export_count"]
        + summary["dead_letter_import_count"]
    )
    return summary


def send_notification_admin_summary(
    *,
    recipient: str | None = None,
    now: datetime | None = None,
    window_hours: int = 24,
    limit: int = 10,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Send or preview the admin notification summary."""
    summary = notification_admin_summary(now=now, window_hours=window_hours, limit=limit)
    target = recipient or current_app.config.get("MAIL_RECIPIENT")
    result = {
        "dry_run": dry_run,
        "recipient": target,
        "sent": False,
        "failed": False,
        "summary": summary,
    }
    if dry_run:
        return result
    if not target:
        result["failed"] = True
        result["message"] = "Admin summary recipient is missing."
        return result
    success, message = send_email(
        recipient=target,
        subject="Quizzical Beats notification summary",
        body_text=_summary_body(summary),
    )
    result["sent"] = success
    result["failed"] = not success
    result["message"] = "Admin summary sent." if success else message
    return result
