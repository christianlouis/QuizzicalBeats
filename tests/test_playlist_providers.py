"""Provider contracts exercised without writing to real streaming accounts."""
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests

from musicround.helpers import playlist_providers as api


SPOTIFY_ID = 'A' * 22
PLAYLIST = 'P' * 22
ISRC = 'USSM19902970'


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


def song(**kwargs):
    return SimpleNamespace(**(dict(title='Song', artist='Artist', isrc=None,
                                   spotify_id=None, deezer_id=None) | kwargs))


def wire(monkeypatch, *responses):
    calls = []
    replies = iter(responses)

    def request(method, url, **kwargs):
        calls.append((method, urlsplit(url).path, kwargs))
        assert kwargs['allow_redirects'] is False
        return next(replies)

    monkeypatch.setattr(api.requests, 'request', request)
    return calls


def test_stored_spotify_id_and_deezer_isrc_lookup(monkeypatch):
    calls = wire(monkeypatch, Response({'id': SPOTIFY_ID, 'is_playable': True}),
                 Response({'error': {'code': 800}}), Response({'id': 12345, 'isrc': ISRC}))
    assert api.resolve_track('spotify', 'token', song(spotify_id=SPOTIFY_ID)) == SPOTIFY_ID
    assert api.resolve_track('deezer', 'token', song(deezer_id=7, isrc=ISRC)) == '12345'
    assert [path for _, path, _ in calls] == [f'/v1/tracks/{SPOTIFY_ID}', '/track/7', f'/track/isrc:{ISRC}']


def test_spotify_isrc_search(monkeypatch):
    calls = wire(monkeypatch, Response({'tracks': {'items': [
        {'id': 'B' * 22, 'external_ids': {'isrc': ISRC}, 'is_playable': False},
        {'id': SPOTIFY_ID, 'external_ids': {'isrc': ISRC}},
    ]}}))
    assert api.resolve_track('spotify', 'token', song(isrc=ISRC)) == SPOTIFY_ID
    assert calls[0][2]['params']['q'] == f'isrc:{ISRC}'


def test_name_search_preserves_unicode_and_versions_and_rejects_ambiguity(monkeypatch):
    def track(track_id, name, version=''):
        return {'id': track_id, 'title': name, 'title_version': version, 'artist': {'name': '楽団'}}
    candidates = [track(1, '別'), track(2, '空', '(Live)'), track(3, '空')]
    calls = wire(monkeypatch, Response({'data': candidates}), Response({'data': candidates + [track(4, '空')]}))
    recording = song(title='空', artist='楽団')
    assert api.resolve_track('deezer', 'token', recording) == '3'
    assert api.resolve_track('deezer', 'token', recording) is None
    assert calls[0][1] == '/search/track'


@pytest.mark.parametrize(('provider', 'remote_id', 'path'), [
    ('spotify', PLAYLIST, '/v1/me/playlists'), ('deezer', '78', '/user/me/playlists'),
])
def test_create_uses_personal_endpoint_and_private_visibility(monkeypatch, provider, remote_id, path):
    calls = wire(monkeypatch, Response({'id': remote_id}))
    assert api.create_playlist(provider, 'personal', 'Round') == remote_id
    method, endpoint, request = calls[0]
    assert (method, endpoint) == ('POST', path)
    if provider == 'spotify':
        assert request['json'] == {'name': 'Round', 'public': False}
        assert request['headers'] == {'Authorization': 'Bearer personal'}
    else:
        assert request['params'] == {'title': 'Round', 'public': '0', 'access_token': 'personal'}


def test_spotify_replaces_in_batches_and_preserves_repeats(monkeypatch):
    calls = wire(monkeypatch, Response({'owner': {'id': 'self'}, 'public': False}),
                 Response({'snapshot_id': 'first'}), Response({'snapshot_id': 'second'}))
    tracks = [SPOTIFY_ID] * 100 + ['B' * 22]
    api.sync_tracks('spotify', 'token', PLAYLIST, tracks, account_id='self')
    assert [(m, p) for m, p, _ in calls] == [
        ('GET', f'/v1/playlists/{PLAYLIST}'), ('PUT', f'/v1/playlists/{PLAYLIST}/items'),
        ('POST', f'/v1/playlists/{PLAYLIST}/items'),
    ]
    assert [uri for _, _, request in calls[1:] for uri in request['json']['uris']] == [
        f'spotify:track:{track}' for track in tracks
    ]


def test_deezer_reads_all_pages_removes_and_reorders_then_checks_result(monkeypatch):
    details = Response({'public': False, 'creator': {'id': 4}})
    calls = wire(monkeypatch, details,
                 Response({'data': [{'id': 1}, {'id': 2}], 'next': 'https://api.deezer.com/next'}),
                 Response({'data': [{'id': 3}]}), Response(True), Response(True), Response(True),
                 Response({'data': [{'id': 3}, {'id': 4}, {'id': 1}]}))
    api.sync_tracks('deezer', 'token', '7', ['3', '4', '1'], account_id='4')
    assert [c[0] for c in calls] == ['GET', 'GET', 'GET', 'POST', 'DELETE', 'POST', 'GET']
    assert calls[2][2]['params']['index'] == 2
    assert [calls[i][2]['params']['songs'] for i in (3, 4)] == ['4', '2']
    assert calls[5][2]['params']['order'] == '3,4,1'


def test_deezer_privacy_must_be_confirmed_before_sending_tracks(monkeypatch):
    public = Response({'creator': {'id': 4}, 'public': True})
    calls = wire(monkeypatch, public, Response(True), public)
    with pytest.raises(api.PlaylistProviderError, match='set it to private'):
        api.sync_tracks('deezer', 'token', '7', ['42'], account_id='4')
    assert [c[1] for c in calls] == ['/playlist/7'] * 3


def test_foreign_playlist_is_never_modified(monkeypatch):
    calls = wire(monkeypatch, Response({'creator': {'id': 9}, 'public': True}))
    with pytest.raises(api.PlaylistProviderError, match='belong'):
        api.sync_tracks('deezer', 'token', '7', ['42'], account_id='4')
    assert [c[0] for c in calls] == ['GET']


def test_deezer_false_write_and_wrong_readback_are_failures(monkeypatch):
    details = Response({'creator': {'id': 4}, 'public': False})
    empty = Response({'data': []})
    wire(monkeypatch, details, empty, Response(False))
    with pytest.raises(api.PlaylistProviderError, match='confirm'):
        api.sync_tracks('deezer', 'token', '7', ['42'], account_id='4')
    wire(monkeypatch, details, empty, Response(True), empty)
    with pytest.raises(api.PlaylistProviderError, match='order'):
        api.sync_tracks('deezer', 'token', '7', ['42'], account_id='4')


@pytest.mark.parametrize('error', [Response({'error': 'private detail'}, 401),
                                   Response({'error': {'code': 300, 'message': 'private detail'}})])
def test_permission_error_sanitized(monkeypatch, error):
    wire(monkeypatch, error)
    with pytest.raises(api.PlaylistProviderError) as raised:
        api.resolve_track('deezer', 'token', song())
    assert raised.value.reconnect
    assert 'private detail' not in str(raised.value)


def test_failed_create_may_have_succeeded_and_missing_playlist_is_identified(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout('secret URL')
    monkeypatch.setattr(api.requests, 'request', timeout)
    with pytest.raises(api.PlaylistProviderError) as raised:
        api.create_playlist('deezer', 'token', 'Round')
    assert raised.value.creation_uncertain
    assert 'secret' not in str(raised.value)
    wire(monkeypatch, Response({'error': {'code': 800}}))
    with pytest.raises(api.PlaylistProviderError) as raised:
        api.sync_tracks('deezer', 'token', '7', ['42'], account_id='4')
    assert raised.value.playlist_missing
