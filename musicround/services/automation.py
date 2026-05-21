"""Automation services used by the MCP server and agent workflows."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

from flask import current_app
from flask_login import login_user, logout_user
from pydub import AudioSegment
from sqlalchemy import or_

from musicround import db
from musicround.helpers.email_helper import send_email
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.utils import generate_tts_mp3
from musicround.models import Round, RoundExport, Song, Tag, User


class AutomationError(ValueError):
    """Raised when an automation request cannot be completed."""


def _song_summary(song: Song) -> dict[str, Any]:
    data = song.to_dict()
    return {
        "id": data["id"],
        "title": data["title"],
        "artist": data["artist"],
        "genre": data["genre"],
        "year": data["year"],
        "source": song.source,
        "preview_url": data["preview_url"],
        "spotify_id": data["spotify_id"],
        "deezer_id": data["deezer_id"],
        "isrc": data["isrc"],
        "tags": data["tags"],
    }


def _round_summary(round_obj: Round) -> dict[str, Any]:
    ids = [int(song_id) for song_id in round_obj.songs.split(",") if song_id]
    songs = Song.query.filter(Song.id.in_(ids)).all()
    songs_by_id = {song.id: song for song in songs}
    ordered = [songs_by_id[song_id] for song_id in ids if song_id in songs_by_id]
    return {
        "id": round_obj.id,
        "name": round_obj.name,
        "round_type": round_obj.round_type,
        "criteria": round_obj.round_criteria_used,
        "song_ids": ids,
        "songs": [_song_summary(song) for song in ordered],
        "mp3_generated": round_obj.mp3_generated,
        "pdf_generated": round_obj.pdf_generated,
        "last_generated_at": (
            round_obj.last_generated_at.isoformat() if round_obj.last_generated_at else None
        ),
    }


def _find_user(user_id: int | None = None) -> User:
    if user_id is not None:
        user = db.session.get(User, user_id)
        if not user:
            raise AutomationError(f"User {user_id} was not found.")
        return user

    users = User.query.order_by(User.id).limit(2).all()
    if len(users) == 1:
        return users[0]
    if not users:
        raise AutomationError(
            "No users exist yet. Create a user before generating user-owned assets."
        )
    raise AutomationError(
        "Multiple users exist. Pass user_id so the action uses the right account."
    )


def _parse_external_id(service_name: str, item_type: str, value: str) -> str:
    service = service_name.lower()
    item = item_type.lower()
    stripped = value.strip()
    if service == "spotify":
        match = re.search(rf"spotify\.com/{item}/([A-Za-z0-9]+)", stripped)
        if match:
            return match.group(1)
        match = re.search(rf"spotify:{item}:([A-Za-z0-9]+)", stripped)
        if match:
            return match.group(1)
    if service == "deezer":
        match = re.search(r"deezer\.page\.link/([A-Za-z0-9]+)", stripped)
        if match:
            return match.group(1)
        match = re.search(rf"deezer\.com/(?:[a-z]{{2}}/)?{item}/(\d+)", stripped)
        if match:
            return match.group(1)
    return stripped.split("?")[0].rstrip("/")


def _attach_tags(song: Song, tag_names: Iterable[str] | None) -> None:
    for raw_name in tag_names or []:
        tag_name = raw_name.strip()
        if not tag_name:
            continue
        tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.session.add(tag)
            db.session.flush()
        if tag not in song.tags:
            song.tags.append(tag)


def add_song(
    title: str,
    artist: str,
    album_name: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    preview_url: str | None = None,
    cover_url: str | None = None,
    spotify_id: str | None = None,
    deezer_id: str | None = None,
    isrc: str | None = None,
    tags: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Add or update a song in the local catalog."""
    if not title or not artist:
        raise AutomationError("Both title and artist are required.")

    existing = None
    if isrc:
        existing = Song.query.filter_by(isrc=isrc).first()
    if not existing and spotify_id:
        existing = Song.query.filter_by(spotify_id=spotify_id).first()
    if not existing and deezer_id:
        existing = Song.query.filter_by(deezer_id=str(deezer_id)).first()

    song = existing or Song(title=title.strip(), artist=artist.strip())
    song.title = title.strip()
    song.artist = artist.strip()
    song.album_name = album_name or song.album_name
    song.genre = genre or song.genre
    song.year = year or song.year
    song.preview_url = preview_url or song.preview_url
    song.cover_url = cover_url or song.cover_url
    song.spotify_id = spotify_id or song.spotify_id
    song.deezer_id = str(deezer_id) if deezer_id else song.deezer_id
    song.isrc = isrc or song.isrc
    song.source = source or song.source or "manual"
    _attach_tags(song, tags)

    if not existing:
        db.session.add(song)
    db.session.commit()
    return {"created": existing is None, "song": _song_summary(song)}


def find_songs(
    query: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    spotify_id: str | None = None,
    deezer_id: str | None = None,
    isrc: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search the local catalog before adding or importing tracks."""
    if limit < 1 or limit > 100:
        raise AutomationError("limit must be between 1 and 100.")

    filters = []
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(or_(Song.title.ilike(pattern), Song.artist.ilike(pattern)))
    if title:
        filters.append(Song.title.ilike(f"%{title.strip()}%"))
    if artist:
        filters.append(Song.artist.ilike(f"%{artist.strip()}%"))
    if spotify_id:
        filters.append(Song.spotify_id == spotify_id)
    if deezer_id:
        filters.append(Song.deezer_id == str(deezer_id))
    if isrc:
        filters.append(Song.isrc == isrc)

    song_query = Song.query
    for condition in filters:
        song_query = song_query.filter(condition)
    songs = song_query.order_by(Song.artist, Song.title).limit(limit).all()
    return {"count": len(songs), "songs": [_song_summary(song) for song in songs]}


def import_catalog_item(
    service_name: str,
    item_type: str,
    item_id_or_url: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Import a track, album, or playlist from Spotify or Deezer."""
    service = service_name.lower()
    item = item_type.lower()
    external_id = _parse_external_id(service, item, item_id_or_url)
    if service == "spotify":
        user = _find_user(user_id)
        with current_app.test_request_context():
            login_user(user)
            try:
                result = ImportHelper.import_item(service, item, external_id)
            finally:
                logout_user()
    else:
        result = ImportHelper.import_item(service, item, external_id)

    if result.get("error_count", 0) > 0:
        current_app.logger.warning("Import completed with errors: %s", result.get("errors", []))
    return {"service_name": service, "item_type": item, "item_id": external_id, "result": result}


def _songs_for_round(
    round_type: str,
    count: int,
    criteria: str | None = None,
    song_ids: list[int] | None = None,
) -> tuple[str, str, list[Song]]:
    from musicround.routes.generate import (
        get_random_songs,
        get_random_songs_from_decade,
        get_random_songs_from_genre,
        get_random_songs_from_least_used_decade,
        get_random_songs_from_least_used_genre,
        get_songs_by_tag,
    )

    normalized = round_type.lower().strip()
    if song_ids:
        songs_by_id = {song.id: song for song in Song.query.filter(Song.id.in_(song_ids)).all()}
        songs = [songs_by_id[song_id] for song_id in song_ids if song_id in songs_by_id]
        if len(songs) != len(song_ids):
            missing = sorted(set(song_ids) - set(songs_by_id))
            raise AutomationError(f"Unknown song IDs: {missing}")
        return "Manual", "Explicit song selection", songs[:count]

    if normalized == "random":
        return "Random", "Random Selection", get_random_songs(count)
    if normalized == "genre":
        if criteria:
            return "Genre", criteria, get_random_songs_from_genre(criteria, x=count)
        songs, chosen = get_random_songs_from_least_used_genre(count)
        return "Genre", chosen or "Least Used Genre", songs
    if normalized == "decade":
        if criteria:
            return "Decade", criteria, get_random_songs_from_decade(criteria, x=count)
        songs, chosen = get_random_songs_from_least_used_decade(count)
        return "Decade", chosen or "Least Used Decade", songs
    if normalized == "tag":
        if not criteria:
            raise AutomationError("Tag rounds require criteria with the tag name.")
        return "Tag", criteria, get_songs_by_tag(criteria, count)
    raise AutomationError("round_type must be one of random, genre, decade, tag, or manual.")


def create_round(
    name: str | None = None,
    round_type: str = "random",
    count: int = 8,
    criteria: str | None = None,
    song_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Create and persist a quiz round."""
    if count < 1:
        raise AutomationError("count must be at least 1.")

    resolved_type, resolved_criteria, songs = _songs_for_round(
        round_type, count, criteria, song_ids
    )
    if not songs:
        raise AutomationError("No songs matched the requested round criteria.")

    round_obj = Round(
        name=name,
        round_type=resolved_type,
        round_criteria_used=resolved_criteria,
        songs=",".join(str(song.id) for song in songs),
        created_at=datetime.utcnow(),
    )
    db.session.add(round_obj)
    for song in songs:
        song.used_count = (song.used_count or 0) + 1
        song.last_used = datetime.utcnow()
    db.session.commit()
    return {"round": _round_summary(round_obj)}


def rename_round(round_id: int, name: str | None) -> dict[str, Any]:
    """Rename a persisted round."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    round_obj.name = name.strip() if name and name.strip() else None
    db.session.commit()
    return {"round": _round_summary(round_obj)}


def _spotify_playlist_song_ids(playlist_id: str, limit: int, user_id: int | None) -> list[int]:
    from musicround.routes.generate import get_songs_from_spotify_playlist

    user = _find_user(user_id)
    with current_app.test_request_context():
        login_user(user)
        try:
            songs = get_songs_from_spotify_playlist(playlist_id)
        finally:
            logout_user()
    return [song.id for song in songs[:limit]]


def _deezer_playlist_song_ids(playlist_id: str, limit: int) -> list[int]:
    deezer_client = current_app.config.get("deezer")
    if not deezer_client:
        raise AutomationError("Deezer client is not configured.")

    tracks = deezer_client.get_playlist_tracks(playlist_id)
    song_ids = []
    lastfm_key = current_app.config.get("LASTFM_API_KEY")
    for track in tracks[:limit]:
        track_id = track.get("id")
        if not track_id:
            continue
        song, _ = deezer_client.import_track(track_id, lastfm_api_key=lastfm_key)
        if song:
            song_ids.append(song.id)
    db.session.commit()
    return song_ids


def create_round_from_playlist(
    service_name: str,
    playlist_id_or_url: str,
    name: str | None = None,
    count: int = 8,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Import a playlist and create a manual round from the imported songs."""
    imported = import_catalog_item(service_name, "playlist", playlist_id_or_url, user_id=user_id)
    playlist_id = imported["item_id"]
    if service_name.lower() == "spotify":
        song_ids = _spotify_playlist_song_ids(playlist_id, count, user_id)
    else:
        song_ids = imported.get("result", {}).get(
            "imported_song_ids"
        ) or _deezer_playlist_song_ids(playlist_id, count)
    if not song_ids:
        raise AutomationError("Playlist import did not return song IDs to build a round.")
    round_result = create_round(
        name=name, round_type="manual", count=count, song_ids=song_ids[:count]
    )
    return {"import": imported, "round": round_result["round"]}


def generate_round_pdf(round_id: int) -> dict[str, Any]:
    from musicround.routes.rounds import generate_pdf

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    pdf_data = generate_pdf(round_id)
    if isinstance(pdf_data, str):
        raise AutomationError(pdf_data)
    round_obj.pdf_generated = True
    round_obj.last_generated_at = datetime.utcnow()
    db.session.commit()
    path = os.path.join("/data/pdfs", f"round_{round_id}.pdf")
    return {"round_id": round_id, "path": path, "bytes": len(pdf_data)}


def generate_round_mp3(round_id: int, user_id: int | None = None) -> dict[str, Any]:
    from musicround.routes.rounds import round_mp3

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    user = _find_user(user_id)
    with current_app.test_request_context(headers={"X-Requested-With": "XMLHttpRequest"}):
        login_user(user)
        try:
            response = round_mp3(round_id)
        finally:
            logout_user()

    if hasattr(response, "get_json"):
        payload = response.get_json(silent=True) or {}
        if payload.get("success") is False or payload.get("error"):
            raise AutomationError(payload.get("error", "MP3 generation failed."))

    path = os.path.join("/data/rounds", f"round_{round_id}.mp3")
    if not os.path.exists(path):
        raise AutomationError(f"MP3 generation did not create {path}.")
    return {"round_id": round_id, "path": path, "bytes": os.path.getsize(path)}


def generate_round_assets(
    round_id: int,
    user_id: int | None = None,
    include_pdf: bool = True,
    include_mp3: bool = True,
) -> dict[str, Any]:
    """Generate requested round assets."""
    assets: dict[str, Any] = {"round_id": round_id}
    if include_pdf:
        assets["pdf"] = generate_round_pdf(round_id)
    if include_mp3:
        assets["mp3"] = generate_round_mp3(round_id, user_id=user_id)
    return assets


def email_round(
    round_id: int,
    recipient: str | None = None,
    user_id: int | None = None,
    subject: str | None = None,
    body_text: str | None = None,
) -> dict[str, Any]:
    """Generate assets and send a round as an email attachment bundle."""
    user = _find_user(user_id)
    target = recipient or user.email
    if not target:
        raise AutomationError("No recipient was provided and the selected user has no email.")

    assets = generate_round_assets(round_id, user_id=user.id)
    round_obj = db.session.get(Round, round_id)
    title = round_obj.name if round_obj and round_obj.name else f"Quizzical Beats Round {round_id}"
    email_subject = subject or title
    email_body = body_text or "Attached are the MP3 and PDF files for your quiz round."

    attachments = []
    with open(assets["pdf"]["path"], "rb") as pdf_file:
        attachments.append(
            {
                "data": pdf_file.read(),
                "filename": f"round_{round_id}.pdf",
                "mimetype": "application/pdf",
            }
        )
    with open(assets["mp3"]["path"], "rb") as mp3_file:
        attachments.append(
            {
                "data": mp3_file.read(),
                "filename": f"round_{round_id}.mp3",
                "mimetype": "audio/mpeg",
            }
        )

    success, message = send_email(target, email_subject, email_body, attachments)
    export = RoundExport(
        round_id=round_id,
        user_id=user.id,
        export_type="email",
        destination=target,
        include_mp3s=True,
        status="success" if success else "failed",
        error_message=None if success else message,
    )
    db.session.add(export)
    db.session.commit()
    if not success:
        raise AutomationError(message)
    return {"success": True, "message": message, "recipient": target, "assets": assets}


def inspect_mp3_quality(path: str | None = None, round_id: int | None = None) -> dict[str, Any]:
    """Inspect basic MP3 quality and flag common generation issues."""
    if not path:
        if round_id is None:
            raise AutomationError("Pass either path or round_id.")
        path = os.path.join("/data/rounds", f"round_{round_id}.mp3")
    if not os.path.exists(path):
        raise AutomationError(f"MP3 file not found: {path}")

    audio = AudioSegment.from_mp3(path)
    warnings = []
    if len(audio) < 1000:
        warnings.append("Audio is shorter than one second.")
    if audio.dBFS == float("-inf"):
        warnings.append("Audio appears to be silent.")
    elif audio.dBFS < -35:
        warnings.append("Average loudness is very low.")
    elif audio.dBFS > -8:
        warnings.append("Average loudness is high; check for limiting or clipping.")

    samples = audio.get_array_of_samples()
    max_possible = float(1 << (8 * audio.sample_width - 1))
    clipped = sum(1 for sample in samples if abs(sample) >= max_possible * 0.99)
    clipping_ratio = clipped / len(samples) if samples else 0
    if clipping_ratio > 0.001:
        warnings.append("Potential clipping detected.")

    return {
        "path": path,
        "duration_seconds": round(len(audio) / 1000, 3),
        "channels": audio.channels,
        "frame_rate": audio.frame_rate,
        "sample_width_bytes": audio.sample_width,
        "average_dbfs": None if audio.dBFS == float("-inf") else round(audio.dBFS, 2),
        "peak_dbfs": round(audio.max_dBFS, 2),
        "clipping_ratio": round(clipping_ratio, 6),
        "warnings": warnings,
        "ok": not warnings,
    }


def inspect_pdf_quality(path: str | None = None, round_id: int | None = None) -> dict[str, Any]:
    """Inspect basic PDF integrity for generated round sheets."""
    if not path:
        if round_id is None:
            raise AutomationError("Pass either path or round_id.")
        path = os.path.join("/data/pdfs", f"round_{round_id}.pdf")
    if not os.path.exists(path):
        raise AutomationError(f"PDF file not found: {path}")

    with open(path, "rb") as pdf_file:
        data = pdf_file.read()
    warnings = []
    if not data.startswith(b"%PDF-"):
        warnings.append("File does not start with a PDF header.")
    if b"%%EOF" not in data[-2048:]:
        warnings.append("PDF EOF marker was not found near the end of the file.")
    if len(data) < 1024:
        warnings.append("PDF file is unusually small.")
    page_count = data.count(b"/Type /Page")
    if page_count == 0:
        warnings.append("No PDF pages were detected.")

    return {
        "path": path,
        "bytes": len(data),
        "page_count_estimate": page_count,
        "warnings": warnings,
        "ok": not warnings,
    }


def generate_tts_snippet(
    user_id: int,
    mp3_type: str,
    text: str,
    service: str = "openai",
    voice: str | None = None,
    model: str | None = None,
    stability: float | None = None,
    similarity: float | None = None,
) -> dict[str, Any]:
    """Generate and assign a custom intro, replay, or outro MP3 for a user."""
    if mp3_type not in {"intro", "replay", "outro"}:
        raise AutomationError("mp3_type must be intro, replay, or outro.")
    if not text:
        raise AutomationError("text is required for TTS generation.")

    user = _find_user(user_id)
    path = generate_tts_mp3(
        text=text,
        username=user.username,
        mp3_type=mp3_type,
        service=service,
        voice=voice,
        model=model,
        stability=stability,
        similarity=similarity,
    )
    if not path:
        raise AutomationError("TTS generation failed.")

    setattr(user, f"{mp3_type}_mp3", path)
    db.session.commit()
    return {"user_id": user.id, "mp3_type": mp3_type, "path": path}
