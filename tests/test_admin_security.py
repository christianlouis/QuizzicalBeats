"""Security tests for Flask-Admin views."""

from musicround.models import SystemSetting, User, db


SENSITIVE_USER_VALUES = [
    'spotify-access-secret',
    'spotify-refresh-secret',
    'google-access-secret',
    'google-refresh-secret',
    'authentik-access-secret',
    'authentik-refresh-secret',
    'dropbox-access-secret',
    'dropbox-refresh-secret',
    'password-reset-secret',
]


def _login_admin(app, client):
    with app.app_context():
        admin = User(username='admin_security', email='admin_security@example.com', is_admin=True)
        admin.password = 'AdminPass123!'
        db.session.add(admin)
        db.session.commit()

    client.post('/users/login', data={'username': 'admin_security', 'password': 'AdminPass123!'})


def _create_sensitive_user(app):
    with app.app_context():
        user = User(
            username='token_user',
            email='token_user@example.com',
            spotify_token='spotify-access-secret',
            spotify_refresh_token='spotify-refresh-secret',
            google_token='google-access-secret',
            google_refresh_token='google-refresh-secret',
            authentik_token='authentik-access-secret',
            authentik_refresh_token='authentik-refresh-secret',
            dropbox_token='dropbox-access-secret',
            dropbox_refresh_token='dropbox-refresh-secret',
            reset_token='password-reset-secret',
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _assert_values_absent(response, values):
    body = response.get_data(as_text=True)
    for value in values:
        assert value not in body


def test_admin_user_list_details_and_export_hide_oauth_tokens(app, client):
    _login_admin(app, client)
    user_id = _create_sensitive_user(app)

    list_response = client.get('/admin/user/')
    details_response = client.get(f'/admin/user/details/?id={user_id}')
    csv_export_response = client.get('/admin/user/export/csv/', buffered=True)
    json_export_response = client.get('/admin/user/export/json/', buffered=True)

    assert list_response.status_code == 200
    assert details_response.status_code == 200
    assert csv_export_response.status_code == 200
    assert json_export_response.status_code in (302, 404)
    _assert_values_absent(list_response, SENSITIVE_USER_VALUES)
    _assert_values_absent(details_response, SENSITIVE_USER_VALUES)
    _assert_values_absent(csv_export_response, SENSITIVE_USER_VALUES)
    _assert_values_absent(json_export_response, SENSITIVE_USER_VALUES)


def test_admin_system_settings_list_and_export_hide_values(app, client):
    _login_admin(app, client)
    with app.app_context():
        SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-secret')
        setting_id = SystemSetting.query.filter_by(key='fallback_spotify_refresh_token').one().id

    list_response = client.get('/admin/systemsetting/')
    details_response = client.get(f'/admin/systemsetting/details/?id={setting_id}')
    csv_export_response = client.get('/admin/systemsetting/export/csv/', buffered=True)

    assert list_response.status_code == 200
    assert details_response.status_code == 200
    assert csv_export_response.status_code == 200
    _assert_values_absent(list_response, ['system-refresh-secret'])
    _assert_values_absent(details_response, ['system-refresh-secret'])
    _assert_values_absent(csv_export_response, ['system-refresh-secret'])


def test_system_settings_page_hides_fallback_refresh_token_value(app, client):
    _login_admin(app, client)
    with app.app_context():
        SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-secret')

    response = client.get('/users/system-settings')

    assert response.status_code == 200
    _assert_values_absent(response, ['system-refresh-secret'])
    assert 'Refresh token stored' in response.get_data(as_text=True)


def test_system_settings_empty_fallback_token_keeps_existing_value(app, client):
    _login_admin(app, client)
    with app.app_context():
        SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-secret')

    response = client.post('/users/system-settings', data={
        'fallback_spotify_refresh_token': '',
        'default_tts_service': '',
        'default_tts_voice': '',
        'default_tts_model': '',
        'spotify_region': 'DE',
        'max_songs_per_round': '8',
        'enable_public_rounds': 'true',
        'allow_signups': 'true',
    })

    assert response.status_code == 302
    with app.app_context():
        assert SystemSetting.get('fallback_spotify_refresh_token') == 'system-refresh-secret'
        assert SystemSetting.get('spotify_region') == 'DE'


def test_system_settings_can_replace_and_clear_fallback_refresh_token(app, client):
    _login_admin(app, client)
    with app.app_context():
        SystemSetting.set('fallback_spotify_refresh_token', 'system-refresh-secret')

    replace_response = client.post('/users/system-settings', data={
        'fallback_spotify_refresh_token': 'new-system-refresh-secret',
        'default_tts_service': '',
        'default_tts_voice': '',
        'default_tts_model': '',
        'spotify_region': '',
        'max_songs_per_round': '8',
        'allow_signups': 'true',
    })

    assert replace_response.status_code == 302
    with app.app_context():
        assert SystemSetting.get('fallback_spotify_refresh_token') == 'new-system-refresh-secret'

    clear_response = client.post('/users/system-settings', data={
        'fallback_spotify_refresh_token': '',
        'clear_fallback_spotify_refresh_token': 'true',
        'default_tts_service': '',
        'default_tts_voice': '',
        'default_tts_model': '',
        'spotify_region': '',
        'max_songs_per_round': '8',
        'allow_signups': 'true',
    })

    assert clear_response.status_code == 302
    with app.app_context():
        assert SystemSetting.get('fallback_spotify_refresh_token') == ''
