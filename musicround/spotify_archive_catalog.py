"""Read-only HTTP search service for the offline Spotify metadata archive.

The service opens SQLite from disk with a bounded page cache. It never copies
the catalog into Python memory and never serves audio or preview bytes.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request


DEFAULT_DB_PATH = "/archive/spotify_clean.sqlite3"
DEFAULT_MIN_POPULARITY = 20
DEFAULT_QUERY_TIMEOUT_SECONDS = 2.0
SNAPSHOT = "spotify_archive_2025_07"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _connection(database_path: str) -> sqlite3.Connection:
    """Open the archive as immutable, disk-backed SQLite with bounded memory use."""
    uri = f"file:{Path(database_path).resolve()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA mmap_size=0")
    connection.execute("PRAGMA cache_size=-8192")
    connection.execute("PRAGMA temp_store=FILE")
    return connection


def _exact_results(connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    """Use the source's identifier indexes for fast exact ISRC or Spotify-ID lookups."""
    rows = connection.execute(
        """
        SELECT tracks.id AS spotify_id, tracks.external_id_isrc AS isrc,
               tracks.name AS title, tracks.popularity AS popularity,
               tracks.preview_url AS preview_url, tracks.duration_ms AS duration_ms,
               albums.name AS album_name, albums.release_date AS release_date,
               (SELECT url FROM album_images WHERE album_rowid = albums.rowid ORDER BY width DESC LIMIT 1) AS cover_url,
               GROUP_CONCAT(artists.name, ', ') AS artists
        FROM tracks
        JOIN albums ON albums.rowid = tracks.album_rowid
        JOIN track_artists ON track_artists.track_rowid = tracks.rowid
        JOIN artists ON artists.rowid = track_artists.artist_rowid
        WHERE tracks.id = :query OR tracks.external_id_isrc = :query
        GROUP BY tracks.rowid
        ORDER BY tracks.popularity DESC, tracks.id ASC
        LIMIT :limit
        """,
        {"query": query, "limit": limit},
    ).fetchall()
    return [_row_payload(row) for row in rows]


def _isrc_results(connection: sqlite3.Connection, isrcs: list[str]) -> list[dict[str, Any]]:
    """Return the most popular archive recording for each exact ISRC."""
    placeholders = ", ".join("?" for _ in isrcs)
    rows = connection.execute(
        f"""
        SELECT tracks.id AS spotify_id, tracks.external_id_isrc AS isrc,
               tracks.name AS title, tracks.popularity AS popularity,
               tracks.preview_url AS preview_url, tracks.duration_ms AS duration_ms,
               albums.name AS album_name, albums.release_date AS release_date,
               (SELECT url FROM album_images WHERE album_rowid = albums.rowid ORDER BY width DESC LIMIT 1) AS cover_url,
               GROUP_CONCAT(artists.name, ', ') AS artists
        FROM tracks
        JOIN albums ON albums.rowid = tracks.album_rowid
        JOIN track_artists ON track_artists.track_rowid = tracks.rowid
        JOIN artists ON artists.rowid = track_artists.artist_rowid
        WHERE tracks.external_id_isrc IN ({placeholders})
        GROUP BY tracks.rowid
        ORDER BY tracks.external_id_isrc ASC, tracks.popularity DESC, tracks.id ASC
        """,
        isrcs,
    ).fetchall()
    chosen: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = _row_payload(row)
        chosen.setdefault(payload["isrc"], payload)
    return list(chosen.values())


def _text_results(
    connection: sqlite3.Connection,
    query: str,
    limit: int,
    min_popularity: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Search a bounded popularity slice and interrupt slow scans predictably."""
    deadline = time.monotonic() + timeout_seconds
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10_000)
    try:
        rows = connection.execute(
            """
            SELECT tracks.id AS spotify_id, tracks.external_id_isrc AS isrc,
                   tracks.name AS title, tracks.popularity AS popularity,
                   tracks.preview_url AS preview_url, tracks.duration_ms AS duration_ms,
                   albums.name AS album_name, albums.release_date AS release_date,
                   (SELECT url FROM album_images WHERE album_rowid = albums.rowid ORDER BY width DESC LIMIT 1) AS cover_url,
                   GROUP_CONCAT(artists.name, ', ') AS artists
            FROM tracks INDEXED BY tracks_popularity
            JOIN albums ON albums.rowid = tracks.album_rowid
            JOIN track_artists ON track_artists.track_rowid = tracks.rowid
            JOIN artists ON artists.rowid = track_artists.artist_rowid
            WHERE tracks.popularity >= :min_popularity
              AND (tracks.name LIKE :pattern OR artists.name LIKE :pattern)
            GROUP BY tracks.rowid
            ORDER BY tracks.popularity DESC, tracks.id ASC
            LIMIT :limit
            """,
            {"min_popularity": min_popularity, "pattern": f"%{query}%", "limit": limit},
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise ValueError("Search took too long; use an ISRC, Spotify ID, or a more specific query.") from exc
        raise
    finally:
        connection.set_progress_handler(None, 0)
    return [_row_payload(row) for row in rows]


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Return a minimal metadata-only candidate without audio delivery data."""
    release_date = row["release_date"]
    return {
        "spotify_id": row["spotify_id"],
        "isrc": row["isrc"],
        "title": row["title"],
        "artists": row["artists"],
        "album_name": row["album_name"],
        "year": int(release_date[:4]) if release_date and release_date[:4].isdigit() else None,
        "popularity": row["popularity"],
        "duration_ms": row["duration_ms"],
        "cover_url": row["cover_url"],
        "source": SNAPSHOT,
    }


def create_app(database_path: str | None = None) -> Flask:
    """Create the internal-only archive catalog application."""
    app = Flask(__name__)
    app.config.update(
        SPOTIFY_ARCHIVE_DB_PATH=database_path or os.getenv("SPOTIFY_ARCHIVE_DB_PATH", DEFAULT_DB_PATH),
        SPOTIFY_ARCHIVE_MIN_POPULARITY=_int_env(
            "SPOTIFY_ARCHIVE_MIN_POPULARITY", DEFAULT_MIN_POPULARITY
        ),
        SPOTIFY_ARCHIVE_QUERY_TIMEOUT_SECONDS=float(
            os.getenv("SPOTIFY_ARCHIVE_QUERY_TIMEOUT_SECONDS", DEFAULT_QUERY_TIMEOUT_SECONDS)
        ),
    )

    @app.get("/healthz")
    def healthz():
        path = Path(app.config["SPOTIFY_ARCHIVE_DB_PATH"])
        return jsonify({
            "ok": path.is_file(),
            "snapshot": SNAPSHOT,
            "read_only": True,
            "database_present": path.is_file(),
        }), 200 if path.is_file() else 503

    @app.get("/v1/search")
    def search():
        query = (request.args.get("q") or "").strip()
        try:
            limit = min(max(int(request.args.get("limit", "20")), 1), 50)
        except ValueError:
            return jsonify({"error": "limit must be an integer between 1 and 50."}), 400
        if len(query) < 2:
            return jsonify({"error": "q must contain at least two characters."}), 400
        database_path = app.config["SPOTIFY_ARCHIVE_DB_PATH"]
        if not Path(database_path).is_file():
            return jsonify({"error": "Archive database is not ready."}), 503
        try:
            with _connection(database_path) as connection:
                results = _exact_results(connection, query, limit)
                mode = "identifier" if results else "text"
                if not results:
                    results = _text_results(
                        connection,
                        query,
                        limit,
                        app.config["SPOTIFY_ARCHIVE_MIN_POPULARITY"],
                        app.config["SPOTIFY_ARCHIVE_QUERY_TIMEOUT_SECONDS"],
                    )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.Error:
            app.logger.exception("Spotify archive search failed")
            return jsonify({"error": "Archive search failed."}), 500
        return jsonify({"results": results, "query_mode": mode, "snapshot": SNAPSHOT})

    @app.post("/v1/isrc-lookup")
    def isrc_lookup():
        payload = request.get_json(silent=True) or {}
        raw_isrcs = payload.get("isrcs")
        if not isinstance(raw_isrcs, list):
            return jsonify({"error": "isrcs must be a JSON array."}), 400
        isrcs = sorted({str(value).strip().upper() for value in raw_isrcs if str(value).strip()})
        if not isrcs or len(isrcs) > 500:
            return jsonify({"error": "isrcs must contain between 1 and 500 values."}), 400
        database_path = app.config["SPOTIFY_ARCHIVE_DB_PATH"]
        if not Path(database_path).is_file():
            return jsonify({"error": "Archive database is not ready."}), 503
        try:
            with _connection(database_path) as connection:
                results = _isrc_results(connection, isrcs)
        except sqlite3.Error:
            app.logger.exception("Spotify archive ISRC lookup failed")
            return jsonify({"error": "Archive ISRC lookup failed."}), 500
        return jsonify({"results": results, "snapshot": SNAPSHOT})

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8080)
