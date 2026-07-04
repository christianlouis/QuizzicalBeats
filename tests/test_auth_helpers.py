"""Tests for musicround.helpers.auth_helpers.update_oauth_tokens.

A provider's refresh response doesn't always include a new refresh_token
(Spotify in particular omits it when the existing one wasn't rotated), so
update_oauth_tokens must not clobber a still-valid stored refresh token with
None just because a given response happened to omit it.
"""
from musicround.helpers.auth_helpers import update_oauth_tokens
from musicround.models import User, db


def _make_user(**kwargs):
    user = User(username='oauthuser', email='oauthuser@example.com')
    for key, value in kwargs.items():
        setattr(user, key, value)
    db.session.add(user)
    db.session.commit()
    return user


class TestUpdateOauthTokensPreservesRefreshToken:
    def test_spotify_refresh_without_new_refresh_token_keeps_existing(self, app):
        with app.app_context():
            user = _make_user(spotify_refresh_token='old-refresh-token')
            update_oauth_tokens(user, {'access_token': 'new-access-token'}, 'spotify')
            assert user.spotify_token == 'new-access-token'
            assert user.spotify_refresh_token == 'old-refresh-token'

    def test_spotify_refresh_with_new_refresh_token_updates_it(self, app):
        with app.app_context():
            user = _make_user(spotify_refresh_token='old-refresh-token')
            update_oauth_tokens(
                user, {'access_token': 'new-access-token', 'refresh_token': 'new-refresh-token'}, 'spotify'
            )
            assert user.spotify_refresh_token == 'new-refresh-token'

    def test_dropbox_refresh_without_new_refresh_token_keeps_existing(self, app):
        with app.app_context():
            user = _make_user(dropbox_refresh_token='old-dropbox-refresh')
            update_oauth_tokens(user, {'access_token': 'new-token'}, 'dropbox')
            assert user.dropbox_refresh_token == 'old-dropbox-refresh'

    def test_google_refresh_without_new_refresh_token_keeps_existing(self, app):
        with app.app_context():
            user = _make_user(google_refresh_token='old-google-refresh')
            update_oauth_tokens(user, {'access_token': 'new-token'}, 'google')
            assert user.google_refresh_token == 'old-google-refresh'

    def test_authentik_refresh_without_new_refresh_token_keeps_existing(self, app):
        with app.app_context():
            user = _make_user(authentik_refresh_token='old-authentik-refresh')
            update_oauth_tokens(user, {'access_token': 'new-token'}, 'authentik')
            assert user.authentik_refresh_token == 'old-authentik-refresh'
