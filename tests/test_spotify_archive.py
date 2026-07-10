"""Tests for the disk-backed offline Spotify archive search path."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from musicround.helpers.spotify_archive import (
    SpotifyArchiveError,
    search_spotify_archive_catalog,
    spotify_archive_catalog_status,
)
from musicround.spotify_archive_catalog import create_app
from tests.test_api_extended import _create_user_and_login


def _archive_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE albums (name TEXT NOT NULL, release_date TEXT NOT NULL);
        CREATE TABLE tracks (
            id TEXT NOT NULL, external_id_isrc TEXT, name TEXT NOT NULL,
            popularity INTEGER NOT NULL, preview_url TEXT, duration_ms INTEGER NOT NULL,
            album_rowid INTEGER NOT NULL
        );
        CREATE TABLE artists (name TEXT NOT NULL);
        CREATE TABLE album_images (album_rowid INTEGER NOT NULL, width INTEGER NOT NULL, url TEXT NOT NULL);
        CREATE TABLE track_artists (track_rowid INTEGER NOT NULL, artist_rowid INTEGER NOT NULL);
        CREATE UNIQUE INDEX tracks_id_unique ON tracks(id);
        CREATE INDEX tracks_popularity ON tracks(popularity);
        CREATE INDEX tracks_isrc ON tracks(external_id_isrc);
        """
    )
    connection.execute("INSERT INTO albums(rowid, name, release_date) VALUES (1, 'Album', '1999-06-01')")
    connection.execute(
        "INSERT INTO tracks(rowid, id, external_id_isrc, name, popularity, preview_url, duration_ms, album_rowid) "
        "VALUES (1, 'spotify-id', 'DEABC1234567', 'Archive Song', 78, 'https://example.test/preview', 180000, 1)"
    )
    connection.execute("INSERT INTO artists(rowid, name) VALUES (1, 'Archive Artist')")
    connection.execute("INSERT INTO track_artists(track_rowid, artist_rowid) VALUES (1, 1)")
    connection.commit()
    connection.close()


def test_archive_catalog_search_is_read_only_and_returns_metadata(tmp_path):
    database_path = tmp_path / "spotify_clean.sqlite3"
    _archive_db(database_path)
    client = create_app(str(database_path)).test_client()

    response = client.get('/v1/search?q=DEABC1234567')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['query_mode'] == 'identifier'
    assert payload['results'] == [{
        'album_name': 'Album',
        'artists': 'Archive Artist',
        'cover_url': None,
        'duration_ms': 180000,
        'isrc': 'DEABC1234567',
        'popularity': 78,
        'source': 'spotify_archive_2025_07',
        'spotify_id': 'spotify-id',
        'title': 'Archive Song',
        'year': 1999,
    }]
    assert 'preview_url' not in payload['results'][0]
    assert sqlite3.connect(database_path).execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 1


def test_archive_catalog_reports_missing_database(tmp_path):
    client = create_app(str(tmp_path / 'missing.sqlite3')).test_client()

    assert client.get('/healthz').status_code == 503
    assert client.get('/v1/search?q=Song').status_code == 503


def test_archive_catalog_bulk_isrc_lookup_uses_metadata_only_fields(tmp_path):
    database_path = tmp_path / "spotify_clean.sqlite3"
    _archive_db(database_path)
    client = create_app(str(database_path)).test_client()

    response = client.post('/v1/isrc-bulk-lookup', json={'isrcs': ['DEABC1234567']})

    assert response.status_code == 200
    assert response.get_json()['results'] == [{
        'album_name': 'Album',
        'artists': None,
        'cover_url': None,
        'duration_ms': 180000,
        'isrc': 'DEABC1234567',
        'popularity': 78,
        'source': 'spotify_archive_2025_07',
        'spotify_id': 'spotify-id',
        'title': 'Archive Song',
        'year': 1999,
    }]


def test_qb_archive_client_returns_review_only_candidates(app):
    app.config['SPOTIFY_ARCHIVE_CATALOG_URL'] = 'http://archive.test'

    with patch('musicround.helpers.spotify_archive.requests.get') as get:
        get.return_value.ok = True
        get.return_value.json.return_value = {
            'snapshot': 'spotify_archive_2025_07',
            'query_mode': 'identifier',
            'results': [{'spotify_id': 'spotify-id', 'isrc': 'DEABC1234567'}],
        }
        payload = search_spotify_archive_catalog(app, 'DEABC1234567')

    assert payload['review_only'] is True
    assert payload['results'][0]['isrc'] == 'DEABC1234567'


def test_qb_archive_client_requires_configuration(app):
    with __import__('pytest').raises(SpotifyArchiveError, match='not configured'):
        search_spotify_archive_catalog(app, 'Archive Song')
    assert spotify_archive_catalog_status(app)['configured'] is False


def test_qb_archive_api_requires_login(client):
    response = client.get('/api/songs/archive-search?q=Archive')
    assert response.status_code in (302, 401, 403)


def test_qb_archive_api_returns_candidates(app, client):
    _create_user_and_login(app, client, 'archiveuser', 'archive@example.com')
    with patch('musicround.routes.api.search_spotify_archive_catalog') as search:
        search.return_value = {
            'results': [{'title': 'Archive Song', 'isrc': 'DEABC1234567'}],
            'snapshot': 'spotify_archive_2025_07',
            'review_only': True,
        }
        response = client.get('/api/songs/archive-search?q=Archive')

    assert response.status_code == 200
    assert response.get_json()['review_only'] is True


def test_archive_backfill_fills_missing_fields_without_replacing_existing_preview(app):
    from musicround.models import Song, db
    from musicround.services import automation

    with app.app_context():
        song = Song(
            title='Existing title', artist='Existing artist', isrc='DEABC1234567',
            preview_url='https://deezer.example.test/preview',
        )
        db.session.add(song)
        db.session.commit()
        with patch('musicround.services.automation.bulk_lookup_spotify_archive_isrcs') as lookup:
            lookup.return_value = {
                'results': [{
                    'isrc': 'DEABC1234567', 'spotify_id': 'spotify-id', 'album_name': 'Archive Album',
                    'year': 1999, 'duration_ms': 180000, 'cover_url': 'https://example.test/cover',
                    'popularity': 78,
                }],
                'snapshot': 'spotify_archive_2025_07',
            }
            result = automation.backfill_songs_from_spotify_archive(dry_run=False)
        refreshed = db.session.get(Song, song.id)

    assert result['processed_count'] == 1
    assert result['matched_count'] == 1
    assert result['updated_count'] == 1
    assert refreshed.spotify_id == 'spotify-id'
    assert refreshed.album_name == 'Archive Album'
    assert refreshed.preview_url == 'https://deezer.example.test/preview'
    assert refreshed.popularity == 78
    assert 'spotify_archive_2025_07' in refreshed.metadata_sources
