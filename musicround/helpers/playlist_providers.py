"""Small, provider-neutral helpers for creating quiz-round playlists.

The functions in this module deliberately use the providers' HTTP APIs directly.
They do not persist tokens or alter ``Song`` records.  Callers pass the short-lived
access token belonging to the currently signed-in account.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests


class PlaylistProviderError(RuntimeError):
    """A safe, user-facing error returned by a streaming provider."""

    def __init__(self, message: str, *, auth_required: bool = False,
                 ambiguous: bool = False, provider_status: int | None = None,
                 creation_uncertain: bool = False, playlist_missing: bool = False):
        super().__init__(message)
        self.auth_required = auth_required
        self.reconnect = auth_required
        self.ambiguous = ambiguous
        self.provider_status = provider_status
        self.creation_uncertain = creation_uncertain
        self.playlist_missing = playlist_missing


_SPOTIFY = "spotify"
_DEEZER = "deezer"
_PROVIDERS = {_SPOTIFY, _DEEZER}


def _provider(provider: str) -> str:
    name = str(provider or "").strip().lower()
    if name not in _PROVIDERS:
        raise PlaylistProviderError("This streaming provider is not supported.")
    return name


def _token(access_token: str) -> str:
    if not isinstance(access_token, str) or not access_token.strip():
        raise PlaylistProviderError("Connect your streaming account first.", auth_required=True)
    return access_token.strip()


def _request(provider: str, method: str, path: str, token: str, **kwargs: Any) -> dict:
    """Perform a provider request and collapse network/API failures safely."""
    headers = kwargs.pop("headers", {})
    params = kwargs.pop("params", None)
    if provider == _SPOTIFY:
        headers = {"Authorization": f"Bearer {token}", **headers}
        url = f"https://api.spotify.com/v1/{path.lstrip('/')}"
    else:
        params = {"access_token": token, **(params or {})}
        url = f"https://api.deezer.com/{path.lstrip('/')}"
    try:
        response = requests.request(method, url, headers=headers, params=params,
                                    timeout=15, **kwargs)
    except requests.RequestException as exc:
        raise PlaylistProviderError("The streaming service is temporarily unavailable.") from exc
    if response.status_code in (401, 403):
        raise PlaylistProviderError("Reconnect your streaming account.",
                                    auth_required=True, provider_status=response.status_code)
    if response.status_code >= 400:
        raise PlaylistProviderError("The streaming service could not update the playlist.",
                                    provider_status=response.status_code)
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise PlaylistProviderError("The streaming service returned an invalid response.") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise PlaylistProviderError("The streaming service could not update the playlist.")
    return payload if isinstance(payload, dict) else {}


def _field(song: Any, name: str) -> Any:
    value = getattr(song, name, None)
    return value if value is not None else song.get(name) if isinstance(song, dict) else None


def _clean_id(value: Any, provider: str) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if provider == _SPOTIFY:
        match = re.fullmatch(r"(?:spotify:track:|https?://open\.spotify\.com/track/)?([A-Za-z0-9]+)", value)
        return match.group(1) if match and len(match.group(1)) == 22 else None
    return value if re.fullmatch(r"\d+", value) else None


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _exact_match(items: list[dict], song: Any, provider: str) -> str | None:
    title, artist = _norm(_field(song, "title")), _norm(_field(song, "artist"))
    matches = []
    for item in items:
        candidate = item.get("track") or item if provider == _SPOTIFY else item
        if not isinstance(candidate, dict):
            continue
        item_artist = candidate.get("artists", [{}])[0].get("name") if provider == _SPOTIFY else candidate.get("artist", {}).get("name")
        if _norm(candidate.get("name") if provider == _SPOTIFY else candidate.get("title")) == title and _norm(item_artist) == artist:
            track_id = _clean_id(candidate.get("id"), provider)
            if track_id:
                matches.append(track_id)
    return matches[0] if len(matches) == 1 else None


def resolve_track(provider: str, access_token: str, song: Any) -> str | None:
    """Resolve one stored song to a provider track ID without changing the DB."""
    provider, token = _provider(provider), _token(access_token)
    local = _clean_id(_field(song, f"{provider}_id"), provider)
    if local:
        return local
    isrc = str(_field(song, "isrc") or "").strip()
    if isrc:
        query = f"isrc:{isrc}" if provider == _SPOTIFY else f'isrc:"{isrc}"'
        payload = _request(provider, "GET", "search", token,
                           params={"q": query, "type": "track", "limit": 5})
        items = payload.get("tracks", {}).get("items", []) if provider == _SPOTIFY else payload.get("data", [])
        for item in items:
            candidate = item.get("track") or item if provider == _SPOTIFY else item
            if str(candidate.get("external_ids", {}).get("isrc", "")).upper() == isrc.upper() or str(candidate.get("isrc", "")).upper() == isrc.upper():
                found = _clean_id(candidate.get("id"), provider)
                if found:
                    return found
    title, artist = str(_field(song, "title") or "").strip(), str(_field(song, "artist") or "").strip()
    if not title or not artist:
        return None
    payload = _request(provider, "GET", "search", token,
                       params={"q": f'artist:"{artist}" track:"{title}"', "type": "track", "limit": 10})
    items = payload.get("tracks", {}).get("items", []) if provider == _SPOTIFY else payload.get("data", [])
    return _exact_match(items, song, provider)


def create_playlist(provider: str, access_token: str, name: str) -> str:
    """Create a private playlist owned by the account represented by ``access_token``."""
    provider, token = _provider(provider), _token(access_token)
    clean_name = str(name or "").strip()[:200]
    if not clean_name:
        raise PlaylistProviderError("The playlist needs a name.")
    try:
        if provider == _SPOTIFY:
            payload = _request(provider, "POST", "me/playlists", token,
                               json={"name": clean_name, "public": False, "collaborative": False})
            playlist_id = _clean_id(payload.get("id"), provider)
            owner = payload.get("owner", {}).get("id")
        else:
            me = _request(provider, "GET", "user/me", token)
            owner = str(me.get("id") or "")
            if not owner:
                raise PlaylistProviderError("Your Deezer account could not be identified.", auth_required=True)
            payload = _request(provider, "POST", f"user/{owner}/playlists", token,
                               data={"title": clean_name, "public": "0"})
            playlist_id = _clean_id(payload.get("id"), provider)
            if not playlist_id:
                raise PlaylistProviderError("Deezer did not confirm a private playlist.", ambiguous=True)
            details = _request(provider, "GET", f"playlist/{playlist_id}", token)
            visibility = details.get("public")
            if visibility not in (False, 0, "0"):
                raise PlaylistProviderError("Deezer could not verify a private playlist.",
                                            ambiguous=True, creation_uncertain=True)
    except PlaylistProviderError as exc:
        if exc.auth_required:
            raise
        raise PlaylistProviderError(str(exc), provider_status=exc.provider_status,
                                    creation_uncertain=exc.provider_status is None or exc.provider_status >= 500) from exc
    if not playlist_id or (owner and payload.get("owner", {}).get("id") not in (None, owner)):
        raise PlaylistProviderError("The playlist could not be verified as belonging to your account.",
                                    ambiguous=True, creation_uncertain=True)
    return playlist_id


def sync_tracks(provider: str, access_token: str, playlist_id: str, track_ids: list[str]) -> None:
    """Add missing tracks once, retaining the order supplied by the caller."""
    provider, token = _provider(provider), _token(access_token)
    clean_playlist = str(playlist_id or "").strip()
    if provider == _SPOTIFY and not re.fullmatch(r"[A-Za-z0-9]{22}", clean_playlist):
        clean_playlist = None
    if not clean_playlist:
        raise PlaylistProviderError("The playlist ID is invalid.")
    desired = validate_tracks(provider, track_ids)
    if provider == _SPOTIFY:
        try:
            payload = _request(provider, "GET", f"playlists/{clean_playlist}/items", token,
                               params={"limit": 100, "fields": "items(track(id)),next"})
        except PlaylistProviderError as exc:
            if exc.provider_status == 404:
                exc.playlist_missing = True
            raise
        uris = [f"spotify:track:{track_id}" for track_id in desired]
        if uris:
            _request(provider, "PUT", f"playlists/{clean_playlist}/items", token,
                     json={"uris": uris[:100]})
            for start in range(100, len(uris), 100):
                _request(provider, "POST", f"playlists/{clean_playlist}/items", token,
                         json={"uris": uris[start:start + 100]})
    else:
        try:
            payload = _request(provider, "GET", f"playlist/{clean_playlist}/tracks", token,
                               params={"limit": 100})
        except PlaylistProviderError as exc:
            if exc.provider_status == 404:
                exc.playlist_missing = True
            raise
        existing = {str(item.get("id")) for item in payload.get("data", [])}
        missing = [track_id for track_id in desired if track_id not in existing]
        if missing:
            _request(provider, "POST", f"playlist/{clean_playlist}/tracks", token,
                     data={"songs": ",".join(missing)})


def validate_tracks(provider: str, track_ids: list[str]) -> list[str]:
    """Validate provider IDs before a playlist is created or changed."""
    provider = _provider(provider)
    clean = [_clean_id(track_id, provider) for track_id in track_ids]
    if any(track_id is None for track_id in clean):
        raise PlaylistProviderError("One or more tracks are not available on this provider.")
    if len(set(clean)) != len(clean):
        raise PlaylistProviderError("A playlist cannot contain duplicate tracks.")
    return clean
