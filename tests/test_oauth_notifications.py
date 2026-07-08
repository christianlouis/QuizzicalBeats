"""Tests for OAuth token email notifications."""

from datetime import datetime, timedelta
from unittest.mock import patch

from musicround.helpers.oauth_notifications import (
    collect_oauth_token_notifications,
    send_oauth_token_notifications,
)
from musicround.models import SystemSetting, User, UserPreferences, db


def _make_user(username, email, **kwargs):
    user = User(username=username, email=email, **kwargs)
    user.password = 'TokenNotifyPass123!'
    db.session.add(user)
    db.session.flush()
    return user


def test_collect_oauth_token_notifications_respects_preferences_and_redacts_tokens(app):
    now = datetime(2026, 7, 8, 10, 0, 0)
    with app.app_context():
        _make_user(
            'spotifywarn',
            'spotifywarn@example.test',
            spotify_id='spotify-user',
            spotify_token='secret-access-token',
            spotify_refresh_token='secret-refresh-token',
            spotify_token_expiry=now + timedelta(minutes=5),
        )
        opted_out = _make_user(
            'dropboxoptout',
            'dropboxoptout@example.test',
            dropbox_id='dropbox-user',
            dropbox_token='dropbox-access-secret',
            dropbox_refresh_token='dropbox-refresh-secret',
            dropbox_token_expiry=now - timedelta(minutes=1),
        )
        db.session.add(
            UserPreferences(
                user_id=opted_out.id,
                oauth_token_email_notifications=False,
            )
        )
        db.session.commit()

        notifications = collect_oauth_token_notifications(now=now)

    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.recipient == 'spotifywarn@example.test'
    assert notification.service == 'spotify'
    assert notification.issue_code == 'spotify_token_expiring'
    assert len(notification.dedupe_key) <= 64
    assert 'secret-access-token' not in notification.body_text
    assert 'secret-refresh-token' not in notification.body_text
    assert 'secret-access-token' not in repr(notification)
    assert 'secret-refresh-token' not in repr(notification)


def test_send_oauth_token_notifications_deduplicates_successful_sends(app):
    now = datetime(2026, 7, 8, 10, 0, 0)
    with app.app_context():
        _make_user(
            'dropboxwarn',
            'dropboxwarn@example.test',
            dropbox_id='dropbox-user',
            dropbox_token='dropbox-access-secret',
            dropbox_refresh_token='dropbox-refresh-secret',
            dropbox_token_expiry=now - timedelta(minutes=1),
        )
        db.session.commit()

        with patch('musicround.helpers.oauth_notifications.send_email') as mock_send:
            mock_send.return_value = (True, 'sent')
            first = send_oauth_token_notifications(now=now, dry_run=False)
            second = send_oauth_token_notifications(now=now + timedelta(minutes=30), dry_run=False)

        assert first['candidate_count'] == 1
        assert first['sent_count'] == 1
        assert second['candidate_count'] == 0
        assert second['sent_count'] == 0
        mock_send.assert_called_once()
        assert SystemSetting.query.filter(SystemSetting.key.like('notification:oauth-token:%')).count() == 1


def test_send_oauth_token_notifications_dry_run_does_not_send_or_mark(app):
    now = datetime(2026, 7, 8, 10, 0, 0)
    with app.app_context():
        _make_user(
            'dryrunspotify',
            'dryrunspotify@example.test',
            spotify_id='spotify-user',
            spotify_token='spotify-access-secret',
            spotify_refresh_token='spotify-refresh-secret',
            spotify_token_expiry=now + timedelta(minutes=5),
        )
        db.session.commit()

        with patch('musicround.helpers.oauth_notifications.send_email') as mock_send:
            result = send_oauth_token_notifications(now=now, dry_run=True)

        assert result['dry_run'] is True
        assert result['candidate_count'] == 1
        assert result['sent_count'] == 0
        mock_send.assert_not_called()
        assert SystemSetting.query.filter(SystemSetting.key.like('notification:oauth-token:%')).count() == 0
