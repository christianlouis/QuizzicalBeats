"""Tests for the OAuth debug diagnostics route."""

from musicround.models import User, db


def _login(app, client, username='oauth_debug_user', is_admin=False):
    with app.app_context():
        user = User(
            username=username,
            email=f'{username}@example.com',
            is_admin=is_admin,
        )
        user.password = 'DebugPass123!'
        db.session.add(user)
        db.session.commit()

    client.post('/users/login', data={'username': username, 'password': 'DebugPass123!'})


def test_oauth_debug_route_is_disabled_by_default(app, client):
    """OAuth diagnostics should not be reachable unless explicitly enabled."""
    _login(app, client, is_admin=True)

    response = client.get('/debug/oauth-urls?format=json')

    assert response.status_code == 404


def test_oauth_debug_route_requires_admin_when_enabled(app, client):
    """Enabled OAuth diagnostics should still be admin-only."""
    app.config['ENABLE_OAUTH_DEBUG'] = True
    _login(app, client, username='oauth_debug_nonadmin', is_admin=False)

    response = client.get('/debug/oauth-urls?format=json')

    assert response.status_code == 403


def test_oauth_debug_route_returns_safe_json_for_admin_when_enabled(app, client):
    """Admins can fetch OAuth URL diagnostics after explicit opt-in."""
    app.config['ENABLE_OAUTH_DEBUG'] = True
    _login(app, client, username='oauth_debug_admin', is_admin=True)

    response = client.get('/debug/oauth-urls?format=json')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['config']['USE_HTTPS'] is False
    assert 'helper_generated_urls' in payload
    assert 'direct_url_for_urls' in payload
    assert 'request_info' in payload
