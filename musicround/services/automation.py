"""Automation services used by the MCP server and agent workflows."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from typing import Any, Iterable

import requests
from flask import current_app
from flask_login import login_user, logout_user
from pydub import AudioSegment
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_

from musicround import db
from musicround.helpers.email_helper import send_email
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.utils import generate_tts_mp3, get_mp3_path
from musicround import models as datastore_models
from musicround.models import Round, RoundExport, Song, Tag, User


class AutomationError(ValueError):
    """Raised when an automation request cannot be completed."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _round_song_ids(round_obj: Round) -> list[int]:
    return [int(song_id) for song_id in round_obj.songs.split(",") if song_id]


def _ordered_round_songs(round_obj: Round) -> list[Song]:
    ids = _round_song_ids(round_obj)
    songs = Song.query.filter(Song.id.in_(ids)).all()
    songs_by_id = {song.id: song for song in songs}
    return [songs_by_id[song_id] for song_id in ids if song_id in songs_by_id]


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
        "used_count": data["used_count"] or 0,
        "usage_frequency": data["used_count"] or 0,
        "last_used": data["last_used"],
        "tags": data["tags"],
    }


def _round_summary(round_obj: Round) -> dict[str, Any]:
    ids = _round_song_ids(round_obj)
    ordered = _ordered_round_songs(round_obj)
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


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _model_registry() -> dict[str, type[db.Model]]:
    registry: dict[str, type[db.Model]] = {}
    for value in vars(datastore_models).values():
        if not isinstance(value, type):
            continue
        if value is db.Model or not issubclass(value, db.Model):
            continue
        mapper = sa_inspect(value, raiseerr=False)
        if mapper is None or getattr(value, "__table__", None) is None:
            continue
        canonical = _snake_case(value.__name__)
        registry[canonical] = value
        registry[value.__name__] = value
        registry[value.__name__.lower()] = value
        registry[value.__tablename__] = value
    return registry


def _canonical_model_key(model: type[db.Model]) -> str:
    return _snake_case(model.__name__)


def _get_model(object_type: str) -> type[db.Model]:
    if not object_type:
        raise AutomationError("object_type is required.")
    model = _model_registry().get(object_type)
    if not model:
        allowed = sorted({_canonical_model_key(model) for model in _model_registry().values()})
        raise AutomationError(f"Unknown object_type '{object_type}'. Allowed values: {allowed}")
    return model


def _column_map(model: type[db.Model]) -> dict[str, Any]:
    return {column.key: column for column in sa_inspect(model).columns}


def _primary_key_columns(model: type[db.Model]) -> list[Any]:
    return list(sa_inspect(model).primary_key)


def _is_sensitive_field(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(marker in lowered for marker in ("password", "token", "secret"))


def _json_value(value: Any, *, sensitive: bool = False, include_sensitive: bool = False) -> Any:
    if sensitive and value is not None and not include_sensitive:
        return "[redacted]"
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_model(instance: db.Model, *, include_sensitive: bool = False) -> dict[str, Any]:
    data = {}
    for column in sa_inspect(instance.__class__).columns:
        value = getattr(instance, column.key)
        data[column.key] = _json_value(
            value,
            sensitive=_is_sensitive_field(column.key),
            include_sensitive=include_sensitive,
        )
    return data


def _coerce_column_value(column: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value

    if python_type is datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        raise AutomationError(f"{column.key} must be an ISO datetime string.")
    if python_type is bool and isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if python_type in {int, float, str, bool} and not isinstance(value, python_type):
        return python_type(value)
    return value


def _identity_for_object(model: type[db.Model], object_id: Any) -> Any:
    primary_key = _primary_key_columns(model)
    if not primary_key:
        raise AutomationError(f"{_canonical_model_key(model)} does not have a primary key.")

    if isinstance(object_id, dict):
        missing = [column.key for column in primary_key if column.key not in object_id]
        if missing:
            raise AutomationError(f"Missing primary key field(s): {missing}")
        values = [_coerce_column_value(column, object_id[column.key]) for column in primary_key]
    elif len(primary_key) == 1:
        values = [_coerce_column_value(primary_key[0], object_id)]
    elif isinstance(object_id, list):
        if len(object_id) != len(primary_key):
            raise AutomationError(
                f"Composite primary key requires {len(primary_key)} values in order."
            )
        values = [
            _coerce_column_value(column, object_id[index])
            for index, column in enumerate(primary_key)
        ]
    else:
        names = [column.key for column in primary_key]
        raise AutomationError(f"Composite primary key requires an object with keys {names}.")

    return values[0] if len(values) == 1 else tuple(values)


def _get_datastore_instance(model: type[db.Model], object_id: Any) -> db.Model:
    instance = db.session.get(model, _identity_for_object(model, object_id))
    if not instance:
        raise AutomationError(f"{_canonical_model_key(model)} {object_id} was not found.")
    return instance


def _apply_datastore_filters(query: Any, model: type[db.Model], filters: dict[str, Any] | None) -> Any:
    columns = _column_map(model)
    for field_name, raw_value in (filters or {}).items():
        column = columns.get(field_name)
        if column is None:
            raise AutomationError(f"Unknown filter field '{field_name}'.")
        query = query.filter(getattr(model, field_name) == _coerce_column_value(column, raw_value))
    return query


def _assign_datastore_fields(instance: db.Model, fields: dict[str, Any], *, creating: bool) -> None:
    if not fields:
        raise AutomationError("fields must not be empty.")

    model = instance.__class__
    columns = _column_map(model)
    primary_keys = {column.key for column in _primary_key_columns(model)}
    for field_name, raw_value in fields.items():
        column = columns.get(field_name)
        if column is None:
            raise AutomationError(f"Unknown field '{field_name}'.")
        if not creating and field_name in primary_keys:
            raise AutomationError("Primary key fields cannot be updated.")
        setattr(instance, field_name, _coerce_column_value(column, raw_value))


def datastore_schema() -> dict[str, Any]:
    """Describe datastore objects available through generic MCP CRUD tools."""
    models_by_key = {
        _canonical_model_key(model): model for model in _model_registry().values()
    }
    objects = []
    for object_type, model in sorted(models_by_key.items()):
        mapper = sa_inspect(model)
        objects.append(
            {
                "object_type": object_type,
                "table": model.__tablename__,
                "primary_key": [column.key for column in mapper.primary_key],
                "columns": [
                    {
                        "name": column.key,
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "sensitive": _is_sensitive_field(column.key),
                    }
                    for column in mapper.columns
                ],
            }
        )
    return {"object_types": [item["object_type"] for item in objects], "objects": objects}


def list_datastore_objects(
    object_type: str,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str | None = None,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """List persisted rows for a mapped datastore object."""
    if limit < 1 or limit > 500:
        raise AutomationError("limit must be between 1 and 500.")
    if offset < 0:
        raise AutomationError("offset must not be negative.")

    model = _get_model(object_type)
    query = _apply_datastore_filters(model.query, model, filters)
    total = query.count()

    if order_by:
        descending = order_by.startswith("-")
        field_name = order_by[1:] if descending else order_by
        if field_name not in _column_map(model):
            raise AutomationError(f"Unknown order_by field '{field_name}'.")
        column = getattr(model, field_name)
        query = query.order_by(column.desc() if descending else column.asc())
    else:
        primary_key = _primary_key_columns(model)
        if primary_key:
            query = query.order_by(*[getattr(model, column.key).asc() for column in primary_key])

    rows = query.offset(offset).limit(limit).all()
    return {
        "object_type": _canonical_model_key(model),
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "objects": [_serialize_model(row, include_sensitive=include_sensitive) for row in rows],
    }


def get_datastore_object(
    object_type: str,
    object_id: Any,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Fetch a single persisted datastore object by primary key."""
    model = _get_model(object_type)
    instance = _get_datastore_instance(model, object_id)
    return {
        "object_type": _canonical_model_key(model),
        "object": _serialize_model(instance, include_sensitive=include_sensitive),
    }


def create_datastore_object(
    object_type: str,
    fields: dict[str, Any],
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Create a persisted datastore object from scalar column fields."""
    model = _get_model(object_type)
    instance = model()
    _assign_datastore_fields(instance, fields, creating=True)
    db.session.add(instance)
    db.session.commit()
    return {
        "created": True,
        "object_type": _canonical_model_key(model),
        "object": _serialize_model(instance, include_sensitive=include_sensitive),
    }


def update_datastore_object(
    object_type: str,
    object_id: Any,
    fields: dict[str, Any],
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Update scalar column fields for a persisted datastore object."""
    model = _get_model(object_type)
    instance = _get_datastore_instance(model, object_id)
    _assign_datastore_fields(instance, fields, creating=False)
    db.session.commit()
    return {
        "updated": True,
        "object_type": _canonical_model_key(model),
        "object": _serialize_model(instance, include_sensitive=include_sensitive),
    }


def delete_datastore_object(object_type: str, object_id: Any) -> dict[str, Any]:
    """Delete a persisted datastore object by primary key."""
    model = _get_model(object_type)
    instance = _get_datastore_instance(model, object_id)
    serialized = _serialize_model(instance)
    db.session.delete(instance)
    db.session.commit()
    return {
        "deleted": True,
        "object_type": _canonical_model_key(model),
        "object": serialized,
    }


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
    if len(song_ids) < count:
        message = (
            f"Playlist import resolved {len(song_ids)} songs; "
            f"expected exactly {count} for a complete quiz round."
        )
        raise AutomationError(
            message,
            details={
                "success": False,
                "status": "needs_more_songs",
                "service": service_name.lower(),
                "playlist_id": playlist_id,
                "expected_song_count": count,
                "resolved_song_count": len(song_ids),
                "missing_count": count - len(song_ids),
                "import": imported,
                "hints": [message],
                "remediation": [
                    {
                        "action": "add_or_replace_playlist_tracks",
                        "message": message,
                        "expected_song_count": count,
                        "resolved_song_count": len(song_ids),
                    }
                ],
            },
        )
    round_result = create_round(
        name=name,
        round_type="manual",
        count=count,
        song_ids=song_ids[:count],
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


def _quality_issue(
    code: str,
    message: str,
    song: Song | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if song:
        issue["song"] = {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "deezer_id": song.deezer_id,
            "spotify_id": song.spotify_id,
        }
    if details:
        issue["details"] = details
    return issue


def _download_preview_audio(
    song: Song, temp_dir: str
) -> tuple[str | None, AudioSegment | None, dict[str, Any] | None]:
    if not song.deezer_id:
        return None, None, _quality_issue(
            "missing_deezer_id",
            f"{song.artist} - {song.title} has no Deezer ID, so the MP3 generator will skip it.",
            song,
        )

    deezer_client = current_app.config.get("deezer")
    if not deezer_client:
        return None, None, _quality_issue(
            "deezer_client_missing",
            "The Deezer client is not configured, so preview availability cannot be verified.",
            song,
        )

    try:
        track = deezer_client.get_track(song.deezer_id)
    except Exception as exc:
        return None, None, _quality_issue(
            "deezer_lookup_failed",
            f"Could not fetch Deezer metadata for {song.artist} - {song.title}: {exc}",
            song,
        )

    preview_url = track.get("preview") if isinstance(track, dict) else None
    if not preview_url:
        return None, None, _quality_issue(
            "missing_preview_url",
            f"{song.artist} - {song.title} has no Deezer preview URL.",
            song,
        )

    try:
        response = requests.get(preview_url, stream=True, timeout=30)
        response.raise_for_status()
        preview_path = os.path.join(temp_dir, f"preview_{song.id}.mp3")
        with open(preview_path, "wb") as preview_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    preview_file.write(chunk)
        return preview_url, AudioSegment.from_file(preview_path), None
    except Exception as exc:
        return preview_url, None, _quality_issue(
            "preview_download_failed",
            f"Could not download or decode preview for {song.artist} - {song.title}: {exc}",
            song,
            {"preview_url": preview_url},
        )


def _round_audio_components(
    user: User, song_count: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    components: dict[str, Any] = {"custom_audio_ms": {}, "number_audio_ms": []}

    for mp3_type in ("intro", "replay", "outro"):
        try:
            segment = AudioSegment.from_mp3(get_mp3_path(user, mp3_type))
            components["custom_audio_ms"][mp3_type] = len(segment)
        except Exception as exc:
            issues.append(
                _quality_issue(
                    "custom_audio_failed",
                    f"Could not load {mp3_type} audio for duration validation: {exc}",
                )
            )

    for index in range(song_count):
        path = os.path.join(current_app.root_path, "static", "audio", f"{index + 1}.mp3")
        try:
            components["number_audio_ms"].append(len(AudioSegment.from_mp3(path)))
        except Exception as exc:
            issues.append(
                _quality_issue(
                    "number_audio_failed",
                    f"Could not load number announcement {index + 1}: {exc}",
                )
            )

    return components, issues


def inspect_round_package(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = 6.0,
) -> dict[str, Any]:
    """Validate a generated round bundle before it is allowed to leave by email."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    user = _find_user(user_id)
    song_ids = _round_song_ids(round_obj)
    songs = _ordered_round_songs(round_obj)
    issues: list[dict[str, Any]] = []
    preview_checks: list[dict[str, Any]] = []
    remediation: list[dict[str, Any]] = []
    total_preview_ms = 0

    actual_song_count = len(song_ids)
    if actual_song_count != expected_song_count:
        code = "actual_song_count_mismatch"
        message = (
            f"Round {round_id} has {actual_song_count} stored songs; "
            f"expected exactly {expected_song_count}."
        )
        issues.append(
            _quality_issue(
                code,
                message,
                details={
                    "expected_song_count": expected_song_count,
                    "actual_song_count": actual_song_count,
                },
            )
        )
        remediation.append(
            {
                "action": "add_missing_track"
                if actual_song_count < expected_song_count
                else "remove_extra_track",
                "message": message,
                "expected_song_count": expected_song_count,
                "actual_song_count": actual_song_count,
            }
        )

    resolved_song_count = len(songs)
    if resolved_song_count != actual_song_count:
        resolved_song_ids = {song.id for song in songs}
        unresolved_positions = [
            index + 1
            for index, song_id in enumerate(song_ids)
            if song_id not in resolved_song_ids
        ]
        message = (
            f"Round {round_id} resolves to {resolved_song_count} playable songs "
            f"from {actual_song_count} stored IDs."
        )
        issues.append(
            _quality_issue(
                "resolved_song_count_mismatch",
                message,
                details={
                    "expected_song_count": expected_song_count,
                    "actual_song_count": actual_song_count,
                    "resolved_song_count": resolved_song_count,
                    "unresolved_positions": unresolved_positions,
                },
            )
        )
        remediation.append(
            {
                "action": "replace_unresolved_positions",
                "message": message,
                "positions": unresolved_positions,
                "expected_song_count": expected_song_count,
                "resolved_song_count": resolved_song_count,
            }
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        for index, song in enumerate(songs, start=1):
            preview_url, audio, issue = _download_preview_audio(song, temp_dir)
            check = {
                "position": index,
                "song_id": song.id,
                "title": song.title,
                "artist": song.artist,
                "preview_url": preview_url,
                "duration_seconds": None,
                "issue_code": None,
                "remediation": None,
                "ok": False,
            }
            if issue:
                issues.append(issue)
                check["issue_code"] = issue["code"]
                check["remediation"] = "replace_position"
                remediation.append(
                    {
                        "action": "replace_position",
                        "position": index,
                        "song_id": song.id,
                        "artist": song.artist,
                        "title": song.title,
                        "issue_code": issue["code"],
                        "message": issue["message"],
                    }
                )
            elif audio:
                duration_seconds = len(audio) / 1000
                total_preview_ms += len(audio)
                check["duration_seconds"] = round(duration_seconds, 3)
                check["ok"] = True
                if duration_seconds < min_preview_seconds:
                    check["ok"] = False
                    issue = _quality_issue(
                        "preview_too_short",
                        (
                            f"{song.artist} - {song.title} preview is "
                            f"{duration_seconds:.1f}s; expected at least "
                            f"{min_preview_seconds:.1f}s."
                        ),
                        song,
                        {"duration_seconds": round(duration_seconds, 3)},
                    )
                    issues.append(issue)
                    check["issue_code"] = issue["code"]
                    check["remediation"] = "replace_position"
                    remediation.append(
                        {
                            "action": "replace_position",
                            "position": index,
                            "song_id": song.id,
                            "artist": song.artist,
                            "title": song.title,
                            "issue_code": issue["code"],
                            "message": issue["message"],
                        }
                    )
                elif duration_seconds > max_preview_seconds:
                    check["ok"] = False
                    issue = _quality_issue(
                        "preview_too_long",
                        (
                            f"{song.artist} - {song.title} preview is "
                            f"{duration_seconds:.1f}s; expected at most "
                            f"{max_preview_seconds:.1f}s."
                        ),
                        song,
                        {"duration_seconds": round(duration_seconds, 3)},
                    )
                    issues.append(issue)
                    check["issue_code"] = issue["code"]
                    check["remediation"] = "replace_position"
                    remediation.append(
                        {
                            "action": "replace_position",
                            "position": index,
                            "song_id": song.id,
                            "artist": song.artist,
                            "title": song.title,
                            "issue_code": issue["code"],
                            "message": issue["message"],
                        }
                    )
            preview_checks.append(check)

    components, component_issues = _round_audio_components(user, len(songs))
    issues.extend(component_issues)
    expected_ms = None
    if not component_issues:
        custom_audio_ms = components["custom_audio_ms"]
        expected_ms = (
            custom_audio_ms.get("intro", 0)
            + custom_audio_ms.get("replay", 0)
            + custom_audio_ms.get("outro", 0)
            + 2 * sum(components["number_audio_ms"])
            + 2 * total_preview_ms
        )

    pdf_result: dict[str, Any] | None = None
    mp3_result: dict[str, Any] | None = None
    try:
        pdf_result = inspect_pdf_quality(round_id=round_id)
        for warning in pdf_result.get("warnings", []):
            issues.append(_quality_issue("pdf_quality_warning", warning))
    except Exception as exc:
        issues.append(_quality_issue("pdf_inspection_failed", str(exc)))

    try:
        mp3_result = inspect_mp3_quality(round_id=round_id)
        for warning in mp3_result.get("warnings", []):
            issues.append(_quality_issue("mp3_quality_warning", warning))
    except Exception as exc:
        issues.append(_quality_issue("mp3_inspection_failed", str(exc)))

    if expected_ms is not None and mp3_result and mp3_result.get("duration_seconds") is not None:
        expected_seconds = expected_ms / 1000
        actual_seconds = float(mp3_result["duration_seconds"])
        delta_seconds = actual_seconds - expected_seconds
        if abs(delta_seconds) > duration_tolerance_seconds:
            issue = _quality_issue(
                "round_mp3_duration_mismatch",
                (
                    f"Generated MP3 is {actual_seconds:.1f}s, expected about "
                    f"{expected_seconds:.1f}s from intro, replay, outro, number "
                    "announcements, and two plays of every preview."
                ),
                details={
                    "actual_seconds": round(actual_seconds, 3),
                    "expected_seconds": round(expected_seconds, 3),
                    "delta_seconds": round(delta_seconds, 3),
                    "tolerance_seconds": duration_tolerance_seconds,
                },
            )
            issues.append(issue)
            remediation.append(
                {
                    "action": "regenerate_assets",
                    "issue_code": issue["code"],
                    "message": issue["message"],
                }
            )

    issue_codes = {issue["code"] for issue in issues}
    if not issues:
        status = "ok"
    elif issue_codes & {"actual_song_count_mismatch", "resolved_song_count_mismatch"}:
        status = "needs_more_songs" if len(songs) < expected_song_count else "blocked"
    elif issue_codes & {
        "missing_deezer_id",
        "missing_preview_url",
        "preview_too_short",
        "preview_too_long",
        "preview_download_failed",
    }:
        status = "needs_substitution"
    elif issue_codes & {"pdf_inspection_failed", "mp3_inspection_failed", "round_mp3_duration_mismatch"}:
        status = "render_failed"
    else:
        status = "blocked"

    return {
        "round_id": round_id,
        "round_name": round_obj.name,
        "status": status,
        "expected_song_count": expected_song_count,
        "actual_song_count": actual_song_count,
        "resolved_song_count": resolved_song_count,
        "song_count": len(songs),
        "preview_checks": preview_checks,
        "components": components,
        "expected_duration_seconds": None if expected_ms is None else round(expected_ms / 1000, 3),
        "pdf": pdf_result,
        "mp3": mp3_result,
        "issues": issues,
        "hints": [issue["message"] for issue in issues],
        "remediation": remediation,
        "ok": not issues,
    }


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
    quality = inspect_round_package(round_id, user_id=user.id)
    if not quality["ok"]:
        message = "Round quality gate failed: " + "; ".join(quality["hints"])
        db.session.add(
            RoundExport(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                destination=target,
                include_mp3s=True,
                status="failed",
                error_message=message,
            )
        )
        db.session.commit()
        raise AutomationError(
            message,
            details={
                "success": False,
                "status": quality["status"],
                "recipient": target,
                "assets": assets,
                "quality": quality,
            },
        )

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
    return {
        "success": True,
        "message": message,
        "recipient": target,
        "assets": assets,
        "quality": quality,
    }


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
