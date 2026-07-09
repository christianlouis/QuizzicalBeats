"""Optional read-only adapter for a locally restored Openmusic Database dump."""

from __future__ import annotations

import re
from typing import Any

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OmdbError(ValueError):
    """Raised for safe, user-facing OMDB configuration or query failures."""


def _identifier(value: str, label: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value or ""):
        raise OmdbError(f"OMDB {label} contains an invalid SQL identifier.")
    return value


def omdb_catalog_status(app) -> dict[str, Any]:
    """Return a credential-safe status for the optional OMDB mirror."""
    server_url = (app.config.get("OMDB_SERVER_URL") or "").rstrip("/")
    if server_url:
        try:
            response = requests.get(f"{server_url}/status", timeout=app.config.get("OMDB_SERVER_TIMEOUT", 10))
            payload = response.json() if response.status_code == 200 else {}
            return {
                "configured": True,
                "mode": "openmusic_server",
                "online": bool(payload.get("online")),
                "title": payload.get("title"),
                "message": "OMDB/Openmusic candidate server is available." if payload.get("online") else "OMDB server did not report online.",
            }
        except (requests.RequestException, ValueError):
            return {
                "configured": True,
                "mode": "openmusic_server",
                "online": False,
                "message": "OMDB server could not be reached.",
            }
    database_url = app.config.get("OMDB_DATABASE_URL")
    if not database_url:
        return {
            "configured": False,
            "backend": None,
            "message": "Set OMDB_DATABASE_URL to enable the optional read-only OMDB catalog.",
        }
    try:
        url = make_url(database_url)
        backend = url.get_backend_name()
    except Exception:
        backend = "unknown"
    return {
        "configured": True,
        "backend": backend,
        "schema": app.config.get("OMDB_SCHEMA", "public"),
        "message": "Optional OMDB catalog is configured for read-only candidate discovery.",
    }


def search_omdb_catalog(app, query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search Openmusic demo API or a local OMDB mirror without leaking URLs."""
    normalized_query = (query or "").strip()
    if len(normalized_query) < 2:
        raise OmdbError("OMDB search query must contain at least two characters.")
    if limit < 1 or limit > 100:
        raise OmdbError("OMDB search limit must be between 1 and 100.")

    server_url = (app.config.get("OMDB_SERVER_URL") or "").rstrip("/")
    if server_url:
        try:
            response = requests.get(
                f"{server_url}/search",
                params={"q": normalized_query},
                timeout=app.config.get("OMDB_SERVER_TIMEOUT", 10),
            )
            if response.status_code >= 400:
                raise OmdbError("OMDB catalog search failed. Check the server logs and mirror schema.")
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            app.logger.warning("OMDB server search failed: %s", exc, exc_info=True)
            raise OmdbError("OMDB catalog search failed. Check the server logs and mirror schema.") from exc
        rows = []
        for track in (payload.get("Tracks") or [])[:limit]:
            album = track.get("Album") or {}
            artists = album.get("Artists") or []
            featured = track.get("Features") or []
            names = [artist.get("Name") for artist in artists + featured if artist.get("Name")]
            rows.append({
                "omdb_track_id": track.get("TrackID"),
                "title": track.get("Title"),
                "views": track.get("Views"),
                "runtime_seconds": track.get("Length"),
                "album_name": album.get("Title"),
                "year": album.get("Year"),
                "artist": " / ".join(dict.fromkeys(names)),
            })
        return rows

    database_url = app.config.get("OMDB_DATABASE_URL")
    if not database_url:
        raise OmdbError("OMDB catalog is not configured.")

    schema = _identifier(app.config.get("OMDB_SCHEMA", "public"), "schema")
    tracks = _identifier(app.config.get("OMDB_TRACKS_TABLE", "tracks"), "tracks table")
    albums = _identifier(app.config.get("OMDB_ALBUMS_TABLE", "albums"), "albums table")
    artists = _identifier(app.config.get("OMDB_ARTISTS_TABLE", "artists"), "artists table")
    artist_tracks = _identifier(
        app.config.get("OMDB_ARTIST_TRACKS_TABLE", "artist_track"),
        "artist-track table",
    )
    prefix = f'"{schema}".'
    tracks_ref = f'{prefix}"{tracks}"'
    albums_ref = f'{prefix}"{albums}"'
    artists_ref = f'{prefix}"{artists}"'
    artist_tracks_ref = f'{prefix}"{artist_tracks}"'

    statement = text(
        f"""
        WITH matched_tracks AS (
            SELECT t.id, t.title, t.views, t.runtime_seconds, t.album
            FROM {tracks_ref} AS t
            WHERE t.combined_vector @@ websearch_to_tsquery('simple', :query)
            ORDER BY t.views DESC NULLS LAST, t.title ASC
            LIMIT :limit
        )
        SELECT
            t.id AS omdb_track_id,
            t.title,
            t.views,
            t.runtime_seconds,
            a.title AS album_name,
            a.year,
            string_agg(DISTINCT ar.name, ' / ' ORDER BY ar.name) AS artist
        FROM matched_tracks AS t
        LEFT JOIN {albums_ref} AS a ON a.id = t.album
        LEFT JOIN {artist_tracks_ref} AS at ON at.track_id = t.id
        LEFT JOIN {artists_ref} AS ar ON ar.id = at.artist_id
        GROUP BY t.id, t.title, t.views, t.runtime_seconds, a.title, a.year
        ORDER BY t.views DESC NULLS LAST, t.title ASC
        """
    )
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement, {"query": normalized_query, "limit": limit}).mappings()]
    except Exception as exc:
        app.logger.warning("OMDB search failed: %s", exc, exc_info=True)
        raise OmdbError("OMDB catalog search failed. Check the server logs and mirror schema.") from exc
