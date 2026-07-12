"""Tests for reusable OAuth connection status helpers."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from musicround.helpers.oauth_status import dropbox_token_status, spotify_token_status, token_notice
from musicround.helpers.service_health import dropbox_service_health, spotify_service_health


def _user(**overrides):
    data = {
        "spotify_id": None,
        "spotify_token": None,
        "spotify_refresh_token": None,
        "spotify_token_expiry": None,
        "dropbox_id": None,
        "dropbox_token": None,
        "dropbox_refresh_token": None,
        "dropbox_token_expiry": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_spotify_status_marks_preserved_link_without_tokens_as_reconnect_required():
    status = spotify_token_status(_user(spotify_id="spotify-user"), now=datetime(2026, 7, 6, 12, 0, 0))

    assert status["status"] == "reconnect_required"
    assert status["reconnect_required"] is True
    assert status["issue_code"] == "spotify_reconnect_required"
    assert token_notice(status)["title"] == "Reconnect required"


def test_spotify_status_warns_before_expiry_without_exposing_tokens():
    now = datetime(2026, 7, 6, 12, 0, 0)
    status = spotify_token_status(
        _user(
            spotify_id="spotify-user",
            spotify_token="secret-access-token",
            spotify_refresh_token="secret-refresh-token",
            spotify_token_expiry=now + timedelta(minutes=5),
        ),
        now=now,
    )

    assert status["status"] == "expiring"
    assert status["expires_soon"] is True
    assert "secret" not in repr(status)
    assert token_notice(status)["message"] == "Refresh or reconnect Spotify before starting a long import."


def test_dropbox_status_marks_expired_access_tokens_as_refreshable():
    now = datetime(2026, 7, 6, 12, 0, 0)
    status = dropbox_token_status(
        _user(
            dropbox_id="dropbox-user",
            dropbox_token="dropbox-access",
            dropbox_refresh_token="dropbox-refresh",
            dropbox_token_expiry=now - timedelta(minutes=1),
        ),
        now=now,
    )

    assert status["status"] == "refresh_required"
    assert status["expired"] is True
    assert status["reconnect_required"] is False
    assert status["message"] == "Dropbox will refresh automatically before exporting round packages."


def test_service_health_surfaces_machine_readable_token_warnings(app):
    with app.app_context():
        user = _user(
            spotify_id="spotify-user",
            spotify_token="access",
            spotify_refresh_token="refresh",
            spotify_token_expiry=datetime.now() + timedelta(minutes=5),
            dropbox_id="dropbox-user",
            dropbox_token="access",
            dropbox_refresh_token="refresh",
            dropbox_token_expiry=datetime.now() - timedelta(minutes=5),
        )

        spotify_health = spotify_service_health(user)
        dropbox_health = dropbox_service_health(user)

    assert spotify_health["status"] == "warning"
    assert "spotify_token_expiring" in {issue["code"] for issue in spotify_health["issues"]}
    assert spotify_health["token_status"]["expires_at"].startswith(str(datetime.now().year))

    assert dropbox_health["status"] == "warning"
    assert dropbox_health["issues"][0]["code"] == "dropbox_token_refresh_required"
    assert dropbox_health["token_status"]["reconnect_required"] is False
