"""Resolve saved recordings and write personal, private playlists using the providers' APIs."""

import re
import unicodedata

import requests


class PlaylistProviderError(RuntimeError):
    """A message safe to show to the quizmaster without leaking request credentials."""

    def __init__(self, message, *, auth_required=False, provider_status=None,
                 creation_uncertain=False, playlist_missing=False):
        super().__init__(message)
        self.reconnect = auth_required
        self.provider_status = provider_status
        self.creation_uncertain = creation_uncertain
        self.playlist_missing = playlist_missing


_BASE = {'spotify': 'https://api.spotify.com/v1', 'deezer': 'https://api.deezer.com'}
_BAD_RESPONSE = 'The streaming service returned an unexpected response. Please try again.'


def _request(provider, method, path, token, *, params=None, body=None, creating=False):
    if provider not in _BASE:
        raise PlaylistProviderError('Unknown streaming service.')
    if not token:
        raise PlaylistProviderError('Connect your streaming account first.', auth_required=True)
    headers = {'Authorization': f'Bearer {token}'} if provider == 'spotify' else {}
    params = dict(params or {})
    if provider == 'deezer':
        params['access_token'] = token
    try:
        response = requests.request(method, f'{_BASE[provider]}/{path}', params=params,
                                    headers=headers, json=body, timeout=12, allow_redirects=False)
    except requests.RequestException:
        raise PlaylistProviderError('The streaming service could not be reached. Try again shortly.',
                                    creation_uncertain=creating) from None
    status = response.status_code
    try:
        payload = response.json()
    except ValueError:
        payload = None
    # Deezer can report an API error inside a successful HTTP response.
    error = payload.get('error') if isinstance(payload, dict) else None
    code = str(error.get('code')) if provider == 'deezer' and isinstance(error, dict) else None
    if status == 429 or code == '4':
        raise PlaylistProviderError('The streaming service is receiving too many requests. Try again shortly.')
    if status in (401, 403) or code in ('200', '300'):
        raise PlaylistProviderError('Reconnect your streaming account and grant playlist access.',
                                    auth_required=True, provider_status=status)
    if status == 404 or code == '800':
        raise PlaylistProviderError('The streaming service could not find this item.', provider_status=404)
    if not 200 <= status < 300 or error:
        raise PlaylistProviderError('The streaming service could not complete the request. Try again.',
                                    provider_status=status, creation_uncertain=creating and status >= 500)
    if payload is None:
        raise PlaylistProviderError(_BAD_RESPONSE, creation_uncertain=creating)
    return payload


def _id(value, provider):
    value = str(value or '').strip()
    pattern = r'[A-Za-z0-9]{22}' if provider == 'spotify' else r'[1-9][0-9]*'
    return value if re.fullmatch(pattern, value) else None


def _available(item, provider):
    if not isinstance(item, dict) or item.get('is_playable') is False or item.get('readable') is False:
        return None
    if item.get('restrictions') or item.get('is_local'):
        return None
    return _id(item.get('id'), provider)


def _catalog_item(provider, path, token):
    try:
        item = _request(provider, 'GET', path, token)
    except PlaylistProviderError as exc:
        if exc.provider_status == 404:
            return None
        raise
    if not isinstance(item, dict) or not _id(item.get('id'), provider):
        raise PlaylistProviderError(_BAD_RESPONSE)
    return item


def _normal(value):
    normalized = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'[^\W_]+', normalized))


def _matches_name(item, provider, title, artist):
    if provider == 'spotify':
        artists = [a['name'] for a in item.get('artists') or [] if isinstance(a, dict) and a.get('name')]
        names = [artists[0], ', '.join(artists)] if artists else []
        item_title = item.get('name')
    else:
        names = [(item.get('artist') or {}).get('name')]
        item_title = item.get('title') or ''
        version = item.get('title_version')
        if version and _normal(version) not in _normal(item_title):
            item_title = f'{item_title} {version}'
    return _normal(item_title) == title and any(_normal(name) == artist for name in names)


def _search(provider, token, query):
    params = {'q': query, 'limit': 10}
    if provider == 'spotify':
        params['type'] = 'track'
    path = 'search' if provider == 'spotify' else 'search/track'
    result = _request(provider, 'GET', path, token, params=params)
    if isinstance(result, dict) and provider == 'spotify':
        result = result.get('tracks')
    items = result.get('items' if provider == 'spotify' else 'data') if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise PlaylistProviderError(_BAD_RESPONSE)
    return [item for item in items if _available(item, provider)]


def resolve_track(provider, token, song):
    """Prefer the saved recording, then its ISRC, then an unambiguous artist/title match."""
    track_id = _id(getattr(song, f'{provider}_id', None), provider)
    if track_id:
        path = 'tracks' if provider == 'spotify' else 'track'
        item = _catalog_item(provider, f'{path}/{track_id}', token)
        available_id = _available(item, provider)
        if available_id:
            return available_id

    isrc = (song.isrc or '').replace('-', '').strip().upper()
    if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}[0-9]{7}', isrc):
        if provider == 'deezer':
            item = _catalog_item(provider, f'track/isrc:{isrc}', token)
            if _available(item, provider) and str(item.get('isrc')).upper() == isrc:
                return _available(item, provider)
        else:
            for item in _search(provider, token, f'isrc:{isrc}'):
                if str((item.get('external_ids') or {}).get('isrc')).upper() == isrc:
                    return _available(item, provider)

    title, artist = _normal(song.title), _normal(song.artist)
    if not title or not artist:
        return None
    # Quote individual fields and keep user-entered quote marks out of the search syntax.
    artist_term = song.artist.replace('"', ' ')
    title_term = song.title.replace('"', ' ')
    items = _search(provider, token, f'artist:"{artist_term}" track:"{title_term}"')
    matches = {_available(item, provider) for item in items if _matches_name(item, provider, title, artist)}
    return matches.pop() if len(matches) == 1 else None


def create_playlist(provider, token, name):
    """Create an empty personal playlist. The caller checkpoints its ID before adding tracks."""
    title = str(name).strip()[:100]
    if provider == 'spotify':
        result = _request(provider, 'POST', 'me/playlists', token, creating=True,
                          body={'name': title, 'public': False})
    else:
        result = _request(provider, 'POST', 'user/me/playlists', token, creating=True,
                          params={'title': title, 'public': '0'})
    remote_id = _id(result.get('id'), provider) if isinstance(result, dict) else None
    if not remote_id:
        raise PlaylistProviderError('The service did not confirm creation. Check your library.',
                                    creation_uncertain=True)
    return remote_id


def _check_destination(provider, token, playlist_id, account_id):
    """Verify ownership and visibility before sending the quiz answers to either service."""
    path = f'playlists/{playlist_id}' if provider == 'spotify' else f'playlist/{playlist_id}'
    params = {'fields': 'public,owner(id)'} if provider == 'spotify' else None

    def details():
        try:
            item = _request(provider, 'GET', path, token, params=params)
        except PlaylistProviderError as exc:
            if exc.provider_status == 404:
                raise PlaylistProviderError('This playlist was removed. Click Create to make a new one.',
                                            playlist_missing=True) from None
            raise
        if not isinstance(item, dict):
            raise PlaylistProviderError(_BAD_RESPONSE)
        owner = item.get('owner' if provider == 'spotify' else 'creator') or {}
        if not isinstance(owner, dict) or not account_id or str(owner.get('id', '')) != str(account_id):
            raise PlaylistProviderError('This playlist does not belong to the connected account.')
        return item.get('public')

    visibility = details()
    if provider == 'deezer' and visibility is True:
        # Some Deezer responses only honor a separate privacy update after creation.
        _request(provider, 'POST', path, token, params={'public': '0'})
        visibility = details()
    if visibility is not False:
        raise PlaylistProviderError('Open the playlist, set it to private, then click Update to add the songs.')


def _deezer_track_ids(path, token):
    ids = []
    while True:
        page = _request('deezer', 'GET', path, token, params={'index': len(ids), 'limit': 100})
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise PlaylistProviderError(_BAD_RESPONSE)
        batch = [_id(item.get('id'), 'deezer') if isinstance(item, dict) else None for item in page['data']]
        if None in batch:
            raise PlaylistProviderError(_BAD_RESPONSE)
        ids.extend(batch)
        if not page.get('next'):
            return ids
        if not batch:
            raise PlaylistProviderError(_BAD_RESPONSE)


def _deezer_sync(path, token, desired):
    current = _deezer_track_ids(path, token)
    if current == desired:
        return

    def change(method, key, ids):
        if _request('deezer', method, path, token, params={key: ','.join(ids)}) is not True:
            raise PlaylistProviderError('Deezer did not confirm the track update. Try updating this playlist again.')

    current_set, desired_set = set(current), set(desired)
    added = [track for track in desired if track not in current_set]
    removed = [track for track in current if track not in desired_set]
    for method, batch in [('POST', added), ('DELETE', removed)]:
        for start in range(0, len(batch), 100):
            change(method, 'songs', batch[start:start + 100])
    if [track for track in current if track in desired_set] + added != desired:
        change('POST', 'order', desired)
    if _deezer_track_ids(path, token) != desired:
        raise PlaylistProviderError('Deezer has not confirmed the saved song order. Try updating this playlist again.')


def validate_tracks(provider, track_ids):
    if not track_ids or any(not _id(track, provider) for track in track_ids):
        raise PlaylistProviderError('The round contains an invalid track for this service.')
    if provider == 'deezer' and len(set(track_ids)) != len(track_ids):
        raise PlaylistProviderError('Deezer can only include each recording once.')
    return track_ids


def sync_tracks(provider, token, playlist_id, track_ids, *, account_id):
    """Make the app-created playlist match the round, including deletions and reordering."""
    if not _id(playlist_id, provider):
        raise PlaylistProviderError('The saved playlist ID is invalid.')
    desired = validate_tracks(provider, track_ids)
    _check_destination(provider, token, playlist_id, account_id)
    if provider == 'deezer':
        _deezer_sync(f'playlist/{playlist_id}/tracks', token, desired)
        return
    path = f'playlists/{playlist_id}/items'
    for start in range(0, len(desired), 100):
        uris = [f'spotify:track:{item}' for item in desired[start:start + 100]]
        result = _request(provider, 'PUT' if start == 0 else 'POST', path, token, body={'uris': uris})
        if not isinstance(result, dict) or not result.get('snapshot_id'):
            raise PlaylistProviderError('Spotify did not confirm the track update. Try updating this playlist again.')
