"""Tests for process blueprint routes."""
import base64

from musicround.models import User, db


def _login(app, client):
    """Create and log in a user."""
    with app.app_context():
        user = User.query.filter_by(username='processtest').first()
        if not user:
            user = User(username='processtest', email='processtest@example.com')
            user.password = 'ProcessPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={
        'username': 'processtest',
        'password': 'ProcessPass123!',
    })


class TestProcessRoutes:
    """Tests for process blueprint routes."""

    def test_base64_encode_requires_login(self, client):
        response = client.post('/process/base64', data=b'some data')

        assert response.status_code in (302, 401)
        if response.status_code == 302:
            assert 'login' in response.headers.get('Location', '').lower()

    def test_base64_encode_no_data(self, app, client):
        _login(app, client)

        response = client.post('/process/base64', data=b'')

        assert response.status_code == 400
        assert response.get_json() == {'error': 'No data provided'}

    def test_base64_encode_success(self, app, client):
        _login(app, client)
        test_data = b'Hello, world! 123 \x00\x01\x02'
        expected_encoded = base64.b64encode(test_data).decode('utf-8')

        response = client.post('/process/base64', data=test_data)

        assert response.status_code == 200
        assert response.get_json() == {'encoded': expected_encoded}
