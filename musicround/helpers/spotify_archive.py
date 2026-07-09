"""Client for the optional, internal Spotify metadata archive service."""

from __future__ import annotations

from typing import Any

import requests


class SpotifyArchiveError(ValueError):
    """Raised when the internal archive service cannot safely serve a request."""


def _base_url(app) -> str:
    return str(app.config.get("SPOTIFY_ARCHIVE_CATALOG_URL") or "").rstrip("/")


def spotify_archive_catalog_status(app) -> dict[str, Any]:
    """Return a credential-safe readiness summary for the optional archive."""
    base_url = _base_url(app)
    if not base_url:
        return {
            "configured": False,
            "available": False,
            "message": "Offline Spotify archive catalog is not configured.",
        }
    try:
        response = requests.get(
            f"{base_url}/healthz",
            timeout=app.config.get("SPOTIFY_ARCHIVE_CATALOG_TIMEOUT", 5),
        )
        payload = response.json() if response.ok else {}
    except (requests.RequestException, ValueError) as exc:
        app.logger.info("Spotify archive catalog health check failed: %s", exc)
        return {
            "configured": True,
            "available": False,
            "message": "Offline Spotify archive catalog is unavailable.",
        }
    return {
        "configured": True,
        "available": bool(payload.get("ok")),
        "message": "Offline Spotify archive catalog is ready."
        if payload.get("ok")
        else "Offline Spotify archive catalog is unavailable.",
        "snapshot": payload.get("snapshot"),
    }


def search_spotify_archive_catalog(app, query: str, limit: int = 20) -> dict[str, Any]:
    """Search review-only Spotify archive candidates through the internal service."""
    query = (query or "").strip()
    if len(query) < 2:
        raise SpotifyArchiveError("Archive search query must contain at least two characters.")
    if not 1 <= limit <= 50:
        raise SpotifyArchiveError("Archive search limit must be between 1 and 50.")
    base_url = _base_url(app)
    if not base_url:
        raise SpotifyArchiveError("Offline Spotify archive catalog is not configured.")
    try:
        response = requests.get(
            f"{base_url}/v1/search",
            params={"q": query, "limit": limit},
            timeout=app.config.get("SPOTIFY_ARCHIVE_CATALOG_TIMEOUT", 5),
        )
    except requests.RequestException as exc:
        app.logger.warning("Spotify archive catalog search failed: %s", exc)
        raise SpotifyArchiveError("Offline Spotify archive catalog is unavailable.") from exc
    if response.status_code == 400:
        try:
            message = response.json().get("error")
        except ValueError:
            message = None
        raise SpotifyArchiveError(message or "Archive search request was invalid.")
    if not response.ok:
        app.logger.warning("Spotify archive catalog returned status %s", response.status_code)
        raise SpotifyArchiveError("Offline Spotify archive catalog search failed.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SpotifyArchiveError("Offline Spotify archive catalog returned invalid data.") from exc
    results = payload.get("results")
    if not isinstance(results, list):
        raise SpotifyArchiveError("Offline Spotify archive catalog returned invalid data.")
    return {
        "results": results,
        "snapshot": payload.get("snapshot"),
        "query_mode": payload.get("query_mode"),
        "review_only": True,
        "hints": [
            "Archive candidates are metadata-only and are never imported automatically.",
            "Resolve a selected candidate through Deezer before adding or replacing a song preview.",
        ],
    }
