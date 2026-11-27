from types import SimpleNamespace

import pytest

from musicround.helpers import playlist_providers as providers


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def song(**values):
    defaults = dict(title="Song", artist="Artist", isrc=None,
                    spotify_id=None, deezer_id=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_resolve_uses_local_provider_id_without_network(monkeypatch):
    monkeypatch.setattr(providers.requests, "request", lambda *a, **k: pytest.fail("network"))
    track_id = "A" * 22
    assert providers.resolve_track("spotify", "token", song(spotify_id=track_id)) == track_id
    assert providers.resolve_track("deezer", "token", song(deezer_id=12345)) == "12345"


def test_resolve_isrc_before_exact_search(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response(payload={"tracks": {"items": [{
            "id": "S" * 22, "name": "Song", "artists": [{"name": "Artist"}],
            "external_ids": {"isrc": "US123"},
        }]}})

    monkeypatch.setattr(providers.requests, "request", request)
    assert providers.resolve_track("spotify", "token", song(isrc="US123")) == "S" * 22
    assert len(calls) == 1


def test_sync_is_idempotent_and_preserves_missing_order(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return Response(payload={"items": [{"track": {"id": "A" * 22}}]})
        return Response(status=201, payload={"snapshot_id": "snap"})

    monkeypatch.setattr(providers.requests, "request", request)
    playlist = "P" * 22
    ids = ["A" * 22, "B" * 22, "C" * 22]
    providers.sync_tracks("spotify", "token", playlist, ids)
    assert calls[-1][2]["json"] == {"uris": [f"spotify:track:{i}" for i in ids]}


def test_deezer_sync_does_not_duplicate_existing_tracks(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return Response(payload={"data": [{"id": "2"}]})
        return Response(payload={"id": "playlist"})

    monkeypatch.setattr(providers.requests, "request", request)
    providers.sync_tracks("deezer", "token", "123", ["2", "3"])
    assert calls[-1][2]["data"] == {"songs": "3"}


def test_create_playlist_is_private(monkeypatch):
    def request(method, url, **kwargs):
        assert kwargs["json"]["public"] is False
        return Response(payload={"id": "P" * 22, "owner": {"id": "owner"}})

    monkeypatch.setattr(providers.requests, "request", request)
    assert providers.create_playlist("spotify", "token", "Round") == "P" * 22


def test_provider_errors_are_sanitized(monkeypatch):
    monkeypatch.setattr(
        providers.requests, "request",
        lambda *a, **k: Response(status=401, payload={"error": "secret detail"}),
    )
    with pytest.raises(providers.PlaylistProviderError) as error:
        providers.resolve_track("spotify", "token", song())
    assert error.value.auth_required is True
    assert "secret" not in str(error.value)
