"""Tests for admin notification summaries."""

from datetime import datetime, timedelta
from unittest.mock import patch

from musicround.helpers.notification_summary import (
    notification_admin_summary,
    send_notification_admin_summary,
)
from musicround.models import ImportJobRecord, Round, RoundExport, User, db


def _make_user(username='summaryuser', email='summary@example.test', **kwargs):
    user = User(username=username, email=email, **kwargs)
    user.password = 'SummaryPass123!'
    db.session.add(user)
    db.session.flush()
    return user


def _make_round(name='Summary Round'):
    round_obj = Round(name=name, round_type='manual', round_criteria_used='Manual', songs='')
    db.session.add(round_obj)
    db.session.flush()
    return round_obj


def test_notification_admin_summary_counts_actionable_items(app):
    now = datetime(2026, 7, 8, 10, 0, 0)
    with app.app_context():
        user = _make_user(
            spotify_id='spotify-user',
            spotify_token=None,
            spotify_refresh_token=None,
            spotify_token_expiry=None,
        )
        round_obj = _make_round()
        db.session.add(
            RoundExport(
                round_id=round_obj.id,
                user_id=user.id,
                export_type='email',
                status='failed',
                timestamp=now - timedelta(hours=1),
                error_message='Round quality gate failed: token=secret',
            )
        )
        db.session.add(
            ImportJobRecord(
                service_name='spotify',
                item_type='playlist',
                item_id='secret-playlist-id',
                user_id=user.id,
                status='dead_letter',
                completed_at=now - timedelta(minutes=20),
                attempt_count=3,
                error_message='provider token=secret',
            )
        )
        db.session.commit()

        summary = notification_admin_summary(
            now=now,
            window_hours=24,
            include_operational_health=False,
        )

    assert summary['oauth_token_candidate_count'] == 1
    assert summary['failed_round_export_count'] == 1
    assert summary['dead_letter_import_count'] == 1
    assert summary['actionable_count'] == 3
    assert 'token=secret' not in str(summary)
    assert 'secret-playlist-id' not in str(summary)


def test_send_notification_admin_summary_dry_run_does_not_send(app):
    with app.app_context():
        app.config['MAIL_RECIPIENT'] = 'admin@example.test'

        with patch('musicround.helpers.notification_summary.send_email') as mock_send:
            result = send_notification_admin_summary(
                dry_run=True,
                include_operational_health=False,
            )

    assert result['dry_run'] is True
    assert result['recipient'] == 'admin@example.test'
    assert result['sent'] is False
    mock_send.assert_not_called()


def test_send_notification_admin_summary_sends_when_requested(app):
    with app.app_context():
        app.config['MAIL_RECIPIENT'] = 'admin@example.test'

        with patch('musicround.helpers.notification_summary.send_email') as mock_send:
            mock_send.return_value = (True, 'sent')
            result = send_notification_admin_summary(
                dry_run=False,
                include_operational_health=False,
            )

    assert result['sent'] is True
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs['recipient'] == 'admin@example.test'
    assert kwargs['subject'] == 'Quizzical Beats notification summary'


def test_notification_admin_summary_includes_operational_health(app):
    with app.app_context():
        health_payload = {
            "ok": False,
            "status": "error",
            "services": {
                "database": {
                    "issues": [
                        {
                            "code": "database_unavailable",
                            "severity": "error",
                            "message": "Database health probe failed.",
                            "details": {
                                "hint": "Check database connectivity.",
                                "secret": "redaction-fixture",
                            },
                        }
                    ]
                }
            },
        }
        backup_payload = {
            "ok": False,
            "status": "error",
            "issues": [
                {
                    "code": "managed_database_requires_external_backup",
                    "severity": "error",
                    "message": "Application backup and restore only support SQLite.",
                    "hint": "Use managed database snapshots.",
                }
            ],
        }

        with patch(
            'musicround.helpers.notification_summary._safe_operational_health',
            return_value={
                "service_health": health_payload,
                "backup_readiness": backup_payload,
            },
        ):
            with patch(
                'musicround.helpers.notification_summary.send_email'
            ) as mock_send:
                mock_send.return_value = (True, 'sent')
                result = send_notification_admin_summary(dry_run=False)

    summary = result['summary']
    assert summary['service_health_issue_count'] == 1
    assert summary['backup_readiness_issue_count'] == 1
    assert summary['actionable_count'] == 2
    assert summary['service_health_issues'][0]['service'] == 'database'
    assert "redaction-fixture" not in str(summary)
    body = mock_send.call_args.kwargs['body_text']
    assert "Service health issues: 1" in body
    assert "Backup readiness issues: 1" in body
    assert "managed_database_requires_external_backup" in body
    assert "redaction-fixture" not in body
