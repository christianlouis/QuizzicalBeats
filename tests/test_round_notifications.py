"""Tests for blocked round notification emails."""

from datetime import datetime, timedelta
from unittest.mock import patch

from musicround.helpers.round_notifications import send_round_blocked_notification
from musicround.models import Round, SystemSetting, User, UserPreferences, db


def _make_user(username='blockeduser', email='blocked@example.test'):
    user = User(username=username, email=email)
    user.password = 'BlockedPass123!'
    db.session.add(user)
    db.session.flush()
    return user


def _make_round(name='Blocked Round'):
    round_obj = Round(name=name, round_type='random', round_criteria_used='Random', songs='')
    db.session.add(round_obj)
    db.session.flush()
    return round_obj


def _quality():
    return {
        'ok': False,
        'status': 'needs_substitution',
        'hints': ['Position 1 has no playable preview token=secret-value.'],
        'report': {
            'headline': 'Blocked Round is blocked: needs_substitution.',
            'markdown': '# Blocked Round is blocked\n\nReplace position 1.',
        },
    }


def test_send_round_blocked_notification_sends_secret_free_repair_mail(app):
    with app.app_context():
        user = _make_user()
        round_obj = _make_round()
        db.session.commit()

        with patch('musicround.helpers.round_notifications.send_email') as mock_send:
            mock_send.return_value = (True, 'sent')
            result = send_round_blocked_notification(
                user=user,
                round_id=round_obj.id,
                quality=_quality(),
                now=datetime(2026, 7, 8, 10, 0, 0),
            )

        assert result == {'sent': True, 'skipped': False, 'reason': None}
        kwargs = mock_send.call_args.kwargs
        assert kwargs['recipient'] == 'blocked@example.test'
        assert kwargs['subject'] == 'Quizzical Beats: Blocked Round needs repair'
        assert 'Replace position 1.' in kwargs['body_text']
        assert 'token=secret-value' not in kwargs['body_text']
        assert 'token=[redacted]' in kwargs['body_text']


def test_send_round_blocked_notification_respects_opt_out(app):
    with app.app_context():
        user = _make_user('optoutround', 'optoutround@example.test')
        round_obj = _make_round('Opt-out Round')
        db.session.add(
            UserPreferences(
                user_id=user.id,
                round_blocked_email_notifications=False,
            )
        )
        db.session.commit()

        with patch('musicround.helpers.round_notifications.send_email') as mock_send:
            result = send_round_blocked_notification(
                user=user,
                round_id=round_obj.id,
                quality=_quality(),
            )

        assert result['reason'] == 'preference_disabled'
        mock_send.assert_not_called()


def test_send_round_blocked_notification_deduplicates_successful_sends(app):
    now = datetime(2026, 7, 8, 10, 0, 0)
    with app.app_context():
        user = _make_user('deduperound', 'deduperound@example.test')
        round_obj = _make_round('Dedupe Round')
        db.session.commit()

        with patch('musicround.helpers.round_notifications.send_email') as mock_send:
            mock_send.return_value = (True, 'sent')
            first = send_round_blocked_notification(
                user=user,
                round_id=round_obj.id,
                quality=_quality(),
                now=now,
            )
            second = send_round_blocked_notification(
                user=user,
                round_id=round_obj.id,
                quality=_quality(),
                now=now + timedelta(minutes=30),
            )

        assert first['sent'] is True
        assert second['reason'] == 'deduplicated'
        mock_send.assert_called_once()
        assert SystemSetting.query.filter(SystemSetting.key.like('notification:round-blocked:%')).count() == 1
