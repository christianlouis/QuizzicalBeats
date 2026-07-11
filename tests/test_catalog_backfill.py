import pytest
from unittest.mock import MagicMock, patch

from musicround.models import db, Song
from musicround.helpers.catalog_backfill import run_backfill
from musicround.helpers.spotify_archive import SpotifyArchiveError


@pytest.fixture
def test_songs(app):
    """Create test songs with varied catalog metadata states.

    Args:
        app: Flask application fixture with a configured test database.

    Returns:
        list: IDs for the five created songs.
    """
    # A: Has deezer_id, missing isrc
    s1 = Song(title="Song 1", artist="Artist 1", deezer_id="d1")

    # B: Has isrc, missing spotify_id
    s2 = Song(title="Song 2", artist="Artist 2", isrc="ISRC1")

    # C: Has nothing but title
    s3 = Song(title="Song 3", artist="Artist 3")

    # D: Has both deezer_id and isrc, but missing spotify_id
    s4 = Song(title="Song 4", artist="Artist 4", deezer_id="d2", isrc="ISRC2")

    # E: Fully populated
    s5 = Song(
        title="Song 5",
        artist="Artist 5",
        isrc="ISRC3",
        spotify_id="s3",
        deezer_id="d3",
        danceability=0.8)

    db.session.add_all([s1, s2, s3, s4, s5])
    db.session.commit()

    return [s1.id, s2.id, s3.id, s4.id, s5.id]


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill(mock_features, mock_archive, mock_deezer, app, test_songs):
    """Test committed backfill execution across all three stages."""
    # Setup mocks
    mock_deezer.side_effect = lambda did, app, album_cache=None: {
        "d1": {"isrc": "ISRC0", "popularity": 50, "year": "2020", "genre": "Pop"},
        "d2": {"isrc": "ISRC2", "popularity": 60}
    }.get(did, {})

    mock_archive.return_value = {
        "results": [
            {"isrc": "ISRC1", "spotify_id": "s1"},
            {"isrc": "ISRC2", "spotify_id": "s2"}
        ]
    }

    mock_features.return_value = {
        "results": [
            {"spotify_id": "s1", "danceability": 0.5, "energy": 0.6},
            {"spotify_id": "s2", "danceability": 0.7, "energy": 0.8}
        ]
    }

    # Run backfill
    result = run_backfill(dry_run=False, limit=None, chunk_size=10, sleep_sec=0)

    # Assert coverage before
    assert result["coverage_before"]["total_songs"] == 5
    assert result["coverage_before"]["with_isrc"] == 3  # ISRC1, ISRC2, ISRC3

    # Assert coverage after
    assert result["coverage_after"]["total_songs"] == 5
    assert result["coverage_after"]["with_isrc"] == 4  # +ISRC0 from Stage A
    assert result["coverage_after"]["with_spotify_id"] == 3  # s2, s4 + s5 existing
    assert result["coverage_after"]["with_audio_features"] == 3  # s2, s4 + s5 existing

    # Assert stage A
    assert result["stage_a"]["processed"] == 1  # only s1 matches
    assert result["stage_a"]["updated"] == 1  # s1 got updated

    # Assert stage B
    # Before stage A, s2, s4, s5 have ISRC. After stage A, s1 has ISRC too.
    # The query for B filters isrc != None AND spotify_id == None.
    # Matches: s1, s2, s4.
    assert result["stage_b"]["processed"] == 3
    assert result["stage_b"]["updated"] == 2  # s1 not in archive mock, s2 -> s1, s4 -> s2 mapped.

    # Assert stage C
    assert result["stage_c"]["processed"] == 2  # s1, s2 newly mapped
    assert result["stage_c"]["updated"] == 2

    # Assert final states
    s1 = db.session.get(Song, test_songs[0])
    assert s1.isrc == "ISRC0"
    assert s1.popularity == 50
    assert s1.year == 2020
    assert s1.genre == "Pop"

    s2 = db.session.get(Song, test_songs[1])
    assert s2.spotify_id == "s1"
    assert s2.danceability == 0.5

    s4 = db.session.get(Song, test_songs[3])
    assert s4.spotify_id == "s2"
    assert s4.danceability == 0.7


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_dry_run(mock_features, mock_archive, mock_deezer, app, test_songs):
    """Test dry-run reporting without persisting catalog changes."""
    mock_deezer.side_effect = lambda did, app, album_cache=None: {
        "d1": {"isrc": "ISRC0", "popularity": 50, "year": "2020", "genre": "Pop"}
    }.get(did, {})

    mock_archive.return_value = {
        "results": [
            {"isrc": "ISRC1", "spotify_id": "s1"},
            {"isrc": "ISRC2", "spotify_id": "s2"}
        ]
    }

    mock_features.return_value = {
        "results": [
            {"spotify_id": "s1", "danceability": 0.5},
            {"spotify_id": "s2", "danceability": 0.7}
        ]
    }

    result = run_backfill(dry_run=True, limit=None, chunk_size=10, sleep_sec=0)

    assert result["stage_a"]["updated"] == 1
    assert result["stage_b"]["updated"] == 2
    assert result["stage_c"]["updated"] == 2

    # Assert nothing was actually saved
    db.session.rollback()  # Clear identity map if any

    s1 = db.session.get(Song, test_songs[0])
    assert s1.isrc is None

    s2 = db.session.get(Song, test_songs[1])
    assert s2.spotify_id is None


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_json_output(mock_features, mock_archive, mock_deezer, app, test_songs):
    """Test that backfill results remain JSON serializable."""
    import json

    mock_deezer.return_value = {}
    mock_archive.return_value = {"results": []}
    mock_features.return_value = {"results": []}

    result = run_backfill(dry_run=True, limit=None, chunk_size=10, sleep_sec=0)

    # Verify the result can be serialized to JSON properly
    try:
        json_output = json.dumps(result, indent=2)
        assert "stage_a" in json_output
        assert "coverage_before" in json_output
    except TypeError as exc:
        pytest.fail(f"run_backfill result is not JSON serializable: {exc}")


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_respects_limit(mock_features, mock_archive, mock_deezer, app, test_songs):
    """Test that each backfill stage respects the configured limit."""
    mock_deezer.side_effect = lambda did, app, album_cache=None: {
        "d1": {"isrc": "ISRC0", "popularity": 50}
    }.get(did, {})

    mock_archive.return_value = {
        "results": [
            {"isrc": "ISRC0", "spotify_id": "s0"},
            {"isrc": "ISRC1", "spotify_id": "s1"},
            {"isrc": "ISRC2", "spotify_id": "s2"}
        ]
    }

    mock_features.return_value = {
        "results": [
            {"spotify_id": "s0", "danceability": 0.4}
        ]
    }

    result = run_backfill(dry_run=False, limit=1, chunk_size=1, sleep_sec=0)

    assert result["stage_a"]["processed"] == 1
    assert result["stage_a"]["updated"] == 1
    assert result["stage_b"]["processed"] == 1
    assert result["stage_b"]["updated"] == 1
    assert result["stage_c"]["processed"] == 1
    assert result["stage_c"]["updated"] == 1

    s1 = db.session.get(Song, test_songs[0])
    s2 = db.session.get(Song, test_songs[1])
    assert s1.spotify_id == "s0"
    assert s1.danceability == 0.4
    assert s2.spotify_id is None
    assert result["coverage_after"]["with_spotify_id"] == 2  # s1 mapped + s5 existing


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_skips_stage_b_archive_errors(
        mock_features, mock_archive, mock_deezer, app, test_songs, caplog):
    """Test that Stage B archive failures are logged and skipped."""
    mock_deezer.return_value = {}
    mock_archive.side_effect = SpotifyArchiveError("archive unavailable")
    mock_features.return_value = {"results": []}

    result = run_backfill(dry_run=False, limit=None, chunk_size=10, sleep_sec=0)

    assert result["stage_b"]["processed"] == 2
    assert result["stage_b"]["updated"] == 0
    assert "Stage B archive lookup failed" in caplog.text


@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_skips_duplicate_spotify_ids(
        mock_features, mock_archive, mock_deezer, app, test_songs, caplog):
    """Test that Stage B skips Spotify IDs already assigned to another song."""
    mock_deezer.return_value = {}
    mock_archive.return_value = {
        "results": [
            {"isrc": "ISRC1", "spotify_id": "s3"},
            {"isrc": "ISRC2", "spotify_id": "s2"}
        ]
    }
    mock_features.return_value = {
        "results": [
            {"spotify_id": "s2", "danceability": 0.7}
        ]
    }

    result = run_backfill(dry_run=False, limit=None, chunk_size=10, sleep_sec=0)

    s2 = db.session.get(Song, test_songs[1])
    s4 = db.session.get(Song, test_songs[3])
    assert s2.spotify_id is None
    assert s4.spotify_id == "s2"
    assert result["stage_b"]["updated"] == 1
    assert "Stage B skipped duplicate Spotify ID s3" in caplog.text


@patch('musicround.helpers.import_helper.ImportHelper._fetch_audio_features_for_song')
@patch('musicround.helpers.catalog_backfill.get_deezer_track_metadata')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_isrcs')
@patch('musicround.helpers.catalog_backfill.bulk_lookup_spotify_archive_audio_features')
def test_run_backfill_stage_c_uses_spotify_fallback(
        mock_features, mock_archive, mock_deezer, mock_fetch_features, app, test_songs):
    """Test that Stage C falls back to the Spotify client on archive errors."""
    app.config['sp'] = MagicMock()
    mock_deezer.return_value = {}
    mock_archive.return_value = {
        "results": [
            {"isrc": "ISRC1", "spotify_id": "s1"}
        ]
    }
    mock_features.side_effect = SpotifyArchiveError("features unavailable")

    def set_features(sp, song, sid):
        song.danceability = 0.9

    mock_fetch_features.side_effect = set_features

    result = run_backfill(dry_run=False, limit=None, chunk_size=10, sleep_sec=0)

    s2 = db.session.get(Song, test_songs[1])
    assert s2.spotify_id == "s1"
    assert s2.danceability == 0.9
    assert result["stage_c"]["processed"] == 1
    assert result["stage_c"]["updated"] == 1
