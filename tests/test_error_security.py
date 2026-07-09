from musicround import db
from musicround.models import User


def _create_user(app, username, email, password='ErrorPass123!', is_admin=False):
    with app.app_context():
        user = User(username=username, email=email, is_admin=is_admin)
        user.password = password
        db.session.add(user)
        db.session.commit()


def _login(client, username, password='ErrorPass123!'):
    response = client.post(
        '/users/login',
        data={'username': username, 'password': password},
    )
    assert response.status_code == 302
    expected_user_id = str(User.query.filter_by(username=username).one().id)
    with client.session_transaction() as session:
        assert session['_user_id'] == expected_user_id
    return response


def _register_crashing_route(app):
    if 'error_security_crash' in app.view_functions:
        return

    @app.route('/test/error-security-crash', methods=['POST'])
    def error_security_crash():
        raise RuntimeError('synthetic boom for error security tests')


def test_error_page_hides_debug_payload_for_non_admin_user(app, client):
    app.config['PROPAGATE_EXCEPTIONS'] = False
    _register_crashing_route(app)
    _create_user(app, 'error_non_admin', 'error_non_admin@example.com')
    _login(client, 'error_non_admin')

    response = client.post(
        '/test/error-security-crash',
        data={
            'password': 'plain-password-value',
            'remember_token': 'plain-token-value',
            'comment': 'visible-form-comment',
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert 'synthetic boom for error security tests' not in body
    assert 'RuntimeError' not in body
    assert 'Traceback' not in body
    assert 'request_form' not in body
    assert 'plain-password-value' not in body
    assert 'plain-token-value' not in body
    assert 'visible-form-comment' not in body


def test_error_page_redacts_sensitive_form_fields_for_admins(app, client):
    app.config['PROPAGATE_EXCEPTIONS'] = False
    _register_crashing_route(app)
    _create_user(app, 'error_admin', 'error_admin@example.com', is_admin=True)
    _login(client, 'error_admin')

    response = client.post(
        '/test/error-security-crash',
        data={
            'password': 'plain-password-value',
            'api_token': 'plain-token-value',
            'client_secret': 'raw-uri-fixture-value',
            'comment': 'visible-form-comment',
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert 'RuntimeError' in body
    assert 'request_form' in body
    assert 'visible-form-comment' in body
    assert 'plain-password-value' not in body
    assert 'plain-token-value' not in body
    assert 'raw-uri-fixture-value' not in body
    assert '[redacted]' in body


def test_error_page_redacts_sensitive_json_query_and_headers_for_admins(app, client):
    app.config['PROPAGATE_EXCEPTIONS'] = False
    _register_crashing_route(app)
    _create_user(app, 'error_admin_json', 'error_admin_json@example.com', is_admin=True)
    _login(client, 'error_admin_json')

    response = client.post(
        '/test/error-security-crash?access_token=query-token-value&comment=visible-query-comment',
        json={
            'client_secret': 'json-secret-value',
            'nested': {
                'refreshToken': 'json-refresh-token-value',
                'comment': 'visible-json-comment',
            },
            'items': [
                {'api-key': 'json-api-key-value'},
                {'label': 'visible-list-comment'},
            ],
        },
        headers={
            'Authorization': 'Bearer header-token-value',
            'X-Api-Key': 'header-api-key-value',
            'X-Debug-Comment': 'visible-header-comment',
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert 'request_json' in body
    assert 'request_args' in body
    assert 'request_headers' in body
    assert 'visible-query-comment' in body
    assert 'visible-json-comment' in body
    assert 'visible-list-comment' in body
    assert 'visible-header-comment' in body
    assert 'query-token-value' not in body
    assert 'json-secret-value' not in body
    assert 'json-refresh-token-value' not in body
    assert 'json-api-key-value' not in body
    assert 'header-token-value' not in body
    assert 'header-api-key-value' not in body
    assert '[redacted]' in body


def test_friendly_error_api_hides_internal_exception_details(app, client, monkeypatch):
    def fail_friendly_message(error_info, app_obj):
        raise RuntimeError('llm provider token=friendly-secret traceback')

    monkeypatch.setattr('musicround.errors.generate_friendly_error_message', fail_friendly_message)

    response = client.post(
        '/api/friendly-error',
        json={
            'error_type': 'RuntimeError',
            'error_message': 'boom',
            'code': 500,
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert response.get_json() == {
        'success': False,
        'message': 'Could not generate a friendly message',
    }
    assert 'friendly-secret' not in body
    assert 'provider token' not in body
    assert 'traceback' not in body
