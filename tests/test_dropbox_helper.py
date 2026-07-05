"""Tests for Dropbox token refresh failure handling."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from musicround.helpers import dropbox_helper
from musicround.helpers.dropbox_helper import DropboxTokenRevokedError
from musicround.models import User, db


def _make_response(status_code, json_body=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text or str(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


def _make_dropbox_user():
    user = User(username='dropboxuser', email='dropboxuser@example.com')
    user.dropbox_token = 'old-dropbox-access'
    user.dropbox_refresh_token = 'old-dropbox-refresh'
    user.dropbox_token_expiry = datetime.now() - timedelta(minutes=10)
    user.dropbox_id = 'dropbox-account'
    db.session.add(user)
    db.session.commit()
    return user


def test_refresh_dropbox_token_raises_on_invalid_grant(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                400,
                {'error': 'invalid_grant', 'error_description': 'revoked'},
            )

            with pytest.raises(DropboxTokenRevokedError):
                dropbox_helper.refresh_dropbox_token('old-refresh')

            assert mock_post.call_args.kwargs['timeout'] == 10


def test_refresh_dropbox_token_keeps_transient_failures_retryable(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.return_value = _make_response(500, text='server error')

            assert dropbox_helper.refresh_dropbox_token('old-refresh') is None


def test_current_user_dropbox_invalid_grant_clears_tokens_and_flashes(app):
    with app.test_request_context('/'):
        user = _make_dropbox_user()
        with patch('musicround.helpers.dropbox_helper.current_user', user), \
                patch('musicround.helpers.dropbox_helper.refresh_dropbox_token') as mock_refresh:
            mock_refresh.side_effect = DropboxTokenRevokedError("invalid_grant")

            result = dropbox_helper.get_current_user_dropbox_token()

        assert result is None
        assert user.dropbox_token is None
        assert user.dropbox_refresh_token is None
        assert user.dropbox_token_expiry is None
        assert user.dropbox_id == 'dropbox-account'

        from flask import get_flashed_messages
        assert any('reconnect dropbox' in message.lower() for message in get_flashed_messages())


def test_dropbox_refresh_if_needed_invalid_grant_returns_reconnect_payload(app):
    with app.test_request_context('/'):
        user = _make_dropbox_user()
        with patch('musicround.helpers.dropbox_helper.refresh_dropbox_token') as mock_refresh:
            mock_refresh.side_effect = DropboxTokenRevokedError("invalid_grant")

            result = dropbox_helper.refresh_dropbox_token_if_needed(user)

        assert result == {
            'success': False,
            'message': 'Dropbox connection expired. Please reconnect Dropbox.',
            'reconnect_required': True,
        }
        assert user.dropbox_token is None
        assert user.dropbox_refresh_token is None
        assert user.dropbox_token_expiry is None


def test_dropbox_refresh_if_needed_transient_failure_keeps_refresh_token(app):
    with app.test_request_context('/'):
        user = _make_dropbox_user()
        with patch('musicround.helpers.dropbox_helper.refresh_dropbox_token') as mock_refresh:
            mock_refresh.return_value = None

            result = dropbox_helper.refresh_dropbox_token_if_needed(user)

        assert result == {'success': False, 'message': 'Failed to refresh token'}
        assert user.dropbox_refresh_token == 'old-dropbox-refresh'
