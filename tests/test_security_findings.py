"""Regression coverage for the imported high and critical security findings."""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("AUTOMATION_TOKEN", "test-automation-token-for-testing")

from musicround.helpers.auth_helpers import _oauth_email_can_link
from musicround.models import User, db
from musicround import mcp_server


def _login_user(app, client):
    with app.app_context():
        user = User(username="security-user", email="security@example.com")
        user.password = "SecurePassword123!"
        db.session.add(user)
        db.session.commit()
    response = client.post(
        "/users/login",
        data={"username": "security-user", "password": "SecurePassword123!"},
    )
    assert response.status_code == 302
    return user


def test_spotify_email_without_verification_cannot_link_existing_account():
    """Spotify profile email must not be treated as identity proof."""
    assert _oauth_email_can_link({"email": "victim@example.com"}, "spotify") is False
    assert _oauth_email_can_link(
        {"email": "victim@example.com", "email_verified": True}, "spotify"
    ) is True


def test_data_route_only_serves_owned_custom_audio(app, client, tmp_path):
    """Authenticated data access cannot read the SQLite DB or backups."""
    _login_user(app, client)
    data_dir = tmp_path / "data"
    (data_dir / "custommp3" / "security-user").mkdir(parents=True)
    (data_dir / "custommp3" / "security-user" / "intro.mp3").write_bytes(b"audio")
    (data_dir / "song_data.db").write_bytes(b"database-secret")
    app.config["DATA_DIR"] = str(data_dir)

    assert client.get("/data/song_data.db").status_code == 404
    assert client.get("/data/backups/backup.zip").status_code == 404
    response = client.get("/data/custommp3/security-user/intro.mp3")
    assert response.status_code == 200
    assert response.data == b"audio"


def test_data_route_rejects_traversal_and_symlink_escape(app, client, tmp_path):
    """Custom audio paths cannot escape the owner's real upload directory."""
    _login_user(app, client)
    data_dir = tmp_path / "data"
    user_dir = data_dir / "custommp3" / "security-user"
    user_dir.mkdir(parents=True)
    (data_dir / "song_data.db").write_bytes(b"database-secret")
    (user_dir / "link.mp3").symlink_to(data_dir / "song_data.db")
    (data_dir / "custommp3" / "other-user").mkdir()
    (data_dir / "custommp3" / "linked-user").symlink_to(
        data_dir / "custommp3" / "other-user", target_is_directory=True
    )
    app.config["DATA_DIR"] = str(data_dir)

    assert client.get(
        "/data/custommp3/security-user/%2e%2e/%2e%2e/song_data.db"
    ).status_code == 404
    assert client.get("/data/custommp3/security-user/link.mp3").status_code == 404
    assert client.get("/data/custommp3/linked-user/intro.mp3").status_code == 404


def test_data_route_denies_other_user_audio(app, client, tmp_path):
    """A normal user cannot read another user's custom audio."""
    _login_user(app, client)
    other_file = tmp_path / "data" / "custommp3" / "other-user" / "intro.mp3"
    other_file.parent.mkdir(parents=True)
    other_file.write_bytes(b"other-user-audio")
    app.config["DATA_DIR"] = str(tmp_path / "data")

    assert client.get("/data/custommp3/other-user/intro.mp3").status_code == 403


def test_admin_can_read_other_user_audio(app, client, tmp_path):
    """Administrators retain the intended cross-user audio support."""
    with app.app_context():
        user = User(username="security-admin", email="security-admin@example.com", is_admin=True)
        user.password = "SecurePassword123!"
        db.session.add(user)
        db.session.commit()
    response = client.post(
        "/users/login",
        data={"username": "security-admin", "password": "SecurePassword123!"},
    )
    assert response.status_code == 302
    other_file = tmp_path / "data" / "custommp3" / "other-user" / "intro.mp3"
    other_file.parent.mkdir(parents=True)
    other_file.write_bytes(b"other-user-audio")
    app.config["DATA_DIR"] = str(tmp_path / "data")

    response = client.get("/data/custommp3/other-user/intro.mp3")
    assert response.status_code == 200
    assert response.data == b"other-user-audio"


def test_spotify_callback_rejects_unverified_existing_account_link(app, client):
    """The live callback must refuse an unverified Spotify email match."""
    with app.app_context():
        user = User(username="oauth-victim", email="victim@example.com")
        user.password = "SecurePassword123!"
        db.session.add(user)
        db.session.commit()

    spotify_client = MagicMock()
    spotify_client.authorize_access_token.return_value = {
        "access_token": "attacker-access",
    }
    with patch.object(
        __import__("musicround.routes.auth", fromlist=["oauth"]).oauth,
        "spotify",
        spotify_client,
        create=True,
    ), patch("musicround.routes.auth.get_spotify_user_info", return_value={
        "id": "attacker-spotify-id",
        "email": "victim@example.com",
    }), patch("musicround.routes.auth.update_oauth_tokens") as update_tokens:
        response = client.get("/callback")

    assert response.status_code == 302
    update_tokens.assert_not_called()
    with app.app_context():
        assert User.query.filter_by(username="oauth-victim").one().spotify_id is None


def test_mcp_datastore_is_read_only_and_catalog_scoped():
    """MCP cannot enumerate, mutate, or reveal authentication datastore state."""
    schema = {"object_types": ["song", "user"], "objects": [
        {"object_type": "song"}, {"object_type": "user"}
    ]}
    with patch.object(mcp_server, "_with_app_context", return_value=schema):
        assert mcp_server.datastore_schema()["object_types"] == ["song"]

    with pytest.raises(ValueError, match="limited to"):
        mcp_server.list_datastore_objects("user")
    with pytest.raises(ValueError, match="disabled"):
        mcp_server.update_datastore_object("song", 1, {"title": "changed"})
    with pytest.raises(ValueError, match="disabled"):
        mcp_server.delete_datastore_object("song", 1)
    with pytest.raises(ValueError, match="sensitive"):
        mcp_server.get_datastore_object("song", 1, include_sensitive=True)
