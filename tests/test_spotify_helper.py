"""Tests for Spotify token refresh handling, in particular invalid_grant.

Spotify refresh tokens expire after six months starting 2026-07-20. A refresh
call that fails with invalid_grant must discard the stored token instead of
being retried (see musicround/helpers/spotify_helper.py).
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from musicround.helpers import spotify_helper
from musicround.helpers.spotify_helper import SpotifyTokenRevokedError
from musicround.models import User, SystemSetting, db


def _make_response(status_code, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or str(json_body)
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


class TestRefreshSpotifyToken:
    def test_success_returns_token_info(self, app):
        with app.app_context():
            app.config['SPOTIFY_CLIENT_ID'] = 'cid'
            app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
            with patch('musicround.helpers.spotify_helper.requests.post') as mock_post:
                mock_post.return_value = _make_response(200, {'access_token': 'new-token', 'expires_in': 3600})
                result = spotify_helper.refresh_spotify_token('refresh-token')
                assert result['access_token'] == 'new-token'

    def test_invalid_grant_raises_revoked_error(self, app):
        with app.app_context():
            app.config['SPOTIFY_CLIENT_ID'] = 'cid'
            app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
            with patch('musicround.helpers.spotify_helper.requests.post') as mock_post:
                mock_post.return_value = _make_response(
                    400, {'error': 'invalid_grant', 'error_description': 'Refresh token revoked'}
                )
                with pytest.raises(SpotifyTokenRevokedError):
                    spotify_helper.refresh_spotify_token('refresh-token')

    def test_transient_5xx_returns_none_not_raises(self, app):
        with app.app_context():
            app.config['SPOTIFY_CLIENT_ID'] = 'cid'
            app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
            with patch('musicround.helpers.spotify_helper.requests.post') as mock_post:
                mock_post.return_value = _make_response(500, text="Internal Server Error")
                result = spotify_helper.refresh_spotify_token('refresh-token')
                assert result is None

    def test_network_error_returns_none(self, app):
        import requests
        with app.app_context():
            app.config['SPOTIFY_CLIENT_ID'] = 'cid'
            app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
            with patch('musicround.helpers.spotify_helper.requests.post') as mock_post:
                mock_post.side_effect = requests.exceptions.Timeout("timed out")
                result = spotify_helper.refresh_spotify_token('refresh-token')
                assert result is None

    def test_other_400_error_returns_none(self, app):
        """A 400 that isn't invalid_grant (e.g. invalid_request) should not raise."""
        with app.app_context():
            app.config['SPOTIFY_CLIENT_ID'] = 'cid'
            app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
            with patch('musicround.helpers.spotify_helper.requests.post') as mock_post:
                mock_post.return_value = _make_response(400, {'error': 'invalid_request'})
                result = spotify_helper.refresh_spotify_token('refresh-token')
                assert result is None


class TestGetCurrentUserSpotifyToken:
    def _create_user(self, expired=True):
        user = User(username='quizmaster', email='qm@example.com')
        user.spotify_token = 'old-access-token'
        user.spotify_refresh_token = 'old-refresh-token'
        user.spotify_id = 'spotify-user-1'
        user.spotify_token_expiry = (
            datetime.now() - timedelta(minutes=10) if expired
            else datetime.now() + timedelta(hours=1)
        )
        db.session.add(user)
        db.session.commit()
        return user

    def test_invalid_grant_clears_user_tokens_and_flashes(self, app):
        with app.test_request_context('/'):
            user = self._create_user(expired=True)
            with patch('musicround.helpers.spotify_helper.current_user', user), \
                 patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")

                result = spotify_helper.get_current_user_spotify_token()

                assert result is None
                assert user.spotify_token is None
                assert user.spotify_refresh_token is None
                assert user.spotify_token_expiry is None
                # spotify_id is preserved so the linked-account identity survives
                assert user.spotify_id == 'spotify-user-1'

                from flask import get_flashed_messages
                messages = get_flashed_messages()
                assert any('reconnect' in m.lower() for m in messages)

    def test_invalid_grant_does_not_retry(self, app):
        """A discarded refresh token must not be retried on the next call."""
        with app.test_request_context('/'):
            user = self._create_user(expired=True)
            with patch('musicround.helpers.spotify_helper.current_user', user), \
                 patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")
                spotify_helper.get_current_user_spotify_token()
                assert mock_refresh.call_count == 1

            # Second call: refresh_token is gone, so refresh must not be attempted again.
            with patch('musicround.helpers.spotify_helper.current_user', user), \
                 patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh_2:
                result = spotify_helper.get_current_user_spotify_token()
                assert result is None
                mock_refresh_2.assert_not_called()

    def test_transient_failure_keeps_refresh_token(self, app):
        with app.test_request_context('/'):
            user = self._create_user(expired=True)
            with patch('musicround.helpers.spotify_helper.current_user', user), \
                 patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.return_value = None  # transient failure

                result = spotify_helper.get_current_user_spotify_token()

                assert result is None
                assert user.spotify_refresh_token == 'old-refresh-token'

    def test_successful_refresh_updates_token(self, app):
        with app.test_request_context('/'):
            user = self._create_user(expired=True)
            with patch('musicround.helpers.spotify_helper.current_user', user), \
                 patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.return_value = {'access_token': 'new-token', 'expires_in': 3600}

                result = spotify_helper.get_current_user_spotify_token()

                assert result == 'new-token'
                assert user.spotify_token == 'new-token'


class TestGetSystemSpotifyToken:
    def test_invalid_grant_clears_system_settings(self, app):
        with app.app_context():
            SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-token')
            SystemSetting.set('system_spotify_token', 'stale-token')
            SystemSetting.set('system_spotify_token_expiry', (datetime.now() - timedelta(hours=1)).isoformat())

            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")

                result = spotify_helper.get_system_spotify_token()

                assert result is None
                assert SystemSetting.get('fallback_spotify_refresh_token', '') == ''
                assert SystemSetting.get('system_spotify_token', '') == ''
                assert SystemSetting.get('system_spotify_token_expiry', '') == ''

    def test_invalid_grant_does_not_retry(self, app):
        with app.app_context():
            SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-token')

            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")
                spotify_helper.get_system_spotify_token()

            # Fallback token was cleared, so a subsequent call must not refresh again.
            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh_2:
                result = spotify_helper.get_system_spotify_token()
                assert result is None
                mock_refresh_2.assert_not_called()

    def test_transient_failure_keeps_fallback_token(self, app):
        with app.app_context():
            SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-token')

            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.return_value = None

                result = spotify_helper.get_system_spotify_token()

                assert result is None
                assert SystemSetting.get('fallback_spotify_refresh_token', '') == 'system-refresh-token'


class TestRefreshSpotifyTokenIfNeeded:
    def test_invalid_grant_returns_none_tuple(self, app):
        with app.app_context():
            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                mock_refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")

                result = spotify_helper.refresh_spotify_token_if_needed(
                    'old-token', 'old-refresh', datetime.now() - timedelta(minutes=10)
                )

                assert result == (None, None, None)

    def test_still_valid_token_is_returned_without_refresh(self, app):
        with app.app_context():
            expiry = datetime.now() + timedelta(hours=1)
            with patch('musicround.helpers.spotify_helper.refresh_spotify_token') as mock_refresh:
                result = spotify_helper.refresh_spotify_token_if_needed('token', 'refresh', expiry)
                assert result == ('token', 'refresh', expiry)
                mock_refresh.assert_not_called()


class TestManualSpotifyBearerToken:
    """A user can temporarily supply their own bearer token (e.g. extracted
    from a Spotify web session) to use instead of this app's own tokens.
    """

    def test_no_token_in_session_returns_none(self, app):
        with app.test_request_context('/'):
            assert spotify_helper.get_manual_spotify_bearer_token() is None

    def test_fresh_token_is_returned(self, app):
        with app.test_request_context('/'):
            from flask import session
            session['access_token'] = 'manually-extracted-token'
            session['bearer_token_added'] = datetime.now().timestamp()
            assert spotify_helper.get_manual_spotify_bearer_token() == 'manually-extracted-token'

    def test_expired_token_is_ignored(self, app):
        with app.test_request_context('/'):
            from flask import session
            session['access_token'] = 'stale-token'
            session['bearer_token_added'] = (datetime.now() - timedelta(hours=2)).timestamp()
            assert spotify_helper.get_manual_spotify_bearer_token() is None

    def test_token_without_timestamp_is_trusted(self, app):
        """Defensive: a token set without bearer_token_added shouldn't be dropped."""
        with app.test_request_context('/'):
            from flask import session
            session['access_token'] = 'manually-extracted-token'
            assert spotify_helper.get_manual_spotify_bearer_token() == 'manually-extracted-token'


class TestGetSpotifyTokenPriority:
    """get_spotify_token() must prefer: manual session token > user's own
    token > system fallback token, so a user can override both the app-wide
    fallback and their own linked account with a token they supply themselves.
    """

    def test_manual_token_wins_over_user_and_system(self, app):
        with app.test_request_context('/'):
            from flask import session
            session['access_token'] = 'manual-token'
            session['bearer_token_added'] = datetime.now().timestamp()

            with patch('musicround.helpers.spotify_helper.get_current_user_spotify_token') as mock_user, \
                 patch('musicround.helpers.spotify_helper.get_system_spotify_token') as mock_system:
                mock_user.return_value = 'user-token'
                mock_system.return_value = 'system-token'

                token, source = spotify_helper.get_spotify_token()

                assert (token, source) == ('manual-token', 'manual')
                mock_user.assert_not_called()
                mock_system.assert_not_called()

    def test_user_token_wins_over_system_when_no_manual_token(self, app):
        with app.test_request_context('/'):
            with patch('musicround.helpers.spotify_helper.get_current_user_spotify_token') as mock_user, \
                 patch('musicround.helpers.spotify_helper.get_system_spotify_token') as mock_system:
                mock_user.return_value = 'user-token'
                mock_system.return_value = 'system-token'

                token, source = spotify_helper.get_spotify_token()

                assert (token, source) == ('user-token', 'user')
                mock_system.assert_not_called()

    def test_system_token_used_when_no_manual_or_user_token(self, app):
        with app.test_request_context('/'):
            with patch('musicround.helpers.spotify_helper.get_current_user_spotify_token') as mock_user, \
                 patch('musicround.helpers.spotify_helper.get_system_spotify_token') as mock_system:
                mock_user.return_value = None
                mock_system.return_value = 'system-token'

                token, source = spotify_helper.get_spotify_token()

                assert (token, source) == ('system-token', 'system')

    def test_none_when_nothing_available(self, app):
        with app.test_request_context('/'):
            with patch('musicround.helpers.spotify_helper.get_current_user_spotify_token') as mock_user, \
                 patch('musicround.helpers.spotify_helper.get_system_spotify_token') as mock_system:
                mock_user.return_value = None
                mock_system.return_value = None

                token, source = spotify_helper.get_spotify_token()

                assert (token, source) == (None, 'none')
