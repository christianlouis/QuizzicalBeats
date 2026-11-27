"""Create and update personal playlists from a round's saved track order."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from musicround.helpers import playlist_providers
from musicround.models import RoundPlaylist, db


PROVIDERS = {'spotify': 'Spotify', 'deezer': 'Deezer'}
_PLAYLIST_URLS = {'spotify': 'https://open.spotify.com/playlist/',
                  'deezer': 'https://www.deezer.com/playlist/'}
_STALE_AFTER = timedelta(minutes=10)


class PlaylistBusy(RuntimeError):
    """Another request holds or has just completed this export."""


def _needs_library_check(row, now):
    """A lost create response can leave a real, empty playlist at the provider."""
    return row.status == 'unknown' or (
        row.status == 'creating' and row.started_at and row.started_at < now - _STALE_AFTER
    )


def playlist_controls(round_id, user_id, accounts):
    """Describe each account's buttons and links without passing tokens to the view."""
    rows = RoundPlaylist.query.filter_by(round_id=round_id, user_id=user_id).all()
    current = {row.provider: row for row in rows if row.account_id == accounts.get(row.provider)}
    controls = []
    for provider, label in PROVIDERS.items():
        row = current.get(provider)
        url = _PLAYLIST_URLS[provider] + row.playlist_id if row and row.playlist_id else None
        controls.append({
            'provider': provider, 'label': label, 'connected': bool(accounts[provider]),
            'url': url, 'check_library': bool(row and _needs_library_check(row, datetime.utcnow())),
        })
    return controls


def _reserve(round_id, user_id, provider, account_id, checked_library):
    """Claim the unique account/round slot before a request can create a remote playlist."""
    key = dict(round_id=round_id, user_id=user_id, provider=provider, account_id=account_id)
    operation = uuid4().hex
    now = datetime.utcnow()
    row = RoundPlaylist.query.filter_by(**key).first()
    if row is None:
        row = RoundPlaylist(**key, status='creating', started_at=now, operation_id=operation)
        db.session.add(row)
        try:
            db.session.commit()
            return row.id, operation, None
        except IntegrityError:
            db.session.rollback()
            row = RoundPlaylist.query.filter_by(**key).first()
            if row is None:
                raise

    if _needs_library_check(row, now):
        if not checked_library:
            raise PlaylistBusy('Check your library before retrying playlist creation.')
    elif row.status in ('creating', 'syncing') and row.started_at > now - _STALE_AFTER:
        raise PlaylistBusy('A playlist export is already in progress. Refresh this round shortly.')

    row_id, remote_id = row.id, row.playlist_id
    claim = RoundPlaylist.query.filter_by(id=row_id, status=row.status, operation_id=row.operation_id)
    changed = claim.update({
        'status': 'syncing' if remote_id else 'creating',
        'started_at': now, 'operation_id': operation,
    }, synchronize_session=False)
    db.session.commit()
    if not changed:
        raise PlaylistBusy('Another playlist export just started. Refresh this round shortly.')
    return row_id, operation, remote_id


def _checkpoint(row_id, operation, **values):
    """Durably record the remote ID before adding tracks, or release a finished claim."""
    changed = RoundPlaylist.query.filter_by(id=row_id, operation_id=operation).update(
        values, synchronize_session=False
    )
    db.session.commit()
    if not changed:
        raise PlaylistBusy('Another export is handling this playlist. Refresh the round shortly.')


def _round_tracks(round_obj, provider, token):
    """Resolve saved entries in order, keeping positions of unavailable and deleted songs."""
    songs = {song.id: song for song in round_obj.song_list}
    resolved = {}
    track_ids, missing = [], []
    deezer_ids = set()
    for position, song_id in enumerate(round_obj.song_id_list, start=1):
        song = songs.get(song_id)
        if song and song_id not in resolved:
            resolved[song_id] = playlist_providers.resolve_track(provider, token, song)
        track_id = resolved.get(song_id)
        if track_id and provider == 'deezer' and track_id in deezer_ids:
            missing.append((position, song_id, True))
        elif track_id:
            track_ids.append(track_id)
            if provider == 'deezer':
                deezer_ids.add(track_id)
        else:
            missing.append((position, song_id, False))
    return track_ids, missing


def describe_omissions(notice, songs):
    """Render saved references on the round page, keeping song titles out of the session cookie."""
    by_id = {song.id: song for song in songs}
    descriptions = []
    for position, song_id, repeated in notice.get('missing', []):
        song = by_id.get(song_id)
        title = f'{song.artist} — {song.title}' if song else f'Missing library song #{song_id}'
        suffix = ' (repeated recording on Deezer)' if repeated else ''
        descriptions.append(f'{position}. {title}{suffix}')
    return dict(notice, missing=descriptions)


def export_round_playlist(round_obj, user_id, provider, account_id, token, *,
                          allow_partial=False, checked_library=False):
    """Export a complete round, or the available tracks if the quizmaster chooses that."""
    track_ids, missing = _round_tracks(round_obj, provider, token)
    total = len(track_ids) + len(missing)
    label = PROVIDERS[provider]
    details = {'missing': missing[:12], 'more_missing': max(0, len(missing) - 12)}
    if not track_ids:
        message = (f'None of the {total} saved songs could be matched on {label}.' if total else
                   'Save at least one song in this round before creating a playlist.')
        return dict(details, message=message, level='warning')
    if missing and not allow_partial:
        return dict(details, message=f'{label} matched {len(track_ids)} of {total} songs.',
                    level='warning', available=len(track_ids))

    playlist_providers.validate_tracks(provider, track_ids)
    title = round_obj.name or f'Music Quiz #{round_obj.id}'
    row_id, operation, remote_id = _reserve(
        round_obj.id, user_id, provider, account_id, checked_library
    )
    creating = remote_id is None
    try:
        if creating:
            remote_id = playlist_providers.create_playlist(provider, token, title)
            _checkpoint(row_id, operation, playlist_id=remote_id, status='syncing')
        playlist_providers.sync_tracks(provider, token, remote_id, track_ids, account_id=account_id)
    except playlist_providers.PlaylistProviderError as exc:
        unknown = not remote_id and exc.creation_uncertain
        _checkpoint(row_id, operation, operation_id=None,
                    status='unknown' if unknown else 'idle',
                    playlist_id=None if exc.playlist_missing else remote_id)
        raise
    _checkpoint(row_id, operation, status='ready', operation_id=None)
    verb = 'Created' if creating else 'Updated'
    return dict(details, level='warning' if missing else 'success',
                message=f'{verb} your {label} playlist with {len(track_ids)} of {total} songs.')
