"""Tests for the optional Openmusic/OMDB discovery integration."""

from unittest.mock import MagicMock, patch

from musicround.helpers.omdb import omdb_catalog_status, search_omdb_catalog
from musicround.services import automation


def _server_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def test_openmusic_server_status_is_credential_safe(app):
    app.config["OMDB_SERVER_URL"] = "https://server.example.test"
    with patch(
        "musicround.helpers.omdb.requests.get",
        return_value=_server_response({"online": True, "title": "Demo"}),
    ):
        status = omdb_catalog_status(app)

    assert status == {
        "configured": True,
        "mode": "openmusic_server",
        "online": True,
        "title": "Demo",
        "message": "OMDB/Openmusic candidate server is available.",
    }


def test_openmusic_search_returns_discovery_rows(app):
    app.config["OMDB_SERVER_URL"] = "https://server.example.test"
    payload = {
        "Tracks": [
            {
                "TrackID": "omdb-track-1",
                "Title": "We Got the Moves",
                "Views": 20000000,
                "Length": 207,
                "Features": [],
                "Album": {
                    "Title": "TEKKNO",
                    "Year": 2022,
                    "Artists": [{"Name": "Electric Callboy"}],
                },
            }
        ]
    }
    with patch("musicround.helpers.omdb.requests.get", return_value=_server_response(payload)):
        rows = search_omdb_catalog(app, "Electric Callboy", limit=10)

    assert rows == [{
        "omdb_track_id": "omdb-track-1",
        "title": "We Got the Moves",
        "views": 20000000,
        "runtime_seconds": 207,
        "album_name": "TEKKNO",
        "year": 2022,
        "artist": "Electric Callboy",
    }]


def test_omdb_seed_source_returns_review_only_candidates(app):
    with app.app_context():
        source = automation.register_seed_source(
            name="OMDB Test Catalog",
            source_type="curated",
            provider="omdb",
        )["seed_source"]
        with patch(
            "musicround.services.automation.search_omdb_catalog",
            return_value=[{
                "omdb_track_id": "omdb-track-1",
                "title": "We Got the Moves",
                "artist": "Electric Callboy",
                "album_name": "TEKKNO",
                "year": 2022,
                "runtime_seconds": 207,
                "views": 20000000,
            }],
        ):
            result = automation.fetch_seed_source_candidates(
                source["id"],
                query="Electric Callboy",
                limit=10,
            )

    assert result["count"] == 1
    assert result["ready_for_import"] is False
    candidate = result["candidates"][0]
    assert candidate["omdb_track_id"] == "omdb-track-1"
    assert candidate["source_views"] == 20000000
    assert candidate["popularity"] is None
    assert candidate["needs_review"] is True
