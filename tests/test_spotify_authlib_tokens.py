"""Tests for Spotify Authlib token storage normalization."""
import json
from datetime import datetime, timedelta

from musicround import _spotify_authlib_token_from_user, _store_spotify_authlib_token
from musicround.models import User


def test_authlib_fetch_token_uses_raw_user_columns():
    """Authlib token getter must not require spotify_token to contain JSON."""
    expiry = datetime.now() + timedelta(hours=1)
    user = User(
        username='spotauth',
        email='spotauth@example.com',
        spotify_token='raw-access-token',
        spotify_refresh_token='raw-refresh-token',
        spotify_token_expiry=expiry,
    )

    token = _spotify_authlib_token_from_user(user)

    assert token == {
        'access_token': 'raw-access-token',
        'refresh_token': 'raw-refresh-token',
        'token_type': 'Bearer',
        'expires_at': int(expiry.timestamp()),
    }


def test_authlib_fetch_token_reads_legacy_json_without_exposing_it():
    """Legacy JSON values remain readable during migration to raw storage."""
    user = User(
        username='legacyspot',
        email='legacyspot@example.com',
        spotify_token=json.dumps({
            'access_token': 'legacy-access-token',
            'refresh_token': 'legacy-refresh-token',
            'expires_at': '1893456000',
        }),
    )

    token = _spotify_authlib_token_from_user(user)

    assert token == {
        'access_token': 'legacy-access-token',
        'refresh_token': 'legacy-refresh-token',
        'token_type': 'Bearer',
        'expires_at': 1893456000,
    }


def test_authlib_update_token_stores_raw_access_token_and_expiry():
    """Authlib token updater must not write JSON back into spotify_token."""
    user = User(
        username='updateme',
        email='updateme@example.com',
        spotify_refresh_token='old-refresh-token',
    )
    expires_at = int((datetime.now() + timedelta(hours=1)).timestamp())

    _store_spotify_authlib_token(
        user,
        {
            'access_token': 'new-access-token',
            'refresh_token': 'new-refresh-token',
            'expires_at': expires_at,
            'token_type': 'Bearer',
        },
    )

    assert user.spotify_token == 'new-access-token'
    assert not user.spotify_token.startswith('{')
    assert user.spotify_refresh_token == 'new-refresh-token'
    assert int(user.spotify_token_expiry.timestamp()) == expires_at


def test_authlib_update_token_preserves_refresh_token_when_not_rotated():
    """Spotify often omits refresh_token; the existing one must survive."""
    user = User(
        username='keeprefresh',
        email='keeprefresh@example.com',
        spotify_refresh_token='existing-refresh-token',
    )

    _store_spotify_authlib_token(user, {'access_token': 'new-access-token'})

    assert user.spotify_token == 'new-access-token'
    assert user.spotify_refresh_token == 'existing-refresh-token'
