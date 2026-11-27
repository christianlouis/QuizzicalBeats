"""Offline tests for personal Deezer account linking."""

import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from musicround.models import DeezerAccount, User, db


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('provider error')

    def json(self):
        return self.payload


def _logged_in_client(app, client, username='deezer-user'):
    with app.app_context():
        user = User(username=username, email=f'{username}@example.test')
        user.password = 'StrongPassword123!'
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'StrongPassword123!'})
    return user_id


def test_link_deezer_uses_state_and_manage_library(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret',
                      DEEZER_REDIRECT_URI='https://quiz.example/deezer-callback')
    _logged_in_client(app, client)

    response = client.post('/deezer-link', data={'round_id': '27'})
    assert response.status_code == 302
    query = parse_qs(urlparse(response.location).query)
    assert query['perms'] == ['manage_library,delete_library']
    assert query['state']
    with client.session_transaction() as session:
        assert session['deezer_oauth_state']['round_id'] == '27'
        assert session['deezer_oauth_state']['value'] == query['state'][0]
        assert session['deezer_oauth_state']['user_id']


@patch('musicround.routes.deezer_routes.requests.get')
def test_callback_verifies_identity_encrypts_token_and_returns_round(mock_get, app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret',
                      DEEZER_REDIRECT_URI='https://quiz.example/deezer-callback')
    user_id = _logged_in_client(app, client, 'linked-user')
    client.post('/deezer-link', data={'round_id': '27'})
    with client.session_transaction() as session:
        state = session['deezer_oauth_state']['value']
    mock_get.side_effect = [_Response({'access_token': 'private-token', 'expires': '3600'}),
                            _Response({'id': 9911, 'name': 'Quiz User'})]

    response = client.get(f'/deezer-callback?code=one-time-code&state={state}')
    assert response.status_code == 302
    assert response.location.endswith('/rounds/27#streaming-playlists')
    with app.app_context():
        account = DeezerAccount.query.filter_by(user_id=user_id).one()
        assert account.account_id == '9911'
        assert account.access_token_ciphertext != 'private-token'
        assert 'private-token' not in account.access_token_ciphertext


def test_callback_rejects_expired_state(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    _logged_in_client(app, client, 'expired-user')
    client.post('/deezer-link')
    with client.session_transaction() as session:
        session['deezer_oauth_state']['expires_at'] = (datetime.utcnow() - timedelta(seconds=1)).timestamp()
        state = session['deezer_oauth_state']['value']
    response = client.get(f'/deezer-callback?code=code&state={state}')
    assert response.status_code == 302
    with app.app_context():
        assert DeezerAccount.query.count() == 0


def test_callback_consumes_state_on_wrong_state(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    _logged_in_client(app, client, 'wrong-state-user')
    client.post('/deezer-link')
    response = client.get('/deezer-callback?code=code&state=wrong')
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert 'deezer_oauth_state' not in session


def test_callback_handles_unicode_state_without_provider_call(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    _logged_in_client(app, client, 'unicode-state-user')
    client.post('/deezer-link')
    with patch('musicround.routes.deezer_routes.requests.get') as mocked_get:
        response = client.get('/deezer-callback?code=code&state=%C3%A4')
    assert response.status_code == 302
    mocked_get.assert_not_called()


def test_callback_handles_permission_denial_without_provider_call(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    user_id = _logged_in_client(app, client, 'denied-user')
    response = client.post('/deezer-link', data={'round_id': '27'})
    state = parse_qs(urlparse(response.location).query)['state'][0]

    with patch('musicround.routes.deezer_routes.requests.get') as mocked_get:
        callback = client.get(f'/deezer-callback?state={state}&error=access_denied')

    assert callback.status_code == 302
    assert callback.location.endswith('/rounds/27#streaming-playlists')
    mocked_get.assert_not_called()
    with app.app_context():
        assert DeezerAccount.query.filter_by(user_id=user_id).first() is None


def test_callback_rejects_state_after_user_switch_without_provider_call(app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    _logged_in_client(app, client, 'original-user')
    start = client.post('/deezer-link', data={'round_id': '27'})
    state = parse_qs(urlparse(start.location).query)['state'][0]
    client.get('/users/logout')
    _logged_in_client(app, client, 'different-user')

    with patch('musicround.routes.deezer_routes.requests.get') as mocked_get:
        response = client.get(f'/deezer-callback?code=code&state={state}')

    assert response.status_code == 302
    mocked_get.assert_not_called()


def test_unconfigured_link_ignores_external_next(app, client):
    _logged_in_client(app, client, 'safe-next-user')
    response = client.post('/deezer-link', data={'next': 'https://attacker.example/'})
    assert response.status_code == 302
    assert response.location.endswith('/users/profile')


@patch('musicround.routes.deezer_routes.requests.get')
def test_callback_rejects_malformed_provider_identity(mock_get, app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    user_id = _logged_in_client(app, client, 'malformed-provider-user')
    start = client.post('/deezer-link')
    state = parse_qs(urlparse(start.location).query)['state'][0]
    mock_get.side_effect = [_Response({'access_token': 'private-token'}),
                            _Response({'id': 'not-numeric'})]

    response = client.get(f'/deezer-callback?code=code&state={state}')
    assert response.status_code == 302
    with app.app_context():
        assert DeezerAccount.query.filter_by(user_id=user_id).first() is None


@patch('musicround.routes.deezer_routes.requests.get')
def test_callback_handles_invalid_encryption_configuration(mock_get, app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret',
                      DEEZER_TOKEN_ENCRYPTION_KEY='not-a-fernet-key')
    user_id = _logged_in_client(app, client, 'invalid-encryption-user')
    start = client.post('/deezer-link')
    state = parse_qs(urlparse(start.location).query)['state'][0]
    mock_get.side_effect = [_Response({'access_token': 'private-token'}), _Response({'id': 1234})]

    response = client.get(f'/deezer-callback?code=code&state={state}')
    assert response.status_code == 302
    with app.app_context():
        assert DeezerAccount.query.filter_by(user_id=user_id).first() is None


@patch('musicround.routes.deezer_routes.requests.get')
def test_profile_does_not_render_deezer_token_and_disconnects(mock_get, app, client):
    app.config.update(DEEZER_APP_ID='app-id', DEEZER_APP_SECRET='app-secret')
    user_id = _logged_in_client(app, client, 'disconnect-user')
    start = client.post('/deezer-link')
    state = parse_qs(urlparse(start.location).query)['state'][0]
    mock_get.side_effect = [_Response({'access_token': 'private-token'}), _Response({'id': 1234})]
    client.get(f'/deezer-callback?code=code&state={state}')
    profile = client.get('/users/profile')
    assert b'private-token' not in profile.data
    client.post('/deezer-disconnect')
    with app.app_context():
        assert DeezerAccount.query.filter_by(user_id=user_id).first() is None
