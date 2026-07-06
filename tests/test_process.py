"""Tests for process blueprint routes."""
import base64
import pytest
from musicround.models import db, User

def _login(app, client):
    """Helper: create a user and log in."""
    with app.app_context():
        user = User.query.filter_by(username='authtest').first()
        if not user:
            user = User(username='authtest', email='authtest@example.com')
            user.password = 'TestPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={
        'username': 'authtest',
        'password': 'TestPass123!',
    })

class TestProcessRoutes:
    """Tests for process blueprint routes."""

    def test_base64_encode_requires_login(self, client):
        """Test that /process/base64 requires authentication."""
        response = client.post('/process/base64', data=b"some data")
        # Depending on Flask-Login setup, unauthenticated POST might return 401 or redirect 302
        assert response.status_code in (302, 401)
        if response.status_code == 302:
            assert 'login' in response.headers.get('Location', '').lower()

    def test_base64_encode_no_data(self, app, client):
        """Test that missing data returns a 400 error."""
        _login(app, client)
        response = client.post('/process/base64', data=b'')
        assert response.status_code == 400
        data = response.get_json()
        assert data == {'error': 'No data provided'}

    def test_base64_encode_success(self, app, client):
        """Test that data is correctly base64-encoded."""
        _login(app, client)
        test_data = b'Hello, world! 123 \x00\x01\x02'
        expected_encoded = base64.b64encode(test_data).decode('utf-8')

        response = client.post('/process/base64', data=test_data)
        assert response.status_code == 200
        data = response.get_json()
        assert data == {'encoded': expected_encoded}
