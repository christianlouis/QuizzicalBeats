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


def test_exchange_code_for_token_uses_timeout_and_hides_network_errors(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.side_effect = dropbox_helper.requests.Timeout('provider timeout old-dropbox-code')

            result = dropbox_helper.exchange_code_for_token('old-dropbox-code')

        assert result is None
        assert mock_post.call_args.kwargs['timeout'] == dropbox_helper.DROPBOX_API_TIMEOUT_SECONDS


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


def test_dropbox_refresh_if_needed_unexpected_error_returns_safe_message(app):
    with app.test_request_context('/'):
        user = _make_dropbox_user()
        with patch('musicround.helpers.dropbox_helper.refresh_dropbox_token') as mock_refresh:
            mock_refresh.side_effect = RuntimeError('provider-secret-body old-dropbox-refresh')

            result = dropbox_helper.refresh_dropbox_token_if_needed(user)

        assert result == {
            'success': False,
            'message': dropbox_helper.DROPBOX_REFRESH_ERROR_MESSAGE,
        }
        assert 'provider-secret-body' not in result['message']
        assert user.dropbox_refresh_token == 'old-dropbox-refresh'


def test_upload_to_dropbox_hides_provider_error_body(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                409,
                text='provider-secret-body old-dropbox-access traceback',
            )

            result = dropbox_helper.upload_to_dropbox(
                'old-dropbox-access',
                '/rounds/secret.json',
                '{}',
                mode='text',
            )

        assert result == {
            'success': False,
            'message': dropbox_helper.DROPBOX_UPLOAD_ERROR_MESSAGE,
            'status_code': 409,
        }
        assert mock_post.call_args.kwargs['timeout'] == dropbox_helper.DROPBOX_API_TIMEOUT_SECONDS
        assert 'provider-secret-body' not in result['message']
        assert 'old-dropbox-access' not in result['message']


def test_upload_to_dropbox_hides_exception_text(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.side_effect = RuntimeError('provider-secret-body old-dropbox-access')

            result = dropbox_helper.upload_to_dropbox(
                'old-dropbox-access',
                '/rounds/secret.json',
                b'{}',
            )

        assert result == {
            'success': False,
            'message': dropbox_helper.DROPBOX_UPLOAD_ERROR_MESSAGE,
        }


def test_create_shared_link_hides_provider_error_body(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.return_value = _make_response(
                500,
                text='provider-secret-body old-dropbox-access traceback',
            )

            result = dropbox_helper.create_shared_link(
                'old-dropbox-access',
                '/rounds/secret.pdf',
            )

        assert result == {
            'success': False,
            'message': dropbox_helper.DROPBOX_SHARED_LINK_ERROR_MESSAGE,
            'status_code': 500,
        }
        assert mock_post.call_args.kwargs['timeout'] == dropbox_helper.DROPBOX_API_TIMEOUT_SECONDS
        assert 'provider-secret-body' not in result['message']
        assert 'old-dropbox-access' not in result['message']


def test_create_shared_link_hides_exception_text(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.side_effect = RuntimeError('provider-secret-body old-dropbox-access')

            result = dropbox_helper.create_shared_link(
                'old-dropbox-access',
                '/rounds/secret.pdf',
            )

        assert result == {
            'success': False,
            'message': dropbox_helper.DROPBOX_SHARED_LINK_ERROR_MESSAGE,
        }


def test_get_dropbox_account_info_uses_timeout(app):
    with app.app_context():
        with patch('musicround.helpers.dropbox_helper.requests.post') as mock_post:
            mock_post.return_value = _make_response(200, {'account_id': 'dbid:123'})

            result = dropbox_helper.get_dropbox_account_info('old-dropbox-access')

        assert result == {'account_id': 'dbid:123'}
        assert mock_post.call_args.kwargs['timeout'] == dropbox_helper.DROPBOX_API_TIMEOUT_SECONDS
