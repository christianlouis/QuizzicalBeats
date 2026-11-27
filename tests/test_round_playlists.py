"""Exercise the round page and personal playlist workflow through Flask's normal routes."""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from flask import redirect

from musicround.helpers import playlist_providers as api
from musicround.helpers.deezer_account import save_deezer_account
from musicround.models import Round, RoundPlaylist, RoundShare, Song, User, db


def make_user(name, spotify=False):
    user = User(username=name, email=f'{name}@example.test')
    user.password = 'PlaylistPass123!'
    if spotify:
        user.spotify_id = f'spotify-{name}'
        user.spotify_token = f'token-{name}'
        user.spotify_token_expiry = datetime.now() + timedelta(hours=1)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user):
    response = client.post('/users/login', data={'username': user.username, 'password': 'PlaylistPass123!'})
    assert response.status_code == 302


@pytest.fixture
def round_data(app):
    owner = make_user('owner', spotify=True)
    songs = [Song(title=name, artist='Band', deezer_id=i, spotify_id=str(i) * 22)
             for i, name in enumerate(['One', 'Two', 'Three'], start=1)]
    db.session.add_all(songs)
    db.session.flush()
    rnd = Round(name='Quiz Night', round_type='genre', round_criteria_used='Rock', user_id=owner.id,
                songs=','.join(str(song.id) for song in reversed(songs)))
    db.session.add(rnd)
    db.session.commit()
    return rnd, owner


@pytest.fixture
def provider(monkeypatch):
    """Stub the streaming service, retaining real authentication, persistence and routes."""
    gateway = Mock()
    gateway.resolve_track.side_effect = lambda service, token, song: str(getattr(song, f'{service}_id'))
    gateway.create_playlist.side_effect = lambda service, token, name: 'P' * 22 if service == 'spotify' else '70'
    for method in ('resolve_track', 'create_playlist', 'sync_tracks'):
        monkeypatch.setattr(api, method, getattr(gateway, method))
    return gateway


def endpoint(rnd, service='spotify'):
    return f'/rounds/{rnd.id}/playlists/{service}'


def test_round_detail_and_sync_use_saved_order_and_same_personal_playlist(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    detail = client.get(f'/rounds/{rnd.id}')
    assert b'Create Spotify playlist' in detail.data
    assert b'Connect Deezer' in detail.data
    response = client.post(endpoint(rnd), follow_redirects=True)
    assert b'Created your Spotify playlist with 3 of 3 songs.' in response.data
    assert b'Open Spotify playlist' in response.data
    ordered = ['3' * 22, '2' * 22, '1' * 22]
    provider.sync_tracks.assert_called_with('spotify', 'token-owner', 'P' * 22, ordered,
                                             account_id='spotify-owner')

    rnd.songs = ','.join(str(song.id) for song in rnd.song_list[::2])
    db.session.commit()
    response = client.post(endpoint(rnd), follow_redirects=True)
    assert b'Updated your Spotify playlist with 2 of 2 songs.' in response.data
    provider.sync_tracks.assert_called_with('spotify', 'token-owner', 'P' * 22, [ordered[0], ordered[2]],
                                             account_id='spotify-owner')
    provider.create_playlist.assert_called_once_with('spotify', 'token-owner', 'Quiz Night')


def test_retry_after_failed_sync_keeps_remote_id(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    provider.sync_tracks.side_effect = [api.PlaylistProviderError('Try again.'), None]
    response = client.post(endpoint(rnd), follow_redirects=True)
    saved = RoundPlaylist.query.one()
    assert saved.playlist_id == 'P' * 22 and saved.status == 'idle'
    assert b'Open Spotify playlist' in response.data
    client.post(endpoint(rnd))
    assert RoundPlaylist.query.one().status == 'ready'
    assert provider.create_playlist.call_count == 1


def test_uncertain_create_checks_library_before_retry(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    provider.create_playlist.side_effect = [api.PlaylistProviderError('Timeout', creation_uncertain=True), 'P' * 22]
    assert b'I checked my Spotify library' in client.post(endpoint(rnd), follow_redirects=True).data
    client.post(endpoint(rnd))
    assert provider.create_playlist.call_count == 1
    client.post(endpoint(rnd), data={'checked_library': '1'})
    assert RoundPlaylist.query.one().status == 'ready'


def test_missing_track_and_repetitions_on_deezer_need_partial_opt_in(round_data, client, provider):
    rnd, owner = round_data
    save_deezer_account(owner.id, '42', 'personal-deezer')
    first = rnd.song_list[0]
    rnd.songs = f'{first.id},987654,{first.id}'
    db.session.commit()
    login(client, owner)
    response = client.post(endpoint(rnd, 'deezer'), follow_redirects=True)
    assert b'Use 1 available song' in response.data
    assert b'Missing library song #987654' in response.data
    assert b'repeated recording on Deezer' in response.data
    provider.create_playlist.assert_not_called()
    response = client.post(endpoint(rnd, 'deezer'), data={'allow_partial': '1'}, follow_redirects=True)
    assert b'1 of 3 songs' in response.data
    assert b'https://www.deezer.com/playlist/70' in response.data
    provider.sync_tracks.assert_called_once_with('deezer', 'personal-deezer', '70', [str(first.deezer_id)],
                                                  account_id='42')


def test_all_missing_does_not_replace_existing_playlist(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    client.post(endpoint(rnd))
    provider.resolve_track.side_effect = lambda *args: None
    response = client.post(endpoint(rnd), data={'allow_partial': '1'}, follow_redirects=True)
    assert b'None of the 3 saved songs' in response.data
    assert provider.sync_tracks.call_count == 1


def test_recent_creation_refuses_a_second_export(round_data, client, provider):
    rnd, owner = round_data
    db.session.add(RoundPlaylist(round_id=rnd.id, user_id=owner.id,
                                 provider='spotify', account_id=owner.spotify_id,
                                 status='creating', operation_id='first', started_at=datetime.utcnow()))
    db.session.commit()
    login(client, owner)
    response = client.post(endpoint(rnd), follow_redirects=True)
    assert b'export is already in progress' in response.data
    provider.create_playlist.assert_not_called()
    provider.sync_tracks.assert_not_called()


def test_deleted_provider_playlist_can_be_recreated(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    client.post(endpoint(rnd))
    provider.sync_tracks.side_effect = [api.PlaylistProviderError('Removed.', playlist_missing=True), None]
    response = client.post(endpoint(rnd), follow_redirects=True)
    assert b'Create Spotify playlist' in response.data
    assert RoundPlaylist.query.one().playlist_id is None
    client.post(endpoint(rnd))
    assert RoundPlaylist.query.one().status == 'ready'
    assert provider.create_playlist.call_count == 2


def test_deleting_round_clears_its_local_playlist_mapping(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    client.post(endpoint(rnd))
    assert RoundPlaylist.query.count() == 1
    db.session.delete(rnd)
    db.session.commit()
    assert RoundPlaylist.query.count() == 0


def test_provider_requests_reconnect_without_writing(round_data, client, provider):
    rnd, owner = round_data
    login(client, owner)
    provider.resolve_track.side_effect = api.PlaylistProviderError('Permission expired.', auth_required=True)
    response = client.post(endpoint(rnd), follow_redirects=True)
    assert b'Reconnect Spotify' in response.data
    assert RoundPlaylist.query.count() == 0


def test_spotify_link_returns_to_starting_round_and_consumes_state(round_data, client, app, monkeypatch):
    rnd, owner = round_data
    login(client, owner)
    app.config['SPOTIFY_CLIENT_ID'] = 'local-app'
    oauth_client = Mock()
    oauth_client.spotify.authorize_redirect.return_value = redirect('https://accounts.spotify.com/authorize')
    oauth_client.spotify.authorize_access_token.return_value = {'access_token': 'renewed', 'expires_in': 3600}
    monkeypatch.setattr('musicround.routes.users.oauth', oauth_client)
    monkeypatch.setattr('musicround.routes.users.get_spotify_user_info', lambda token: {'id': 'relinked'})

    assert client.post('/users/spotify-link', data={'round_id': rnd.id}).status_code == 302
    state = oauth_client.spotify.authorize_redirect.call_args.kwargs['state']
    callback = client.get('/users/spotify-link/callback', query_string={'state': state, 'code': 'one-use'})
    assert callback.location.endswith(f'/rounds/{rnd.id}#streaming-playlists')
    assert owner.spotify_id == 'relinked'
    client.get('/users/spotify-link/callback', query_string={'state': state, 'code': 'one-use'})
    oauth_client.spotify.authorize_access_token.assert_called_once_with()


@pytest.mark.parametrize('role', ['viewer', None])
def test_viewer_and_unshared_user_cannot_export(round_data, client, provider, role):
    rnd, _ = round_data
    visitor = make_user('visitor', spotify=True)
    if role:
        db.session.add(RoundShare(round_id=rnd.id, user_id=visitor.id, role=role))
        db.session.commit()
    login(client, visitor)
    response = client.get(f'/rounds/{rnd.id}')
    assert b'id="streaming-playlists"' not in response.data
    assert client.post(endpoint(rnd)).status_code in (403, 404)
    provider.create_playlist.assert_not_called()


def test_producer_uses_own_account_and_relink_has_separate_playlist(round_data, app, client, provider):
    rnd, owner = round_data
    producer = make_user('producer')
    db.session.add(RoundShare(round_id=rnd.id, user_id=producer.id, role='producer'))
    db.session.commit()
    save_deezer_account(owner.id, '41', 'owner-token')
    save_deezer_account(producer.id, '42', 'producer-token')
    login(client, owner)
    client.post(endpoint(rnd, 'deezer'))
    assert client.get('/users/logout').status_code == 302
    login(client, producer)
    client.post(endpoint(rnd, 'deezer'))
    save_deezer_account(producer.id, '43', 'different-token')
    client.post(endpoint(rnd, 'deezer'))
    assert [(row.user_id, row.account_id) for row in RoundPlaylist.query.order_by(RoundPlaylist.id)] == [
        (owner.id, '41'), (producer.id, '42'), (producer.id, '43'),
    ]
    assert [call.args[1] for call in provider.sync_tracks.call_args_list] == [
        'owner-token', 'producer-token', 'different-token',
    ]


def test_unlinked_account_csrf_and_login_are_enforced(round_data, app, client, provider):
    rnd, owner = round_data
    assert client.post(endpoint(rnd)).status_code in (302, 401)
    login(client, owner)
    response = client.post(endpoint(rnd, 'deezer'), follow_redirects=True)
    assert b'Connect your Deezer account' in response.data
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(endpoint(rnd)).status_code == 400
    provider.create_playlist.assert_not_called()
