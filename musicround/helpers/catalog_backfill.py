import time
from typing import Any, Dict
from flask import current_app
from sqlalchemy.exc import IntegrityError

from musicround.models import db, Song
from musicround.helpers.metadata import get_deezer_track_metadata
from musicround.helpers.spotify_archive import (
    bulk_lookup_spotify_archive_isrcs,
    bulk_lookup_spotify_archive_audio_features,
    SpotifyArchiveError
)


def get_coverage() -> Dict[str, int]:
    """Returns coverage counts for the catalog."""
    total = Song.query.count()
    with_deezer = Song.query.filter(Song.deezer_id.isnot(None)).count()
    with_isrc = Song.query.filter(Song.isrc.isnot(None)).count()
    with_spotify = Song.query.filter(Song.spotify_id.isnot(None)).count()
    with_features = Song.query.filter(Song.danceability.isnot(None)).count()

    return {
        "total_songs": total,
        "with_deezer_id": with_deezer,
        "with_isrc": with_isrc,
        "with_spotify_id": with_spotify,
        "with_audio_features": with_features
    }


def _chunked_query(query, chunk_size, limit=None):
    """Yield chunks of songs using keyset pagination by ID."""
    last_id = 0
    processed = 0
    while True:
        if limit and processed >= limit:
            break

        current_chunk_size = chunk_size
        if limit:
            current_chunk_size = min(chunk_size, limit - processed)

        chunk = (
            query.filter(Song.id > last_id)
            .order_by(Song.id)
            .limit(current_chunk_size)
            .all()
        )
        if not chunk:
            break
        yield chunk
        processed += len(chunk)
        last_id = chunk[-1].id


def run_backfill(dry_run: bool = False, limit: int = None, chunk_size: int = 50,
                 sleep_sec: float = 0.1) -> Dict[str, Any]:
    """Backfill catalog identifiers and audio features in staged batches.

    Args:
        dry_run: When true, roll back writes and report simulated coverage.
        limit: Optional maximum number of songs each stage should process.
        chunk_size: Maximum number of songs or Spotify IDs handled per batch.
        sleep_sec: Delay between rate-limited external metadata calls.

    Returns:
        A dictionary containing coverage_before, coverage_after, and per-stage
        processed/updated counters for stages A, B, and C.
    """
    app = current_app._get_current_object()

    coverage_before = get_coverage()

    result = {
        "coverage_before": coverage_before,
        "coverage_after": None,
        "stage_a": {"processed": 0, "updated": 0},
        "stage_b": {"processed": 0, "updated": 0},
        "stage_c": {"processed": 0, "updated": 0},
    }

    # --- Stage A: Deezer ISRC + missing metadata ---
    query_a = Song.query.filter(Song.deezer_id.isnot(None), Song.isrc.is_(None))
    album_cache = {}

    for chunk_idx, chunk in enumerate(_chunked_query(query_a, chunk_size, limit), 1):
        if not chunk:
            break

        updated_in_chunk = 0
        for song in chunk:
            if limit and result["stage_a"]["processed"] >= limit:
                break

            result["stage_a"]["processed"] += 1
            metadata = get_deezer_track_metadata(
                song.deezer_id,
                app=app,
                album_cache=album_cache)

            changed = False
            if metadata.get("isrc") and not song.isrc:
                song.isrc = metadata["isrc"]
                changed = True
            if metadata.get("popularity") is not None and song.popularity is None:
                song.popularity = metadata["popularity"]
                changed = True
            if metadata.get("year") and not song.year:
                try:
                    song.year = int(metadata["year"])
                    changed = True
                except (ValueError, TypeError):
                    pass
            if metadata.get("genre") and not song.genre:
                song.genre = metadata["genre"]
                changed = True

            if changed:
                updated_in_chunk += 1
                result["stage_a"]["updated"] += 1

            if sleep_sec > 0:
                time.sleep(sleep_sec)

        app.logger.info(
            f"Stage A chunk {chunk_idx} - {len(chunk)} songs, {updated_in_chunk} updated")
        if not dry_run:
            db.session.commit()
        else:
            db.session.rollback()

        if limit and result["stage_a"]["processed"] >= limit:
            break

    # --- Stage B: Offline Spotify true-up by EXACT ISRC ---
    query_b = Song.query.filter(Song.isrc.isnot(None), Song.spotify_id.is_(None))

    newly_mapped_spotify_ids = []

    for chunk_idx, chunk in enumerate(_chunked_query(query_b, chunk_size, limit), 1):
        if not chunk:
            break

        if limit and result["stage_b"]["processed"] >= limit:
            # We already fetched the chunk, but we need to respect the limit.
            chunk = chunk[:limit - result["stage_b"]["processed"]]
            if not chunk:
                break

        isrcs = [s.isrc for s in chunk if s.isrc]
        if not isrcs:
            continue

        result["stage_b"]["processed"] += len(chunk)
        updated_in_chunk = 0
        chunk_newly_mapped_ids = []

        try:
            archive_res = bulk_lookup_spotify_archive_isrcs(app, isrcs)
            isrc_to_spotify = {
                item["isrc"].upper(): item["spotify_id"] for item in archive_res.get(
                    "results", []) if item.get("spotify_id")}
            candidate_sids = set(isrc_to_spotify.values())
            assigned_spotify_ids = set()
            if candidate_sids:
                assigned_spotify_ids = {
                    sid for (sid,) in db.session.query(Song.spotify_id)
                    .filter(Song.spotify_id.in_(candidate_sids))
                    .all()
                }
            for song in chunk:
                if not song.isrc:
                    continue
                sid = isrc_to_spotify.get(song.isrc.upper())
                if sid:
                    if sid in assigned_spotify_ids:
                        app.logger.warning(
                            "Stage B skipped duplicate Spotify ID %s for song %s",
                            sid,
                            song.id)
                        continue
                    song.spotify_id = sid
                    assigned_spotify_ids.add(sid)
                    chunk_newly_mapped_ids.append(sid)
                    updated_in_chunk += 1

        except SpotifyArchiveError as exc:
            app.logger.warning(f"Stage B archive lookup failed: {exc}")

        app.logger.info(
            f"Stage B chunk {chunk_idx} - {len(chunk)} songs, {updated_in_chunk} updated")
        if not dry_run:
            try:
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                app.logger.warning(
                    f"Stage B commit skipped due to Spotify ID conflict: {exc}")
                updated_in_chunk = 0
                chunk_newly_mapped_ids = []
        else:
            db.session.rollback()
        result["stage_b"]["updated"] += updated_in_chunk
        newly_mapped_spotify_ids.extend(chunk_newly_mapped_ids)

        if limit and result["stage_b"]["processed"] >= limit:
            break

    # --- Stage C: Audio features for newly-mapped Spotify IDs ONLY ---
    if newly_mapped_spotify_ids:
        result["stage_c"]["processed"] = len(newly_mapped_spotify_ids)
        updated_c = 0

        for i in range(0, len(newly_mapped_spotify_ids), chunk_size):
            chunk_sids = newly_mapped_spotify_ids[i:i + chunk_size]
            try:
                archive_res = bulk_lookup_spotify_archive_audio_features(app, chunk_sids)
                sid_to_features = {
                    item["spotify_id"]: item
                    for item in archive_res.get("results", [])
                    if item.get("spotify_id")
                }

                if not dry_run:
                    songs_to_update = Song.query.filter(Song.spotify_id.in_(chunk_sids)).all()
                    for song in songs_to_update:
                        features = sid_to_features.get(song.spotify_id)
                        if features and features.get("danceability") is not None:
                            song.acousticness = features.get("acousticness")
                            song.danceability = features.get("danceability")
                            song.energy = features.get("energy")
                            song.instrumentalness = features.get("instrumentalness")
                            song.key = features.get("key")
                            song.liveness = features.get("liveness")
                            song.loudness = features.get("loudness")
                            song.mode = features.get("mode")
                            song.speechiness = features.get("speechiness")
                            song.tempo = features.get("tempo")
                            song.time_signature = features.get("time_signature")
                            song.valence = features.get("valence")
                            song.duration_ms = features.get("duration_ms")
                            updated_c += 1
                    db.session.commit()
                else:
                    # In dry run, count how many features we found
                    for sid in chunk_sids:
                        feat = sid_to_features.get(sid)
                        if feat and feat.get("danceability") is not None:
                            updated_c += 1

            except SpotifyArchiveError as exc:
                app.logger.warning(
                    f"Stage C archive lookup failed for chunk, falling back: {exc}")
                sp = app.config.get('sp')
                if sp:
                    from musicround.helpers.import_helper import ImportHelper
                    if not dry_run:
                        for sid in chunk_sids:
                            song = Song.query.filter_by(spotify_id=sid).first()
                            if song:
                                ImportHelper._fetch_audio_features_for_song(sp, song, sid)
                                if song.danceability is not None:
                                    updated_c += 1
                                if sleep_sec > 0:
                                    time.sleep(sleep_sec)
                        db.session.commit()
                    else:
                        updated_c += len(chunk_sids)
                else:
                    app.logger.error("Stage C fallback failed: Spotify client not available.")

        result["stage_c"]["updated"] = updated_c
        app.logger.info(
            f"Stage C - {result['stage_c']['processed']} processed, {updated_c} updated")

    if dry_run:
        simulated_coverage = dict(coverage_before)
        simulated_coverage["with_isrc"] += result["stage_a"]["updated"]
        simulated_coverage["with_spotify_id"] += result["stage_b"]["updated"]
        simulated_coverage["with_audio_features"] += result["stage_c"]["updated"]
        result["coverage_after"] = simulated_coverage
    else:
        result["coverage_after"] = get_coverage()

    return result
