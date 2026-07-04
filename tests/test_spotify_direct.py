"""Tests for SpotifyDirectClient's refresh-token handling.

Covers discarding the cached token on invalid_grant (see #60 / Spotify's
2026-07-20 refresh token expiry change) without retrying the dead token.
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from musicround.helpers.spotify_direct import SpotifyDirectClient


def _make_response(status_code, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    return resp


@pytest.fixture
def direct_client(app, tmp_path):
    with app.app_context():
        app.config['SPOTIFY_CLIENT_ID'] = 'cid'
        app.config['SPOTIFY_CLIENT_SECRET'] = 'secret'
        cache_path = tmp_path / ".spotifycache"
        cache_path.write_text(json.dumps({
            'access_token': 'old-token',
            'refresh_token': 'old-refresh',
            'expires_at': 0,
        }))
        client = SpotifyDirectClient(cache_path=str(cache_path))
        yield client, cache_path


class TestRefreshAccessToken:
    def test_invalid_grant_discards_cache(self, direct_client):
        client, cache_path = direct_client
        assert client.refresh_token == 'old-refresh'
        assert os.path.exists(cache_path)

        with patch.object(client.session, 'post') as mock_post:
            mock_post.return_value = _make_response(400, {'error': 'invalid_grant'})
            result = client._refresh_access_token()

        assert result is False
        assert client.access_token is None
        assert client.refresh_token is None
        assert not os.path.exists(cache_path)

    def test_transient_5xx_keeps_refresh_token(self, direct_client):
        client, cache_path = direct_client
        with patch.object(client.session, 'post') as mock_post:
            mock_post.return_value = _make_response(500)
            result = client._refresh_access_token()

        assert result is False
        # Transient failures must not discard the refresh token or cache.
        assert client.refresh_token == 'old-refresh'
        assert os.path.exists(cache_path)

    def test_successful_refresh_updates_token(self, direct_client):
        client, cache_path = direct_client
        with patch.object(client.session, 'post') as mock_post:
            mock_post.return_value = _make_response(200, {'access_token': 'new-token', 'expires_in': 3600})
            result = client._refresh_access_token()

        assert result is True
        assert client.access_token == 'new-token'
        mock_post.assert_called_once_with(
            client.token_url,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': 'old-refresh',
                'client_id': 'cid',
                'client_secret': 'secret',
            },
            timeout=10,
        )
        cached = json.loads(cache_path.read_text())
        assert cached['access_token'] == 'new-token'
        assert cached['refresh_token'] == 'old-refresh'
        assert cached['expires_at'] == client.token_expiry

    def test_no_refresh_token_returns_false(self, direct_client):
        client, _ = direct_client
        client.refresh_token = None
        assert client._refresh_access_token() is False
