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
            'client_secret': 'plain-secret-value',
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
    assert 'plain-secret-value' not in body
    assert '[redacted]' in body
