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
            spotify_token='secret-access-token',
            spotify_refresh_token='secret-refresh-token',
            spotify_token_expiry=now + timedelta(minutes=5),
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

        summary = notification_admin_summary(now=now, window_hours=24)

    assert summary['oauth_token_candidate_count'] == 1
    assert summary['failed_round_export_count'] == 1
    assert summary['dead_letter_import_count'] == 1
    assert summary['actionable_count'] == 3
    assert 'secret-access-token' not in str(summary)
    assert 'token=secret' not in str(summary)
    assert 'secret-playlist-id' not in str(summary)


def test_send_notification_admin_summary_dry_run_does_not_send(app):
    with app.app_context():
        app.config['MAIL_RECIPIENT'] = 'admin@example.test'

        with patch('musicround.helpers.notification_summary.send_email') as mock_send:
            result = send_notification_admin_summary(dry_run=True)

    assert result['dry_run'] is True
    assert result['recipient'] == 'admin@example.test'
    assert result['sent'] is False
    mock_send.assert_not_called()


def test_send_notification_admin_summary_sends_when_requested(app):
    with app.app_context():
        app.config['MAIL_RECIPIENT'] = 'admin@example.test'

        with patch('musicround.helpers.notification_summary.send_email') as mock_send:
            mock_send.return_value = (True, 'sent')
            result = send_notification_admin_summary(dry_run=False)

    assert result['sent'] is True
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs['recipient'] == 'admin@example.test'
    assert kwargs['subject'] == 'Quizzical Beats notification summary'
