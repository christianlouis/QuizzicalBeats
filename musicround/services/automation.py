"""Automation services used by the MCP server and agent workflows."""

from __future__ import annotations

import os
import re
import csv
import json
import math
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests
from flask import current_app
from flask_login import login_user, logout_user
from pydub import AudioSegment
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_

from musicround import db
from musicround.helpers.database_config import (
    bool_from_config,
    database_cutover_plan,
    database_summary,
    database_uri_overrides_postgres_env,
    is_legacy_data_sqlite_uri,
    managed_database_requirement_error,
    postgres_env_readiness,
)
from musicround.helpers.email_helper import send_email
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.round_notifications import send_round_blocked_notification
from musicround.helpers.paths import app_data_path
from musicround.helpers.storage_health import (
    check_round_artifact_storage,
    require_round_artifact_storage,
    round_mp3_dir,
    round_pdf_dir,
)
from musicround.helpers.service_health import (
    artifact_storage_service_health,
    dropbox_service_health,
    email_service_health,
    spotify_service_health,
)
from musicround.helpers.utils import generate_tts_mp3, get_mp3_path
from musicround import models as datastore_models
from musicround.models import (
    ImportJobRecord,
    PlannedQuizRound,
    Round,
    RoundAccessEvent,
    RoundAudioScript,
    RoundExport,
    RoundShare,
    SeedSource,
    SeedSourceRun,
    Song,
    SystemSetting,
    Tag,
    User,
)


class AutomationError(ValueError):
    """Raised when an automation request cannot be completed."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


AUTOMATION_STORAGE_ERROR = "Round artifact storage is unhealthy."
AUTOMATION_PDF_INSPECTION_ERROR = "PDF inspection failed."
AUTOMATION_MP3_INSPECTION_ERROR = "MP3 inspection failed."
AUTOMATION_MP3_GENERATION_ERROR = "MP3 generation failed. Check the server logs."
AUTOMATION_SCHEDULED_EMAIL_ERROR = "Scheduled round email failed. Check the server logs."
AUTOMATION_SEED_SOURCE_FETCH_ERROR = "Seed source fetch failed. Check the server logs."
DEFAULT_MP3_DURATION_TOLERANCE_SECONDS = 30.0
MIN_MP3_DURATION_MISMATCH_BLOCK_SECONDS = 40.0
ROUND_SHARE_ROLES = {"viewer", "editor", "producer"}
MP3_DURATION_MISSING_SLOT_FACTOR = 0.75
DEFAULT_SEED_SOURCE_DEFINITIONS = [
    {
        "name": "Billboard Hot 100",
        "source_type": "chart",
        "provider": "billboard",
        "url": "https://www.billboard.com/charts/hot-100/",
        "cadence": "weekly",
        "priority": 10,
        "notes": "US mainstream singles chart for broad recognizability.",
    },
    {
        "name": "Billboard 200",
        "source_type": "chart",
        "provider": "billboard",
        "url": "https://www.billboard.com/charts/billboard-200/",
        "cadence": "weekly",
        "priority": 20,
        "notes": "US albums chart for artist and album-era research.",
    },
    {
        "name": "Official Singles Chart",
        "source_type": "chart",
        "provider": "official-charts",
        "url": "https://www.officialcharts.com/charts/singles-chart/",
        "cadence": "weekly",
        "priority": 30,
        "notes": "UK singles chart for quiz-friendly mainstream picks.",
    },
    {
        "name": "Official Albums Chart",
        "source_type": "chart",
        "provider": "official-charts",
        "url": "https://www.officialcharts.com/charts/albums-chart/",
        "cadence": "weekly",
        "priority": 40,
        "notes": "UK albums chart for recurring artist and album context.",
    },
    {
        "name": "Offizielle Deutsche Charts Singles",
        "source_type": "chart",
        "provider": "germany-official-charts",
        "url": "https://www.offiziellecharts.de/charts/single",
        "cadence": "weekly",
        "priority": 50,
        "notes": "German singles chart for local mainstream coverage.",
    },
    {
        "name": "Spotify Charts",
        "source_type": "chart",
        "provider": "spotify",
        "url": "https://charts.spotify.com/",
        "cadence": "weekly",
        "priority": 60,
        "notes": "Streaming chart entry point for current-popularity research.",
    },
    {
        "name": "Wacken Open Air Line-Up",
        "source_type": "festival",
        "provider": "wacken",
        "url": "https://www.wacken.com/en/program/",
        "cadence": "annual",
        "priority": 110,
        "notes": "Metal and hard-rock festival source for headliner research.",
    },
    {
        "name": "Graspop Metal Meeting Line-Up",
        "source_type": "festival",
        "provider": "graspop",
        "url": "https://www.graspop.be/en/line-up/",
        "cadence": "annual",
        "priority": 120,
        "notes": "Metal festival source for European headliner research.",
    },
    {
        "name": "Download Festival Line-Up",
        "source_type": "festival",
        "provider": "download",
        "url": "https://downloadfestival.co.uk/line-up/",
        "cadence": "annual",
        "priority": 130,
        "notes": "UK rock and metal festival source for headliner research.",
    },
    {
        "name": "Rock am Ring Line-Up",
        "source_type": "festival",
        "provider": "rock-am-ring",
        "url": "https://www.rock-am-ring.com/en/lineup/",
        "cadence": "annual",
        "priority": 140,
        "notes": "German rock festival source for local and international headliners.",
    },
]


def _round_song_ids(round_obj: Round) -> list[int]:
    return [int(song_id) for song_id in round_obj.songs.split(",") if song_id]


def _ordered_round_songs(round_obj: Round) -> list[Song]:
    ids = _round_song_ids(round_obj)
    songs = Song.query.filter(Song.id.in_(ids)).all()
    songs_by_id = {song.id: song for song in songs}
    return [songs_by_id[song_id] for song_id in ids if song_id in songs_by_id]


def _playlist_position_map(
    song_ids: list[int],
    expected_count: int | None = None,
    source_positions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    limit = expected_count if expected_count is not None else len(song_ids)
    if source_positions:
        positions = []
        selected = source_positions[:limit]
        for index, source in enumerate(selected):
            song_id = source.get("song_id")
            try:
                song_id = int(song_id) if song_id is not None else None
            except (TypeError, ValueError):
                song_id = None
            status = source.get("status") or ("resolved" if song_id else "failed")
            positions.append({
                "position": source.get("position") or index + 1,
                "song_id": song_id,
                "resolved": bool(song_id) and status == "resolved",
                "status": status,
                "spotify_track_id": source.get("spotify_track_id"),
                "artist": source.get("artist"),
                "title": source.get("title"),
                "reason": source.get("reason"),
            })
        for index in range(len(selected), limit):
            positions.append({
                "position": index + 1,
                "song_id": None,
                "resolved": False,
                "status": "missing",
                "spotify_track_id": None,
                "artist": None,
                "title": None,
                "reason": "no_playlist_position",
            })
        return positions

    positions = []
    for index, song_id in enumerate(song_ids[:limit]):
        positions.append({
            "position": index + 1,
            "song_id": song_id,
            "resolved": True,
            "status": "resolved",
            "spotify_track_id": None,
            "artist": None,
            "title": None,
            "reason": None,
        })
    for index in range(len(song_ids), limit):
        positions.append({
            "position": index + 1,
            "song_id": None,
            "resolved": False,
            "status": "missing",
            "spotify_track_id": None,
            "artist": None,
            "title": None,
            "reason": "not_resolved",
        })
    return positions


def _song_summary(song: Song) -> dict[str, Any]:
    data = song.to_dict()
    preview_url = (
        song.preview_url
        or song.spotify_preview_url
        or song.deezer_preview_url
        or song.apple_preview_url
        or song.youtube_preview_url
    )
    return {
        "id": data["id"],
        "title": data["title"],
        "artist": data["artist"],
        "genre": data["genre"],
        "year": data["year"],
        "source": song.source,
        "preview_url": preview_url,
        "spotify_id": data["spotify_id"],
        "deezer_id": data["deezer_id"],
        "isrc": data["isrc"],
        "used_count": data["used_count"] or 0,
        "usage_frequency": data["used_count"] or 0,
        "last_used": data["last_used"],
        "tags": data["tags"],
    }


def _user_summary(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "name": " ".join(part for part in (user.first_name, user.last_name) if part) or None,
    }


def _public_user_summary(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "name": " ".join(part for part in (user.first_name, user.last_name) if part) or None,
    }


def _round_share_summary(share: RoundShare) -> dict[str, Any]:
    return {
        "id": share.id,
        "round_id": share.round_id,
        "user_id": share.user_id,
        "role": share.role,
        "created_at": _datetime_payload(share.created_at),
        "user": _user_summary(share.user),
    }


def _round_access_event_summary(event: RoundAccessEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "round_id": event.round_id,
        "action": event.action,
        "role": event.role,
        "details": event.details,
        "created_at": _datetime_payload(event.created_at),
        "actor_user_id": event.actor_user_id,
        "actor": _user_summary(event.actor),
        "target_user_id": event.target_user_id,
        "target_user": _user_summary(event.target_user),
    }


def database_configuration_summary() -> dict[str, Any]:
    """Return credential-safe database readiness details for agent workflows."""
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    summary = database_summary(db_uri)
    managed_required = bool_from_config(current_app.config.get("DATABASE_REQUIRE_MANAGED"))
    postgres_readiness = postgres_env_readiness(os.environ)
    managed_error = managed_database_requirement_error(db_uri, managed_required)
    issues: list[dict[str, Any]] = []

    if managed_error:
        issues.append(
            {
                "code": "managed_database_requirement_failed",
                "message": managed_error,
                "severity": "error",
            }
        )
    elif is_legacy_data_sqlite_uri(db_uri):
        issues.append(
            {
                "code": "legacy_sqlite_data_store",
                "message": "Database is still configured to use the legacy /data SQLite file.",
                "severity": "warning",
                "hint": (
                    "Configure a managed SQL URI or complete PG* credentials via "
                    "secrets, then enable DATABASE_REQUIRE_MANAGED=true."
                ),
            }
        )
    if database_uri_overrides_postgres_env(os.environ):
        issues.append(
            {
                "code": "database_uri_overrides_postgres_env",
                "message": (
                    "SQLALCHEMY_DATABASE_URI is overriding complete split "
                    "PostgreSQL configuration."
                ),
                "severity": "warning",
                "hint": (
                    "Remove or blank SQLALCHEMY_DATABASE_URI before relying on "
                    "PG* managed database secrets during cutover."
                ),
            }
        )

    status = "ok"
    if any(issue["severity"] == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"

    return {
        "ok": status != "error",
        "status": status,
        "managed_required": managed_required,
        "database": summary,
        "postgres_env": postgres_readiness,
        "issues": issues,
    }


def database_cutover_plan_summary() -> dict[str, Any]:
    """Return a credential-safe managed database cutover plan for agents."""
    return database_cutover_plan(database_configuration_summary())


def _record_round_access_event(
    round_obj: Round,
    action: str,
    *,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    role: str | None = None,
    details: str | None = None,
) -> RoundAccessEvent:
    event = RoundAccessEvent(
        round_id=round_obj.id,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        role=role,
        details=details,
    )
    db.session.add(event)
    return event


def _validate_round_access_actor(actor_user_id: int | None) -> int | None:
    if actor_user_id is None:
        return None
    return _find_user(actor_user_id).id


def _validate_round_access_requester(round_obj: Round, requester_user_id: int | None) -> None:
    if requester_user_id is None:
        return
    requester = _find_user(requester_user_id)
    if requester.is_admin or round_obj.user_id == requester.id:
        return
    raise AutomationError("Only the round owner or an admin can view round access events.")


def _validate_round_manager(round_obj: Round, actor_user_id: int | None) -> int | None:
    actor_id = _validate_round_access_actor(actor_user_id)
    if actor_id is None:
        return None
    actor = db.session.get(User, actor_id)
    if actor and (actor.is_admin or round_obj.user_id == actor.id):
        return actor.id
    raise AutomationError("Only the round owner or an admin can manage public links.")


def _public_round_links_enabled() -> bool:
    return SystemSetting.get("enable_public_rounds", "false") == "true"


def _new_public_round_token() -> str:
    while True:
        token = secrets.token_urlsafe(24)
        if not Round.query.filter_by(public_token=token).first():
            return token


def _round_summary(round_obj: Round) -> dict[str, Any]:
    ids = _round_song_ids(round_obj)
    ordered = _ordered_round_songs(round_obj)
    return {
        "id": round_obj.id,
        "name": round_obj.name,
        "owner_user_id": round_obj.user_id,
        "owner": _user_summary(round_obj.owner),
        "visibility": round_obj.visibility,
        "public_link_enabled": bool(round_obj.public_token),
        "public_token_created_at": _datetime_payload(round_obj.public_token_created_at),
        "round_type": round_obj.round_type,
        "criteria": round_obj.round_criteria_used,
        "song_ids": ids,
        "songs": [_song_summary(song) for song in ordered],
        "shares": [_round_share_summary(share) for share in round_obj.shares.order_by(RoundShare.id.asc()).all()],
        "mp3_generated": round_obj.mp3_generated,
        "pdf_generated": round_obj.pdf_generated,
        "last_generated_at": (
            round_obj.last_generated_at.isoformat() if round_obj.last_generated_at else None
        ),
    }


def _public_round_summary(round_obj: Round) -> dict[str, Any]:
    return {
        "id": round_obj.id,
        "name": round_obj.name,
        "round_type": round_obj.round_type,
        "criteria": round_obj.round_criteria_used,
        "created_at": _datetime_payload(round_obj.created_at),
        "song_count": len(_round_song_ids(round_obj)),
        "songs": [_song_summary(song) for song in _ordered_round_songs(round_obj)],
        "owner": _public_user_summary(round_obj.owner),
    }


def _planned_quiz_round_summary(plan: PlannedQuizRound) -> dict[str, Any]:
    return {
        "id": plan.id,
        "quiz_date": _datetime_payload(plan.quiz_date),
        "quizmaster_id": plan.quizmaster_id,
        "quizmaster": _user_summary(plan.quizmaster),
        "theme": plan.theme,
        "brief": plan.brief,
        "source_playlist_url": plan.source_playlist_url,
        "due_at": _datetime_payload(plan.due_at),
        "status": plan.status,
        "round_id": plan.round_id,
        "round": _round_summary(plan.round) if plan.round else None,
        "export_id": plan.export_id,
        "export": _round_export_summary(plan.export) if plan.export else None,
        "created_at": _datetime_payload(plan.created_at),
        "updated_at": _datetime_payload(plan.updated_at),
    }


def _seed_source_run_summary(run: SeedSourceRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "seed_source_id": run.seed_source_id,
        "status": run.status,
        "started_at": _datetime_payload(run.started_at),
        "completed_at": _datetime_payload(run.completed_at),
        "songs_seen": run.songs_seen,
        "songs_imported": run.songs_imported,
        "error_message": run.error_message,
        "notes": run.notes,
    }


def _seed_source_summary(source: SeedSource, include_runs: bool = False) -> dict[str, Any]:
    """Summarize a seed source and optionally include recent run history.

    Args:
        source: Seed source model to serialize.
        include_runs: When true, include up to 20 recent runs and derive
            latest_run from that fetched list. When false, only latest_run is
            queried.

    Returns:
        Dictionary payload suitable for MCP and automation responses.
    """
    ordered_runs = source.runs.order_by(SeedSourceRun.started_at.desc(), SeedSourceRun.id.desc())
    if include_runs:
        runs = ordered_runs.limit(20).all()
        latest_run = runs[0] if runs else None
    else:
        runs = []
        latest_run = ordered_runs.first()
    payload = {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "provider": source.provider,
        "url": source.url,
        "cadence": source.cadence,
        "active": source.active,
        "priority": source.priority,
        "notes": source.notes,
        "created_at": _datetime_payload(source.created_at),
        "updated_at": _datetime_payload(source.updated_at),
        "latest_run": _seed_source_run_summary(latest_run) if latest_run else None,
    }
    if include_runs:
        payload["runs"] = [_seed_source_run_summary(run) for run in runs]
    return payload


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
    genre: str | None = None,
    year: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    has_preview: bool | None = None,
    unused_only: bool = False,
    offset: int = 0,
    order_by: str = "artist",
    spotify_id: str | None = None,
    deezer_id: str | None = None,
    isrc: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search the local catalog before adding or importing tracks."""
    if limit < 1 or limit > 100:
        raise AutomationError("limit must be between 1 and 100.")
    if offset < 0:
        raise AutomationError("offset must not be negative.")

    filters = []
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(or_(Song.title.ilike(pattern), Song.artist.ilike(pattern)))
    if title:
        filters.append(Song.title.ilike(f"%{title.strip()}%"))
    if artist:
        filters.append(Song.artist.ilike(f"%{artist.strip()}%"))
    if genre:
        filters.append(Song.genre.ilike(genre.strip()))
    if year is not None:
        filters.append(Song.year == int(year))
    if year_min is not None:
        filters.append(Song.year >= int(year_min))
    if year_max is not None:
        filters.append(Song.year <= int(year_max))
    if has_preview is True:
        filters.append(or_(
            Song.preview_url.isnot(None),
            Song.spotify_preview_url.isnot(None),
            Song.deezer_preview_url.isnot(None),
            Song.apple_preview_url.isnot(None),
            Song.youtube_preview_url.isnot(None),
        ))
    elif has_preview is False:
        filters.extend([
            Song.preview_url.is_(None),
            Song.spotify_preview_url.is_(None),
            Song.deezer_preview_url.is_(None),
            Song.apple_preview_url.is_(None),
            Song.youtube_preview_url.is_(None),
        ])
    if unused_only:
        filters.append(or_(Song.used_count == 0, Song.used_count.is_(None)))
    if spotify_id:
        filters.append(Song.spotify_id == spotify_id)
    if deezer_id:
        filters.append(Song.deezer_id == str(deezer_id))
    if isrc:
        filters.append(Song.isrc == isrc)

    song_query = Song.query
    for condition in filters:
        song_query = song_query.filter(condition)
    total = song_query.count()

    descending = order_by.startswith("-")
    field_name = order_by[1:] if descending else order_by
    allowed_order = {
        "artist": Song.artist,
        "title": Song.title,
        "genre": Song.genre,
        "year": Song.year,
        "used_count": Song.used_count,
        "last_used": Song.last_used,
        "id": Song.id,
    }
    column = allowed_order.get(field_name)
    if column is None:
        raise AutomationError(
            "order_by must be one of artist, title, genre, year, used_count, last_used, id."
        )
    song_query = song_query.order_by(column.desc() if descending else column.asc())
    if field_name not in {"artist", "title"}:
        song_query = song_query.order_by(Song.artist.asc(), Song.title.asc())

    songs = song_query.offset(offset).limit(limit).all()
    return {
        "count": len(songs),
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": {
            "query": query,
            "title": title,
            "artist": artist,
            "genre": genre,
            "year": year,
            "year_min": year_min,
            "year_max": year_max,
            "has_preview": has_preview,
            "unused_only": unused_only,
            "spotify_id": spotify_id,
            "deezer_id": deezer_id,
            "isrc": isrc,
            "order_by": order_by,
        },
        "songs": [_song_summary(song) for song in songs],
    }


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
    user_id: int | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    """Create and persist a quiz round."""
    if count < 1:
        raise AutomationError("count must be at least 1.")
    if visibility not in {"private", "shared", "public"}:
        raise AutomationError("visibility must be private, shared, or public.")

    resolved_type, resolved_criteria, songs = _songs_for_round(
        round_type, count, criteria, song_ids
    )
    if not songs:
        raise AutomationError("No songs matched the requested round criteria.")

    owner = _find_user(user_id) if user_id is not None else None
    round_obj = Round(
        name=name,
        user_id=owner.id if owner else None,
        visibility=visibility,
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


def set_round_owner(
    round_id: int,
    user_id: int | None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Assign or clear a round owner and optionally update visibility."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    owner = _find_user(user_id) if user_id is not None else None
    if visibility is not None and visibility not in {"private", "shared", "public"}:
        raise AutomationError("visibility must be private, shared, or public.")

    round_obj.user_id = owner.id if owner else None
    if visibility is not None:
        round_obj.visibility = visibility
    round_obj.updated_at = datetime.utcnow()
    db.session.commit()
    return {"round": _round_summary(round_obj)}


def share_round(
    round_id: int,
    user_id: int,
    role: str = "viewer",
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Grant a user access to a round for future collaboration workflows."""
    if role not in ROUND_SHARE_ROLES:
        raise AutomationError("role must be viewer, editor, or producer.")

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    user = _find_user(user_id)
    actor_user_id = _validate_round_access_actor(actor_user_id)
    if round_obj.user_id == user.id:
        raise AutomationError("The owner already has access to this round.")

    share = RoundShare.query.filter_by(round_id=round_id, user_id=user.id).first()
    created = share is None
    if not share:
        share = RoundShare(round_id=round_id, user_id=user.id)
        db.session.add(share)
    share.role = role
    round_obj.visibility = "shared"
    round_obj.updated_at = datetime.utcnow()
    event = _record_round_access_event(
        round_obj,
        "share_created" if created else "share_updated",
        actor_user_id=actor_user_id,
        target_user_id=user.id,
        role=role,
    )
    db.session.commit()
    return {
        "created": created,
        "share": _round_share_summary(share),
        "access_event": _round_access_event_summary(event),
        "round": _round_summary(round_obj),
    }


def list_round_shares(round_id: int) -> dict[str, Any]:
    """List owner and explicit share grants for a round."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    shares = round_obj.shares.order_by(RoundShare.id.asc()).all()
    return {
        "round_id": round_id,
        "visibility": round_obj.visibility,
        "owner": _user_summary(round_obj.owner),
        "count": len(shares),
        "shares": [_round_share_summary(share) for share in shares],
    }


def revoke_round_share(
    round_id: int,
    user_id: int,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Remove a user's explicit share grant from a round."""
    actor_user_id = _validate_round_access_actor(actor_user_id)
    share = RoundShare.query.filter_by(round_id=round_id, user_id=user_id).first()
    if not share:
        raise AutomationError(f"Round {round_id} is not shared with user {user_id}.")
    removed = _round_share_summary(share)
    round_obj = db.session.get(Round, round_id)
    db.session.delete(share)
    db.session.flush()
    event = None
    if round_obj:
        event = _record_round_access_event(
            round_obj,
            "share_revoked",
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            role=removed.get("role"),
        )
    if round_obj and round_obj.visibility == "shared" and round_obj.shares.count() == 0:
        round_obj.visibility = "private"
        round_obj.updated_at = datetime.utcnow()
    db.session.commit()
    return {
        "revoked": True,
        "share": removed,
        "access_event": _round_access_event_summary(event) if event else None,
        "round": _round_summary(round_obj) if round_obj else None,
    }


def list_round_access_events(
    round_id: int,
    limit: int = 50,
    requester_user_id: int | None = None,
) -> dict[str, Any]:
    """List recent ownership and sharing audit events for a round."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    _validate_round_access_requester(round_obj, requester_user_id)
    try:
        requested_limit = int(limit or 50)
    except (TypeError, ValueError) as exc:
        raise AutomationError("limit must be an integer.") from exc
    normalized_limit = max(1, min(requested_limit, 200))
    events = (
        RoundAccessEvent.query.filter_by(round_id=round_id)
        .order_by(RoundAccessEvent.created_at.desc(), RoundAccessEvent.id.desc())
        .limit(normalized_limit)
        .all()
    )
    return {
        "round_id": round_id,
        "count": len(events),
        "events": [_round_access_event_summary(event) for event in events],
    }


def enable_round_public_link(
    round_id: int,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Enable a token-based read-only public link for a round."""
    if not _public_round_links_enabled():
        raise AutomationError("Public round links are disabled in system settings.")
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    actor_id = _validate_round_manager(round_obj, actor_user_id)
    created = not bool(round_obj.public_token)
    if not round_obj.public_token:
        round_obj.public_token = _new_public_round_token()
        round_obj.public_token_created_at = datetime.utcnow()
    round_obj.updated_at = datetime.utcnow()
    event = _record_round_access_event(
        round_obj,
        "public_link_enabled" if created else "public_link_refreshed",
        actor_user_id=actor_id,
    )
    db.session.commit()
    return {
        "created": created,
        "public_token": round_obj.public_token,
        "public_url_path": f"/rounds/public/{round_obj.public_token}",
        "public_token_created_at": _datetime_payload(round_obj.public_token_created_at),
        "access_event": _round_access_event_summary(event),
        "round": _round_summary(round_obj),
    }


def disable_round_public_link(
    round_id: int,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Disable a token-based read-only public link for a round."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    actor_id = _validate_round_manager(round_obj, actor_user_id)
    had_public_link = bool(round_obj.public_token)
    round_obj.public_token = None
    round_obj.public_token_created_at = None
    round_obj.updated_at = datetime.utcnow()
    event = _record_round_access_event(
        round_obj,
        "public_link_disabled",
        actor_user_id=actor_id,
    )
    db.session.commit()
    return {
        "disabled": had_public_link,
        "access_event": _round_access_event_summary(event),
        "round": _round_summary(round_obj),
    }


def get_public_round(public_token: str) -> dict[str, Any]:
    """Return read-only round data for an active public token."""
    token = (public_token or "").strip()
    if not token:
        raise AutomationError("public_token is required.")
    round_obj = Round.query.filter_by(public_token=token).first()
    if not round_obj:
        raise AutomationError("Public round link was not found.")
    return {"round": _public_round_summary(round_obj)}


def register_seed_source(
    name: str,
    source_type: str,
    provider: str | None = None,
    url: str | None = None,
    cadence: str | None = None,
    priority: int = 100,
    active: bool = True,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create or update a catalog seed source for chart/festival ingestion."""
    normalized_name = (name or "").strip()
    normalized_type = (source_type or "").strip().lower()
    normalized_provider = (provider or "").strip() or None
    if not normalized_name:
        raise AutomationError("name must not be empty.")
    if normalized_type not in {"chart", "festival", "editorial", "curated", "playlist"}:
        raise AutomationError("source_type must be chart, festival, editorial, curated, or playlist.")
    if priority < 0 or priority > 1000:
        raise AutomationError("priority must be between 0 and 1000.")

    source = SeedSource.query.filter_by(
        name=normalized_name,
        provider=normalized_provider,
    ).first()
    created = source is None
    if source is None:
        source = SeedSource(name=normalized_name, provider=normalized_provider)
        db.session.add(source)

    source.source_type = normalized_type
    source.url = (url or "").strip() or None
    source.cadence = (cadence or "").strip() or None
    source.priority = priority
    source.active = bool(active)
    source.notes = (notes or "").strip() or None
    source.updated_at = datetime.utcnow()
    db.session.commit()

    return {"created": created, "seed_source": _seed_source_summary(source, include_runs=True)}


def list_seed_sources(
    source_type: str | None = None,
    active: bool | None = True,
    include_runs: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """List configured chart/festival seed sources for agent planning."""
    if limit < 1 or limit > 500:
        raise AutomationError("limit must be between 1 and 500.")
    query = SeedSource.query
    if source_type:
        query = query.filter(SeedSource.source_type == source_type.strip().lower())
    if active is not None:
        query = query.filter(SeedSource.active.is_(bool(active)))
    sources = (
        query
        .order_by(SeedSource.priority.asc(), SeedSource.name.asc(), SeedSource.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(sources),
        "sources": [_seed_source_summary(source, include_runs=include_runs) for source in sources],
    }


def seed_default_seed_sources() -> dict[str, Any]:
    """Create or update default chart and festival source registry entries."""
    seeded = []
    created_count = 0
    for definition in DEFAULT_SEED_SOURCE_DEFINITIONS:
        result = register_seed_source(**definition)
        created_count += 1 if result["created"] else 0
        seeded.append(result["seed_source"])

    return {
        "ok": True,
        "count": len(seeded),
        "created_count": created_count,
        "updated_count": len(seeded) - created_count,
        "sources": seeded,
        "hints": [
            "Default sources are registry metadata only; no songs are imported.",
            "Use fetch_seed_source_candidates for read-only source review before building provider-specific importers.",
        ],
    }


def record_seed_source_run(
    seed_source_id: int,
    status: str,
    songs_seen: int = 0,
    songs_imported: int = 0,
    error_message: str | None = None,
    notes: str | None = None,
    completed: bool = True,
) -> dict[str, Any]:
    """Record an import/read attempt for a seed source."""
    source = db.session.get(SeedSource, seed_source_id)
    if not source:
        raise AutomationError(f"Seed source {seed_source_id} was not found.")
    normalized_status = (status or "").strip().lower()
    if normalized_status not in {"planned", "running", "success", "partial", "failed"}:
        raise AutomationError("status must be planned, running, success, partial, or failed.")
    if songs_seen < 0 or songs_imported < 0:
        raise AutomationError("song counts must not be negative.")

    run = SeedSourceRun(
        seed_source_id=source.id,
        status=normalized_status,
        songs_seen=songs_seen,
        songs_imported=songs_imported,
        error_message=(error_message or "").strip() or None,
        notes=(notes or "").strip() or None,
        completed_at=datetime.utcnow() if completed else None,
    )
    db.session.add(run)
    source.updated_at = datetime.utcnow()
    db.session.commit()
    return {
        "recorded": True,
        "seed_source": _seed_source_summary(source),
        "run": _seed_source_run_summary(run),
    }


def _seed_source_candidate_from_mapping(
    row: dict[str, Any],
    line_number: int,
) -> dict[str, Any] | None:
    title_keys = ("title", "song", "song_title", "track", "track_title", "name")
    artist_keys = ("artist", "artists", "artist_name", "performer", "act")
    normalized = {str(key).strip().casefold().replace(" ", "_"): value for key, value in row.items()}
    title = next((normalized[key] for key in title_keys if normalized.get(key)), None)
    artist = next((normalized[key] for key in artist_keys if normalized.get(key)), None)
    raw = json.dumps(row, sort_keys=True, ensure_ascii=True)
    return _playlist_candidate(line_number, raw, str(title or ""), str(artist or ""))


def _seed_source_candidates_from_json_payload(
    payload: Any,
    limit: int,
) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("candidates", "tracks", "songs", "items", "results", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []

    candidates: list[dict[str, Any]] = []
    for line_number, row in enumerate(payload, start=1):
        if len(candidates) >= limit:
            break
        if isinstance(row, dict):
            candidate = _seed_source_candidate_from_mapping(row, line_number)
        elif isinstance(row, str):
            title, artist, confidence, issues = _split_playlist_line(row)
            candidate = _playlist_candidate(line_number, row, title, artist, confidence, issues)
        else:
            candidate = None
        if candidate:
            candidates.append(candidate)
    return candidates


def _parse_seed_source_payload(text: str, content_type: str | None, limit: int) -> dict[str, Any]:
    content_type = (content_type or "").casefold()
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            candidates = _seed_source_candidates_from_json_payload(json.loads(text), limit)
        except json.JSONDecodeError:
            candidates = []
        if candidates:
            low_confidence = [candidate for candidate in candidates if candidate["needs_review"]]
            return {
                "count": len(candidates),
                "candidates": candidates,
                "low_confidence_count": len(low_confidence),
                "low_confidence": low_confidence,
                "ready_for_import": bool(candidates) and not low_confidence,
                "hints": ["Review source candidates before importing songs."],
            }
    return parse_text_playlist(text, limit=limit)


def fetch_seed_source_candidates(
    seed_source_id: int,
    text: str | None = None,
    limit: int = 100,
    timeout_seconds: float = 20.0,
    record_run: bool = True,
) -> dict[str, Any]:
    """Read a seed source into reviewable candidates without importing songs."""
    if limit < 1 or limit > 500:
        raise AutomationError("limit must be between 1 and 500.")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or timeout_seconds > 60:
        raise AutomationError("timeout_seconds must be between 0 and 60.")

    source = db.session.get(SeedSource, seed_source_id)
    if not source:
        raise AutomationError(f"Seed source {seed_source_id} was not found.")

    content_type = None
    payload_text = (text or "").strip()
    try:
        if not payload_text:
            if not source.url:
                raise AutomationError("seed source has no URL; pass text for manual review.")
            response = requests.get(source.url, timeout=timeout_seconds)
            if response.status_code >= 400:
                raise AutomationError(AUTOMATION_SEED_SOURCE_FETCH_ERROR)
            content_type = response.headers.get("content-type")
            payload_text = response.text
        parsed = _parse_seed_source_payload(payload_text, content_type, limit)
    except AutomationError as exc:
        if record_run:
            record_seed_source_run(
                source.id,
                status="failed",
                error_message=AUTOMATION_SEED_SOURCE_FETCH_ERROR
                if str(exc) == AUTOMATION_SEED_SOURCE_FETCH_ERROR
                else str(exc),
                completed=True,
            )
        raise
    except Exception as exc:
        current_app.logger.error("Seed source fetch failed for %s: %s", source.id, exc, exc_info=True)
        if record_run:
            record_seed_source_run(
                source.id,
                status="failed",
                error_message=AUTOMATION_SEED_SOURCE_FETCH_ERROR,
                completed=True,
            )
        raise AutomationError(AUTOMATION_SEED_SOURCE_FETCH_ERROR) from exc

    run = None
    if record_run:
        run_status = "partial" if parsed["low_confidence_count"] else "success"
        run = record_seed_source_run(
            source.id,
            status=run_status,
            songs_seen=parsed["count"],
            songs_imported=0,
            notes="Fetched candidates only; no songs were imported.",
            completed=True,
        )["run"]

    return {
        "ok": True,
        "seed_source": _seed_source_summary(source),
        "provider": source.provider,
        "source_type": source.source_type,
        "count": parsed["count"],
        "candidates": parsed["candidates"],
        "low_confidence_count": parsed["low_confidence_count"],
        "low_confidence": parsed["low_confidence"],
        "ready_for_import": parsed["ready_for_import"],
        "imported": False,
        "run": run,
        "hints": [
            "This read-only step does not import songs.",
            "Review candidates, resolve low-confidence rows, then use explicit import or round-creation tools.",
        ],
    }


def _song_position(round_obj: Round, position: int) -> tuple[list[int], int]:
    song_ids = _round_song_ids(round_obj)
    if position < 1 or position > len(song_ids):
        raise AutomationError(
            f"Position {position} is outside this round. Allowed positions are 1-{len(song_ids)}."
        )
    return song_ids, position - 1


def _record_song_added_to_round(song: Song) -> None:
    song.used_count = (song.used_count or 0) + 1
    song.last_used = datetime.utcnow()


def _record_song_removed_from_round(song: Song | None) -> None:
    if song and song.used_count:
        song.used_count = max(song.used_count - 1, 0)


def replace_round_song(
    round_id: int,
    position: int,
    replacement_song_id: int,
    inspect_after: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Replace one song at a 1-based round position and mark generated assets stale."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    song_ids, index = _song_position(round_obj, position)
    replacement = db.session.get(Song, replacement_song_id)
    if not replacement:
        raise AutomationError(f"Song {replacement_song_id} was not found.")

    old_song_id = song_ids[index]
    if replacement.id in song_ids and replacement.id != old_song_id:
        raise AutomationError(f"Song {replacement.id} is already in round {round_id}.")

    old_song = db.session.get(Song, old_song_id)
    song_ids[index] = replacement.id
    round_obj.songs = ",".join(str(song_id) for song_id in song_ids)
    if replacement.id != old_song_id:
        _record_song_removed_from_round(old_song)
        _record_song_added_to_round(replacement)
        round_obj.reset_generated_status()
        round_obj.updated_at = datetime.utcnow()
    db.session.commit()

    result: dict[str, Any] = {
        "round": _round_summary(round_obj),
        "position": position,
        "replaced_song": _song_summary(old_song) if old_song else {"id": old_song_id},
        "replacement_song": _song_summary(replacement),
        "assets_invalidated": replacement.id != old_song_id,
    }
    if inspect_after:
        result["quality"] = inspect_round_package(round_id, user_id=user_id)
    return result


def add_round_song(
    round_id: int,
    song_id: int,
    position: int | None = None,
    inspect_after: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Add one song to a round at a 1-based position or append it."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    song = db.session.get(Song, song_id)
    if not song:
        raise AutomationError(f"Song {song_id} was not found.")

    song_ids = _round_song_ids(round_obj)
    if song.id in song_ids:
        raise AutomationError(f"Song {song.id} is already in round {round_id}.")

    insert_position = position if position is not None else len(song_ids) + 1
    if insert_position < 1 or insert_position > len(song_ids) + 1:
        raise AutomationError(
            f"Position {insert_position} is outside this round. "
            f"Allowed insert positions are 1-{len(song_ids) + 1}."
        )

    song_ids.insert(insert_position - 1, song.id)
    round_obj.songs = ",".join(str(existing_id) for existing_id in song_ids)
    _record_song_added_to_round(song)
    round_obj.reset_generated_status()
    round_obj.updated_at = datetime.utcnow()
    db.session.commit()

    result: dict[str, Any] = {
        "round": _round_summary(round_obj),
        "position": insert_position,
        "added_song": _song_summary(song),
        "assets_invalidated": True,
    }
    if inspect_after:
        result["quality"] = inspect_round_package(round_id, user_id=user_id)
    return result


def suggest_replacement_songs(
    round_id: int,
    position: int,
    limit: int = 10,
    query: str | None = None,
    require_deezer_id: bool = True,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
) -> dict[str, Any]:
    """Suggest catalog songs that can replace a failed round position."""
    if limit < 1 or limit > 50:
        raise AutomationError("limit must be between 1 and 50.")

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    song_ids, index = _song_position(round_obj, position)
    original_song = db.session.get(Song, song_ids[index])
    excluded_ids = set(song_ids)

    song_query = Song.query.filter(~Song.id.in_(excluded_ids))
    if require_deezer_id:
        song_query = song_query.filter(Song.deezer_id.isnot(None))
    if query:
        pattern = f"%{query.strip()}%"
        song_query = song_query.filter(or_(Song.title.ilike(pattern), Song.artist.ilike(pattern)))

    candidates = song_query.limit(250).all()

    def _candidate_score(song: Song) -> tuple[int, int, int, int, str, str]:
        genre_match = 1 if original_song and song.genre and song.genre == original_song.genre else 0
        original_year = original_song.year if original_song and original_song.year else None
        year_distance = abs(song.year - original_year) if song.year and original_year else 9999
        preview_signal = 1 if song.preview_url or song.deezer_preview_url or song.spotify_preview_url else 0
        used_count = song.used_count or 0
        return (-genre_match, year_distance, -preview_signal, used_count, song.artist or "", song.title or "")

    suggestions = []
    for song in sorted(candidates, key=_candidate_score):
        suggestion = _song_summary(song)
        suggestion["same_genre"] = bool(original_song and song.genre and song.genre == original_song.genre)
        suggestion["year_distance"] = (
            abs(song.year - original_song.year)
            if original_song and song.year and original_song.year
            else None
        )
        suggestion["preview_check"] = {
            "required": verify_previews,
            "ok": None,
            "duration_seconds": None,
            "issue_code": None,
        }
        suggestions.append(suggestion)

    if verify_previews:
        verified = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for suggestion in suggestions:
                song = db.session.get(Song, suggestion["id"])
                preview_url, audio, issue = _download_preview_audio(song, temp_dir)
                suggestion["preview_url"] = preview_url or suggestion["preview_url"]
                if issue:
                    suggestion["preview_check"]["ok"] = False
                    suggestion["preview_check"]["issue_code"] = issue["code"]
                    continue
                duration_seconds = len(audio) / 1000 if audio else 0
                suggestion["preview_check"]["duration_seconds"] = round(duration_seconds, 3)
                suggestion["preview_check"]["ok"] = duration_seconds >= min_preview_seconds
                if duration_seconds < min_preview_seconds:
                    suggestion["preview_check"]["issue_code"] = "preview_too_short"
                    continue
                verified.append(suggestion)
                if len(verified) >= limit:
                    break
        suggestions = verified

    return {
        "round_id": round_id,
        "round_name": round_obj.name,
        "position": position,
        "original_song": _song_summary(original_song) if original_song else {"id": song_ids[index]},
        "count": min(len(suggestions), limit),
        "suggestions": suggestions[:limit],
        "filters": {
            "query": query,
            "require_deezer_id": require_deezer_id,
            "verify_previews": verify_previews,
            "excluded_song_ids": sorted(excluded_ids),
        },
    }


def suggest_additional_songs(
    round_id: int,
    limit: int = 10,
    query: str | None = None,
    require_deezer_id: bool = True,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
) -> dict[str, Any]:
    """Suggest catalog songs that can be added to an incomplete round."""
    if limit < 1 or limit > 50:
        raise AutomationError("limit must be between 1 and 50.")

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    excluded_ids = set(_round_song_ids(round_obj))
    song_query = Song.query.filter(~Song.id.in_(excluded_ids))
    if require_deezer_id:
        song_query = song_query.filter(Song.deezer_id.isnot(None))
    if query:
        pattern = f"%{query.strip()}%"
        song_query = song_query.filter(or_(Song.title.ilike(pattern), Song.artist.ilike(pattern)))

    candidates = song_query.limit(250).all()

    def _candidate_score(song: Song) -> tuple[int, int, str, str]:
        preview_signal = 1 if song.preview_url or song.deezer_preview_url or song.spotify_preview_url else 0
        used_count = song.used_count or 0
        return (-preview_signal, used_count, song.artist or "", song.title or "")

    suggestions = []
    for song in sorted(candidates, key=_candidate_score):
        suggestion = _song_summary(song)
        suggestion["preview_check"] = {
            "required": verify_previews,
            "ok": None,
            "duration_seconds": None,
            "issue_code": None,
        }
        suggestions.append(suggestion)

    if verify_previews:
        verified = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for suggestion in suggestions:
                song = db.session.get(Song, suggestion["id"])
                preview_url, audio, issue = _download_preview_audio(song, temp_dir)
                suggestion["preview_url"] = preview_url or suggestion["preview_url"]
                if issue:
                    suggestion["preview_check"]["ok"] = False
                    suggestion["preview_check"]["issue_code"] = issue["code"]
                    continue
                duration_seconds = len(audio) / 1000 if audio else 0
                suggestion["preview_check"]["duration_seconds"] = round(duration_seconds, 3)
                suggestion["preview_check"]["ok"] = duration_seconds >= min_preview_seconds
                if duration_seconds < min_preview_seconds:
                    suggestion["preview_check"]["issue_code"] = "preview_too_short"
                    continue
                verified.append(suggestion)
                if len(verified) >= limit:
                    break
        suggestions = verified

    return {
        "round_id": round_id,
        "round_name": round_obj.name,
        "count": min(len(suggestions), limit),
        "suggestions": suggestions[:limit],
        "filters": {
            "query": query,
            "require_deezer_id": require_deezer_id,
            "verify_previews": verify_previews,
            "excluded_song_ids": sorted(excluded_ids),
        },
    }


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
    source_positions = imported.get("result", {}).get("playlist_positions") or []
    if source_positions:
        position_map = _playlist_position_map([], count, source_positions=source_positions)
        song_ids = [
            item["song_id"]
            for item in position_map
            if item["resolved"] and item.get("song_id") is not None
        ]
    elif service_name.lower() == "spotify":
        song_ids = _spotify_playlist_song_ids(playlist_id, count, user_id)
        position_map = _playlist_position_map(song_ids, count)
    else:
        song_ids = imported.get("result", {}).get(
            "imported_song_ids"
        ) or _deezer_playlist_song_ids(playlist_id, count)
        position_map = _playlist_position_map(song_ids, count)
    if not song_ids and not position_map:
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
                "resolved_positions": position_map,
                "missing_positions": [
                    item["position"]
                    for item in position_map
                    if not item["resolved"]
                ],
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
    return {
        "import": imported,
        "round": round_result["round"],
        "resolved_positions": position_map,
    }


def generate_round_pdf(round_id: int) -> dict[str, Any]:
    from musicround.routes.rounds import generate_pdf

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    try:
        require_round_artifact_storage(include_mp3=False, include_pdf=True)
    except RuntimeError as exc:
        current_app.logger.error("PDF generation blocked by unhealthy artifact storage: %s", exc)
        raise AutomationError(
            AUTOMATION_STORAGE_ERROR,
            details=check_round_artifact_storage(include_mp3=False),
        ) from exc
    pdf_data = generate_pdf(round_id)
    if isinstance(pdf_data, str):
        raise AutomationError(pdf_data)
    round_obj.pdf_generated = True
    round_obj.last_generated_at = datetime.utcnow()
    db.session.commit()
    path = os.path.join(round_pdf_dir(), f"round_{round_id}.pdf")
    return {"round_id": round_id, "path": path, "bytes": len(pdf_data)}


def generate_round_mp3(round_id: int, user_id: int | None = None) -> dict[str, Any]:
    from musicround.routes.rounds import round_mp3

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    user = _find_user(user_id)
    try:
        require_round_artifact_storage(include_mp3=True, include_pdf=False)
    except RuntimeError as exc:
        current_app.logger.error("MP3 generation blocked by unhealthy artifact storage: %s", exc)
        raise AutomationError(
            AUTOMATION_STORAGE_ERROR,
            details=check_round_artifact_storage(include_pdf=False),
        ) from exc
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

    path = os.path.join(round_mp3_dir(), f"round_{round_id}.mp3")
    if not os.path.exists(path):
        current_app.logger.error("MP3 generation for round %s did not create %s", round_id, path)
        raise AutomationError(AUTOMATION_MP3_GENERATION_ERROR)
    return {"round_id": round_id, "path": path, "bytes": os.path.getsize(path)}


def generate_round_assets(
    round_id: int,
    user_id: int | None = None,
    include_pdf: bool = True,
    include_mp3: bool = True,
) -> dict[str, Any]:
    """Generate requested round assets."""
    try:
        require_round_artifact_storage(include_mp3=include_mp3, include_pdf=include_pdf)
    except RuntimeError as exc:
        current_app.logger.error("Round asset generation blocked by unhealthy artifact storage: %s", exc)
        raise AutomationError(
            AUTOMATION_STORAGE_ERROR,
            details=check_round_artifact_storage(include_mp3=include_mp3, include_pdf=include_pdf),
        ) from exc
    assets: dict[str, Any] = {
        "round_id": round_id,
        "review_url_path": f"/rounds/{round_id}/bundle-review",
    }
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
    severity: str = "error",
) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "severity": severity, "message": message}
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


def _blocking_quality_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [issue for issue in issues if issue.get("severity", "error") != "warning"]


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
        current_app.logger.error(
            "Deezer metadata lookup failed for song %s (%s): %s",
            song.id,
            song.deezer_id,
            exc,
            exc_info=True,
        )
        return None, None, _quality_issue(
            "deezer_lookup_failed",
            f"Could not fetch Deezer metadata for {song.artist} - {song.title}. Check the server logs.",
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
        current_app.logger.error(
            "Preview download/decode failed for song %s (%s): %s",
            song.id,
            song.deezer_id,
            exc,
            exc_info=True,
        )
        return preview_url, None, _quality_issue(
            "preview_download_failed",
            f"Could not download or decode preview for {song.artist} - {song.title}. Replace this song or retry later.",
            song,
            {"preview_url_present": bool(preview_url)},
        )


def _selected_track_hint_scripts(round_id: int) -> list[RoundAudioScript]:
    """Return selected generated per-track hints in playback order."""
    return (
        RoundAudioScript.query.filter_by(
            round_id=round_id,
            script_type="track_hint",
            selected=True,
        )
        .filter(RoundAudioScript.generated_mp3_path.isnot(None))
        .order_by(RoundAudioScript.cue_position.asc(), RoundAudioScript.id.asc())
        .all()
    )


def _round_audio_components(
    user: User, song_count: int, round_id: int | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    components: dict[str, Any] = {
        "custom_audio_ms": {},
        "number_audio_ms": [],
        "hint_audio_ms": {},
    }

    for mp3_type in ("intro", "replay", "outro"):
        try:
            segment = AudioSegment.from_mp3(get_mp3_path(user, mp3_type))
            components["custom_audio_ms"][mp3_type] = len(segment)
        except Exception as exc:
            current_app.logger.error(
                "Could not load %s audio for duration validation: %s",
                mp3_type,
                exc,
                exc_info=True,
            )
            issues.append(
                _quality_issue(
                    "custom_audio_failed",
                    f"Could not load {mp3_type} audio for duration validation. Check the server logs.",
                )
            )

    for index in range(song_count):
        path = os.path.join(current_app.root_path, "static", "audio", f"{index + 1}.mp3")
        try:
            components["number_audio_ms"].append(len(AudioSegment.from_mp3(path)))
        except Exception as exc:
            current_app.logger.error(
                "Could not load number announcement %s for duration validation: %s",
                index + 1,
                exc,
                exc_info=True,
            )
            issues.append(
                _quality_issue(
                    "number_audio_failed",
                    f"Could not load number announcement {index + 1}. Check the server logs.",
                )
            )

    if round_id is not None:
        for script in _selected_track_hint_scripts(round_id):
            if not script.cue_position:
                continue
            path = app_data_path(script.generated_mp3_path)
            try:
                components["hint_audio_ms"][script.cue_position] = len(AudioSegment.from_mp3(path))
            except Exception as exc:
                current_app.logger.error(
                    "Could not load hint audio for round %s position %s: %s",
                    round_id,
                    script.cue_position,
                    exc,
                    exc_info=True,
                )
                issues.append(
                    _quality_issue(
                        "track_hint_audio_failed",
                        f"Could not load hint audio for position {script.cue_position}. Check the server logs.",
                    )
                )

    return components, issues


def _round_repair_report(quality: dict[str, Any]) -> dict[str, Any]:
    round_label = quality.get("round_name") or f"Round {quality.get('round_id')}"
    status = quality.get("status", "blocked")
    ok = bool(quality.get("ok"))
    issues = quality.get("issues", [])
    blocking_issues = _blocking_quality_issues(issues)
    warning_issues = [issue for issue in issues if issue.get("severity") == "warning"]
    remediation = quality.get("remediation", [])
    preview_checks = quality.get("preview_checks", [])

    if ok:
        headline = f"{round_label} is ready to send."
        warning_suffix = (
            f" {len(warning_issues)} warning(s) should be reviewed."
            if warning_issues
            else ""
        )
        summary = (
            f"{quality.get('resolved_song_count', quality.get('song_count', 0))} songs, "
            "all blocking preview and generated asset checks passed the package gate."
            f"{warning_suffix}"
        )
    else:
        headline = f"{round_label} is blocked: {status}."
        summary = (
            f"{len(blocking_issues)} blocker(s) found. Expected "
            f"{quality.get('expected_song_count')} songs, found "
            f"{quality.get('resolved_song_count', quality.get('song_count'))} playable songs."
        )

    blockers: list[str] = []
    warnings: list[str] = []
    for issue in blocking_issues:
        song = issue.get("song")
        prefix = ""
        if song:
            prefix = f"{song.get('artist')} - {song.get('title')}: "
        blockers.append(f"{prefix}{issue.get('message')}")
    for issue in warning_issues:
        song = issue.get("song")
        prefix = ""
        if song:
            prefix = f"{song.get('artist')} - {song.get('title')}: "
        warnings.append(f"{prefix}{issue.get('message')}")

    failed_positions = []
    for check in preview_checks:
        if check.get("ok"):
            continue
        failed_positions.append(
            {
                "position": check.get("position"),
                "song_id": check.get("song_id"),
                "artist": check.get("artist"),
                "title": check.get("title"),
                "issue_code": check.get("issue_code"),
                "message": (
                    f"Position {check.get('position')}: "
                    f"{check.get('artist')} - {check.get('title')}"
                ),
            }
        )

    actions = []
    seen_actions = set()
    for item in remediation:
        action = item.get("action")
        if action == "replace_position":
            text = (
                f"Replace position {item.get('position')} "
                f"({item.get('artist')} - {item.get('title')}) and regenerate assets."
            )
        elif action == "add_missing_track":
            text = (
                f"Add {item.get('expected_song_count') - item.get('actual_song_count')} "
                "missing song(s), then regenerate assets."
            )
        elif action == "remove_extra_track":
            text = "Remove extra song(s), then regenerate assets."
        elif action == "replace_unresolved_positions":
            positions = ", ".join(str(position) for position in item.get("positions", []))
            text = f"Replace unresolved position(s) {positions}, then regenerate assets."
        elif action == "regenerate_assets":
            text = "Regenerate PDF and MP3, then rerun the package inspection."
        else:
            text = item.get("message") or f"Run remediation action {action}."
        if text not in seen_actions:
            seen_actions.add(text)
            actions.append({"action": action, "message": text, "details": item})

    if status == "needs_substitution" and failed_positions:
        next_step = (
            "Call suggest_replacement_songs for each failed position, then "
            "replace_round_song, regenerate assets, and rerun inspect_round_package."
        )
    elif status == "needs_more_songs":
        next_step = (
            "Complete the round to exactly the expected number of playable songs, "
            "regenerate assets, and rerun inspect_round_package."
        )
    elif status == "render_failed":
        next_step = "Regenerate assets or fix the renderer inputs, then rerun inspect_round_package."
    elif ok:
        next_step = "Send the round email."
    else:
        next_step = "Resolve the listed blockers and rerun inspect_round_package."

    markdown_lines = [f"# {headline}", "", summary]
    if blockers:
        markdown_lines.extend(["", "## Blockers"])
        markdown_lines.extend(f"- {blocker}" for blocker in blockers)
    if warnings:
        markdown_lines.extend(["", "## Warnings"])
        markdown_lines.extend(f"- {warning}" for warning in warnings)
    if actions:
        markdown_lines.extend(["", "## Repair actions"])
        markdown_lines.extend(f"- {action['message']}" for action in actions)
    markdown_lines.extend(["", "## Next step", next_step])

    return {
        "headline": headline,
        "summary": summary,
        "status": status,
        "ok": ok,
        "blockers": blockers,
        "warnings": warnings,
        "failed_positions": failed_positions,
        "actions": actions,
        "next_step": next_step,
        "markdown": "\n".join(markdown_lines),
    }


def inspect_round_package(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Validate a generated round bundle before it is allowed to leave by email."""
    if expected_song_count < 1:
        raise AutomationError("expected_song_count must be at least 1.")
    if not math.isfinite(min_preview_seconds) or not math.isfinite(max_preview_seconds):
        raise AutomationError("preview duration limits must be finite.")
    if min_preview_seconds < 0 or max_preview_seconds < 0:
        raise AutomationError("preview duration limits must not be negative.")
    if min_preview_seconds > max_preview_seconds:
        raise AutomationError("min_preview_seconds must not exceed max_preview_seconds.")
    if not math.isfinite(duration_tolerance_seconds):
        raise AutomationError("duration_tolerance_seconds must be finite.")
    if duration_tolerance_seconds < 0:
        raise AutomationError("duration_tolerance_seconds must not be negative.")

    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    user = _find_user(user_id)
    song_ids = _round_song_ids(round_obj)
    songs_by_id = {
        song.id: song
        for song in Song.query.filter(Song.id.in_(song_ids)).all()
    }
    songs = [songs_by_id[song_id] for song_id in song_ids if song_id in songs_by_id]
    song_slots = [
        {
            "position": index,
            "stored_song_id": song_id,
            "resolved": song_id in songs_by_id,
            "song": _song_summary(songs_by_id[song_id]) if song_id in songs_by_id else None,
        }
        for index, song_id in enumerate(song_ids, start=1)
    ]
    issues: list[dict[str, Any]] = []
    preview_checks: list[dict[str, Any]] = []
    remediation: list[dict[str, Any]] = []
    total_preview_ms = 0
    preview_ms_by_position: dict[int, int] = {}
    service_health = {
        "artifact_storage": artifact_storage_service_health(),
        "spotify": spotify_service_health(user),
        "dropbox": dropbox_service_health(user),
    }
    storage = service_health["artifact_storage"]
    for issue in storage["issues"]:
        issues.append(issue)
        remediation.append(
            {
                "action": "repair_storage",
                "issue_code": issue["code"],
                "message": issue["message"],
                "hint": issue["details"].get("hint"),
                "path": issue["details"].get("path"),
            }
        )

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
        for slot in song_slots:
            song = songs_by_id.get(slot["stored_song_id"])
            if not song:
                continue
            index = slot["position"]
            preview_url, audio, issue = _download_preview_audio(song, temp_dir)
            check = {
                "position": index,
                "stored_song_id": slot["stored_song_id"],
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
                preview_ms_by_position[index] = len(audio)
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

    components, component_issues = _round_audio_components(user, len(songs), round_id=round_id)
    issues.extend(component_issues)
    expected_ms = None
    if not component_issues:
        custom_audio_ms = components["custom_audio_ms"]
        expected_ms = (
            custom_audio_ms.get("intro", 0)
            + custom_audio_ms.get("replay", 0)
            + custom_audio_ms.get("outro", 0)
            + 2 * sum(components["number_audio_ms"])
            + sum((components.get("hint_audio_ms") or {}).values())
            + 2 * total_preview_ms
        )
        track_slot_ms = []
        number_audio_ms = components.get("number_audio_ms") or []
        hint_audio_ms = components.get("hint_audio_ms") or {}
        for position, preview_ms in preview_ms_by_position.items():
            number_ms = number_audio_ms[position - 1] if position - 1 < len(number_audio_ms) else 0
            track_slot_ms.append((2 * preview_ms) + (2 * number_ms) + hint_audio_ms.get(position, 0))
        if track_slot_ms:
            components["expected_track_slot_seconds"] = [
                round(value / 1000, 3) for value in track_slot_ms
            ]
            components["minimum_expected_track_slot_seconds"] = round(min(track_slot_ms) / 1000, 3)

    pdf_result: dict[str, Any] | None = None
    mp3_result: dict[str, Any] | None = None
    try:
        pdf_result = inspect_pdf_quality(round_id=round_id)
        for warning in pdf_result.get("warnings", []):
            issues.append(_quality_issue("pdf_quality_warning", warning, severity="warning"))
    except Exception as exc:
        current_app.logger.error("PDF inspection failed for round %s: %s", round_id, exc, exc_info=True)
        issues.append(_quality_issue("pdf_inspection_failed", AUTOMATION_PDF_INSPECTION_ERROR))

    try:
        mp3_result = inspect_mp3_quality(round_id=round_id)
        for warning in mp3_result.get("warnings", []):
            issues.append(_quality_issue("mp3_quality_warning", warning, severity="warning"))
    except Exception as exc:
        current_app.logger.error("MP3 inspection failed for round %s: %s", round_id, exc, exc_info=True)
        issues.append(_quality_issue("mp3_inspection_failed", AUTOMATION_MP3_INSPECTION_ERROR))

    if expected_ms is not None and mp3_result and mp3_result.get("duration_seconds") is not None:
        expected_seconds = expected_ms / 1000
        actual_seconds = float(mp3_result["duration_seconds"])
        delta_seconds = actual_seconds - expected_seconds
        if abs(delta_seconds) > duration_tolerance_seconds:
            minimum_slot_seconds = components.get("minimum_expected_track_slot_seconds")
            missing_slot_threshold = (
                max(
                    duration_tolerance_seconds,
                    MIN_MP3_DURATION_MISMATCH_BLOCK_SECONDS,
                    minimum_slot_seconds * MP3_DURATION_MISSING_SLOT_FACTOR,
                )
                if minimum_slot_seconds
                else max(duration_tolerance_seconds, MIN_MP3_DURATION_MISMATCH_BLOCK_SECONDS)
            )
            severity = "error" if abs(delta_seconds) >= missing_slot_threshold else "warning"
            issue = _quality_issue(
                "round_mp3_duration_mismatch",
                (
                    f"Generated MP3 is {actual_seconds:.1f}s, expected about "
                    f"{expected_seconds:.1f}s from intro, replay, outro, number "
                    "announcements, optional hints, and two plays of every preview."
                ),
                details={
                    "actual_seconds": round(actual_seconds, 3),
                    "expected_seconds": round(expected_seconds, 3),
                    "delta_seconds": round(delta_seconds, 3),
                    "tolerance_seconds": duration_tolerance_seconds,
                    "blocking_threshold_seconds": round(missing_slot_threshold, 3),
                },
                severity=severity,
            )
            issues.append(issue)
            remediation.append(
                {
                    "action": "regenerate_assets",
                    "issue_code": issue["code"],
                    "message": issue["message"],
                }
            )

    blocking_issues = _blocking_quality_issues(issues)
    blocking_issue_codes = {issue["code"] for issue in blocking_issues}
    if not blocking_issues:
        status = "ok"
    elif blocking_issue_codes & {"actual_song_count_mismatch", "resolved_song_count_mismatch"}:
        status = "needs_more_songs" if len(songs) < expected_song_count else "blocked"
    elif blocking_issue_codes & {
        "missing_deezer_id",
        "missing_preview_url",
        "preview_too_short",
        "preview_too_long",
        "preview_download_failed",
    }:
        status = "needs_substitution"
    elif blocking_issue_codes & {
        "artifact_storage_missing",
        "artifact_storage_not_directory",
        "artifact_storage_not_writable",
    }:
        status = "storage_unhealthy"
    elif blocking_issue_codes & {"pdf_inspection_failed", "mp3_inspection_failed", "round_mp3_duration_mismatch"}:
        status = "render_failed"
    else:
        status = "blocked"

    result = {
        "round_id": round_id,
        "round_name": round_obj.name,
        "status": status,
        "expected_song_count": expected_song_count,
        "actual_song_count": actual_song_count,
        "resolved_song_count": resolved_song_count,
        "song_count": len(songs),
        "song_slots": song_slots,
        "preview_checks": preview_checks,
        "components": components,
        "storage": storage,
        "service_health": service_health,
        "expected_duration_seconds": None if expected_ms is None else round(expected_ms / 1000, 3),
        "pdf": pdf_result,
        "mp3": mp3_result,
        "issues": issues,
        "warnings": [issue for issue in issues if issue.get("severity") == "warning"],
        "blocking_issue_count": len(blocking_issues),
        "hints": [issue["message"] for issue in blocking_issues],
        "remediation": remediation,
        "ok": not blocking_issues,
    }
    result["report"] = _round_repair_report(result)
    return result


def round_repair_report(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Return the package quality payload plus a human-readable repair report."""
    quality = inspect_round_package(
        round_id=round_id,
        user_id=user_id,
        expected_song_count=expected_song_count,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )
    return {"quality": quality, "report": quality["report"]}


def _normalize_round_ids(round_ids: Iterable[int]) -> list[int]:
    normalized_round_ids: list[int] = []
    seen_round_ids: set[int] = set()
    for value in round_ids or []:
        try:
            round_id = int(value)
        except (TypeError, ValueError) as exc:
            raise AutomationError("round_ids must contain only integer round IDs.") from exc
        if round_id < 1:
            raise AutomationError("round_ids must contain positive round IDs.")
        if round_id in seen_round_ids:
            continue
        normalized_round_ids.append(round_id)
        seen_round_ids.add(round_id)

    if not normalized_round_ids:
        raise AutomationError("round_ids must contain at least one round ID.")
    if len(normalized_round_ids) > 50:
        raise AutomationError("round_ids must contain at most 50 round IDs.")
    return normalized_round_ids


def inspect_round_package_batch(
    round_ids: Iterable[int],
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Inspect multiple round packages without aborting on one bad round."""
    normalized_round_ids = _normalize_round_ids(round_ids)

    rounds: list[dict[str, Any]] = []
    ok_count = 0
    warning_count = 0
    blocked_count = 0
    error_count = 0
    needs_repair_count = 0

    for round_id in normalized_round_ids:
        try:
            quality = inspect_round_package(
                round_id=round_id,
                user_id=user_id,
                expected_song_count=expected_song_count,
                min_preview_seconds=min_preview_seconds,
                max_preview_seconds=max_preview_seconds,
                duration_tolerance_seconds=duration_tolerance_seconds,
            )
        except AutomationError as exc:
            error_count += 1
            rounds.append(
                {
                    "round_id": round_id,
                    "ok": False,
                    "status": "error",
                    "error": str(exc),
                    "details": exc.details,
                    "ready_to_send": False,
                    "needs_repair": True,
                }
            )
            continue

        report = quality.get("report") or _round_repair_report(quality)
        round_ok = bool(quality.get("ok"))
        warnings = quality.get("warnings") or []
        blocking_issue_count = int(quality.get("blocking_issue_count") or 0)
        if round_ok:
            ok_count += 1
        if warnings:
            warning_count += 1
        if blocking_issue_count:
            blocked_count += 1
        if not round_ok:
            needs_repair_count += 1
        rounds.append(
            {
                "round_id": round_id,
                "round_name": quality.get("round_name"),
                "ok": round_ok,
                "status": quality.get("status"),
                "ready_to_send": round_ok,
                "needs_repair": not round_ok,
                "expected_song_count": quality.get("expected_song_count"),
                "actual_song_count": quality.get("actual_song_count"),
                "resolved_song_count": quality.get("resolved_song_count"),
                "blocking_issue_count": blocking_issue_count,
                "warning_count": len(warnings),
                "failed_positions": report.get("failed_positions") or [],
                "repair_actions": report.get("actions") or [],
                "next_step": report.get("next_step"),
                "headline": report.get("headline"),
                "summary": report.get("summary"),
            }
        )

    status = "ok"
    if error_count:
        status = "error"
    elif needs_repair_count:
        status = "needs_repair"
    elif warning_count:
        status = "warning"

    return {
        "ok": needs_repair_count == 0 and error_count == 0,
        "status": status,
        "round_ids": normalized_round_ids,
        "count": len(normalized_round_ids),
        "ok_count": ok_count,
        "warning_count": warning_count,
        "blocked_count": blocked_count,
        "error_count": error_count,
        "needs_repair_count": needs_repair_count,
        "rounds": rounds,
        "sendable_round_ids": [
            item["round_id"] for item in rounds if item.get("ready_to_send")
        ],
        "repair_round_ids": [
            item["round_id"] for item in rounds if item.get("needs_repair")
        ],
        "hints": [
            "Send only rounds listed in sendable_round_ids.",
            "Repair each repair_round_ids entry, regenerate assets, then rerun this batch audit.",
        ],
    }


def round_repair_plan(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    replacement_limit: int = 5,
    additional_limit: int = 10,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Return a non-mutating repair plan with candidate songs for a blocked round."""
    if replacement_limit < 1 or replacement_limit > 50:
        raise AutomationError("replacement_limit must be between 1 and 50.")
    if additional_limit < 1 or additional_limit > 50:
        raise AutomationError("additional_limit must be between 1 and 50.")

    repair = round_repair_report(
        round_id=round_id,
        user_id=user_id,
        expected_song_count=expected_song_count,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )
    quality = repair["quality"]
    report = repair["report"]

    failed_by_position: dict[int, dict[str, Any]] = {}
    for item in report.get("failed_positions") or []:
        try:
            position = int(item.get("position"))
        except (TypeError, ValueError):
            continue
        failed_by_position[position] = item

    for action in report.get("actions") or []:
        details = action.get("details") or {}
        if details.get("action") != "replace_unresolved_positions":
            continue
        for raw_position in details.get("positions") or []:
            try:
                position = int(raw_position)
            except (TypeError, ValueError):
                continue
            failed_by_position.setdefault(
                position,
                {
                    "position": position,
                    "issue_code": "unresolved_song",
                    "message": f"Position {position}: unresolved stored song ID.",
                },
            )

    replacement_positions: list[dict[str, Any]] = []
    for position in sorted(failed_by_position):
        failed_song = failed_by_position[position]
        try:
            suggestions = suggest_replacement_songs(
                round_id=round_id,
                position=position,
                limit=replacement_limit,
                verify_previews=verify_previews,
                min_preview_seconds=min_preview_seconds,
            )
            replacement_positions.append(
                {
                    "position": position,
                    "failed_song": failed_song,
                    "count": suggestions["count"],
                    "suggestions": suggestions["suggestions"],
                }
            )
        except AutomationError as exc:
            replacement_positions.append(
                {
                    "position": position,
                    "failed_song": failed_song,
                    "count": 0,
                    "suggestions": [],
                    "error": str(exc),
                }
            )

    actual_song_count = int(quality.get("actual_song_count") or 0)
    missing_song_count = max(0, expected_song_count - actual_song_count)
    additional_songs = None
    if missing_song_count:
        additional_songs = suggest_additional_songs(
            round_id=round_id,
            limit=max(additional_limit, missing_song_count),
            verify_previews=verify_previews,
            min_preview_seconds=min_preview_seconds,
        )

    next_actions = []
    if replacement_positions:
        next_actions.append("replace_failed_positions")
    if missing_song_count:
        next_actions.append("add_missing_songs")
    if next_actions:
        next_actions.append("regenerate_assets")
        next_actions.append("inspect_round_package")

    return {
        "round_id": round_id,
        "round_name": quality.get("round_name"),
        "ok": bool(quality.get("ok")),
        "status": quality.get("status"),
        "quality": quality,
        "report": report,
        "replacement_positions": replacement_positions,
        "missing_song_count": missing_song_count,
        "additional_songs": additional_songs,
        "next_actions": next_actions or ["send_round_email"],
        "hints": [
            "This plan is read-only; apply replacements/additions explicitly.",
            "After changes, regenerate assets and rerun inspect_round_package before sending.",
        ],
    }


def round_repair_plan_batch(
    round_ids: Iterable[int],
    user_id: int | None = None,
    expected_song_count: int = 8,
    replacement_limit: int = 5,
    additional_limit: int = 10,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Build non-mutating repair plans for several rounds in one agent call."""
    normalized_round_ids = _normalize_round_ids(round_ids)
    plans: list[dict[str, Any]] = []
    ready_count = 0
    repair_count = 0
    error_count = 0

    for round_id in normalized_round_ids:
        try:
            plan = round_repair_plan(
                round_id=round_id,
                user_id=user_id,
                expected_song_count=expected_song_count,
                replacement_limit=replacement_limit,
                additional_limit=additional_limit,
                verify_previews=verify_previews,
                min_preview_seconds=min_preview_seconds,
                max_preview_seconds=max_preview_seconds,
                duration_tolerance_seconds=duration_tolerance_seconds,
            )
        except AutomationError as exc:
            error_count += 1
            plans.append(
                {
                    "round_id": round_id,
                    "ok": False,
                    "status": "error",
                    "error": str(exc),
                    "details": exc.details,
                    "needs_repair": True,
                }
            )
            continue

        needs_repair = not bool(plan.get("ok"))
        if needs_repair:
            repair_count += 1
        else:
            ready_count += 1
        plan["needs_repair"] = needs_repair
        plans.append(plan)

    status = "ok"
    if error_count:
        status = "error"
    elif repair_count:
        status = "needs_repair"

    return {
        "ok": repair_count == 0 and error_count == 0,
        "status": status,
        "round_ids": normalized_round_ids,
        "count": len(normalized_round_ids),
        "ready_count": ready_count,
        "repair_count": repair_count,
        "error_count": error_count,
        "plans": plans,
        "ready_round_ids": [
            item["round_id"] for item in plans if not item.get("needs_repair")
        ],
        "repair_round_ids": [
            item["round_id"] for item in plans if item.get("needs_repair")
        ],
        "hints": [
            "Apply only explicit replacement/addition actions from each plan.",
            "After repairs, regenerate assets and rerun inspect_round_package_batch.",
        ],
    }


def _import_job_summary(record: ImportJobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "service_name": record.service_name,
        "item_type": record.item_type,
        "item_id": record.item_id,
        "item_url": record.item_url,
        "priority": record.priority,
        "user_id": record.user_id,
        "status": record.status,
        "created_at": _datetime_payload(record.created_at),
        "started_at": _datetime_payload(record.started_at),
        "completed_at": _datetime_payload(record.completed_at),
        "duration_seconds": record.duration,
        "imported_count": record.imported_count or 0,
        "skipped_count": record.skipped_count or 0,
        "attempt_count": record.attempt_count or 0,
        "max_attempts": record.max_attempts or 1,
        "error_message": record.error_message,
        **import_job_status_metadata(record),
    }


def _import_job_result_metadata(record: ImportJobRecord) -> dict[str, Any]:
    raw_metadata = getattr(record, "result_metadata", None)
    if not raw_metadata:
        return {}
    if isinstance(raw_metadata, dict):
        return raw_metadata
    try:
        parsed = json.loads(raw_metadata)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _import_job_failed_position_hints(record: ImportJobRecord) -> list[dict[str, Any]]:
    metadata = _import_job_result_metadata(record)
    positions = metadata.get("playlist_positions")
    if not isinstance(positions, list):
        return []

    failed_positions: list[dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict) or item.get("status") == "resolved":
            continue
        failed_positions.append(
            {
                "position": item.get("position"),
                "artist": item.get("artist"),
                "title": item.get("title"),
                "song_id": item.get("song_id"),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "message": (
                    f"Review playlist position {item.get('position')}: "
                    f"{item.get('artist') or 'Unknown artist'} - "
                    f"{item.get('title') or 'Unknown title'} "
                    f"({item.get('reason') or item.get('status') or 'not resolved'})."
                ),
            }
        )
    return failed_positions


def import_job_status_metadata(record: ImportJobRecord) -> dict[str, Any]:
    """Return repair-oriented metadata for import progress views and MCP clients."""
    status = record.status or "pending"
    attempts = record.attempt_count or 0
    max_attempts = record.max_attempts or 1
    imported_count = record.imported_count or 0
    skipped_count = record.skipped_count or 0
    retryable = status in {"failed", "dead_letter"}
    terminal = status in {"completed", "failed", "dead_letter"}
    progress_percent_by_status = {
        "pending": 5,
        "processing": 50,
        "completed": 100,
        "failed": 100,
        "dead_letter": 100,
    }
    progress_label_by_status = {
        "pending": "Waiting in queue",
        "processing": "Import running",
        "completed": "Import completed",
        "failed": "Retryable failure",
        "dead_letter": "Manual review required",
    }
    hints: list[str] = []
    if status == "pending":
        hints.append("This import is queued and will start when earlier jobs finish.")
    elif status == "processing":
        hints.append("Poll this job until it completes or becomes retryable.")
    elif status == "completed":
        if skipped_count:
            hints.append(f"Review {skipped_count} skipped item(s) before using the imported catalog blindly.")
        else:
            hints.append("No repair action is needed for this completed import.")
    elif status == "failed":
        hints.append("Retry this job after checking the source URL and provider token health.")
    elif status == "dead_letter":
        hints.append("This job exhausted automatic retries and needs manual review before retrying.")
    if retryable and attempts >= max_attempts:
        hints.append("Reset attempts when retrying if the underlying provider issue has been fixed.")
    if retryable and not record.error_message:
        hints.append("No detailed failure message was recorded; inspect worker logs if retry fails again.")
    if imported_count:
        hints.append(f"{imported_count} item(s) imported before this status was recorded.")
    failed_position_hints = _import_job_failed_position_hints(record)
    if failed_position_hints:
        hints.append("Review failed_position_hints for playlist positions that need replacement or retry.")

    return {
        "retryable": retryable,
        "terminal": terminal,
        "progress_percent": progress_percent_by_status.get(status, 0),
        "progress_label": progress_label_by_status.get(status, status.replace("_", " ").title()),
        "repair_hints": hints,
        "failed_position_hints": failed_position_hints,
    }


def import_progress_events(
    user_id: int | None = None,
    include_recent: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    """Return import queue and job status for polling MCP clients."""
    if limit < 1 or limit > 100:
        raise AutomationError("limit must be between 1 and 100.")

    queue = current_app.config.get("IMPORT_QUEUE")
    query = ImportJobRecord.query
    if user_id is not None:
        query = query.filter_by(user_id=user_id)

    statuses = ("pending", "processing", "completed", "failed", "dead_letter")
    stats = {
        status: query.filter_by(status=status).count()
        for status in statuses
    }
    active_jobs = (
        query.filter(ImportJobRecord.status.in_(("pending", "processing")))
        .order_by(
            ImportJobRecord.priority.asc(),
            ImportJobRecord.created_at.asc(),
            ImportJobRecord.id.asc(),
        )
        .limit(limit)
        .all()
    )

    recent_jobs = []
    if include_recent:
        recent_jobs = (
            query.order_by(
                ImportJobRecord.completed_at.desc().nullslast(),
                ImportJobRecord.created_at.desc(),
                ImportJobRecord.id.desc(),
            )
            .limit(limit)
            .all()
        )

    return {
        "ok": True,
        "queue_initialized": queue is not None,
        "queue_size": queue.qsize() if queue else None,
        "queue_snapshot": queue.snapshot() if queue else [],
        "stats": stats,
        "active_jobs": [_import_job_summary(record) for record in active_jobs],
        "recent_jobs": [_import_job_summary(record) for record in recent_jobs],
        "hints": [
            "Poll this tool while imports are active. Dead-letter jobs require manual review."
        ],
    }


def retry_import_job(job_id: int, reset_attempts: bool = False) -> dict[str, Any]:
    """Move a failed or dead-letter import job back to pending and enqueue it."""
    record = db.session.get(ImportJobRecord, job_id)
    if not record:
        raise AutomationError(f"Import job {job_id} was not found.")
    if record.status not in {"failed", "dead_letter"}:
        raise AutomationError(
            f"Import job {job_id} is {record.status}; only failed or dead_letter jobs can retry."
        )

    record.status = "pending"
    record.started_at = None
    record.completed_at = None
    record.error_message = None
    if reset_attempts:
        record.attempt_count = 0
    db.session.commit()

    queue = current_app.config.get("IMPORT_QUEUE") or current_app.config.get("import_queue")
    enqueued = False
    if queue:
        queue.enqueue_record(record)
        enqueued = True

    return {
        "retried": True,
        "enqueued": enqueued,
        "job": _import_job_summary(record),
        "hints": [] if enqueued else [
            "No in-process import queue is configured; a database-backed worker can still pick up this pending job."
        ],
    }


def _split_playlist_line(line: str) -> tuple[str | None, str | None, float, list[str]]:
    text = re.sub(r"^\s*(?:\d+[\).\-\s]+|[-*]\s+)", "", line).strip()
    text = text.strip("\"'")
    issues: list[str] = []
    confidence = 0.95

    if not text:
        return None, None, 0.0, ["empty_line"]

    spotify_match = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", text)
    deezer_match = re.search(r"deezer\.com/(?:[a-z]{2}/)?track/(\d+)", text)
    if spotify_match or deezer_match:
        issues.append("platform_track_url")
        return text, None, 0.55, issues

    for delimiter in (" - ", " – ", " — ", "\t", ";", ","):
        if delimiter in text:
            left, right = [part.strip() for part in text.split(delimiter, 1)]
            if left and right:
                return right, left, confidence, issues

    by_match = re.match(r"(.+?)\s+by\s+(.+)", text, flags=re.IGNORECASE)
    if by_match:
        return by_match.group(1).strip(), by_match.group(2).strip(), 0.85, issues

    issues.append("missing_artist")
    return text, None, 0.35, issues


def _playlist_candidate(
    line_number: int,
    raw_line: str,
    title: str | None,
    artist: str | None,
    confidence: float = 0.95,
    issues: list[str] | None = None,
) -> dict[str, Any] | None:
    title = (title or "").strip()
    artist = (artist or "").strip()
    issues = list(issues or [])
    if not title and not artist:
        return None
    if not title:
        if "missing_title" not in issues:
            issues.append("missing_title")
        confidence = min(confidence, 0.35)
    if not artist:
        if "missing_artist" not in issues:
            issues.append("missing_artist")
        confidence = min(confidence, 0.35)
    return {
        "line": line_number,
        "line_number": line_number,
        "raw": raw_line.strip(),
        "raw_line": raw_line.strip(),
        "title": title or None,
        "artist": artist or None,
        "confidence": confidence,
        "needs_review": confidence < 0.8 or bool(issues),
        "issues": issues,
    }


def _parse_headered_csv_playlist(text: str, limit: int) -> list[dict[str, Any]] | None:
    """Parse CSV-like rows only when explicit artist/title headers are present."""
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if not non_empty_lines:
        return None

    delimiter = ";" if non_empty_lines[0].count(";") > non_empty_lines[0].count(",") else ","
    header = next(csv.reader([non_empty_lines[0]], delimiter=delimiter), [])
    normalized_header = [column.strip().casefold() for column in header]
    title_headers = {"title", "song", "song title", "track", "track title"}
    artist_headers = {"artist", "artists", "artist name", "performer"}
    if not title_headers.intersection(normalized_header):
        return None
    if not artist_headers.intersection(normalized_header):
        return None

    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    fieldnames = reader.fieldnames or []
    title_field = next(field for field in fieldnames if field.strip().casefold() in title_headers)
    artist_field = next(field for field in fieldnames if field.strip().casefold() in artist_headers)
    candidates: list[dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        if len(candidates) >= limit:
            break
        raw_line = non_empty_lines[line_number - 1] if line_number - 1 < len(non_empty_lines) else ""
        candidate = _playlist_candidate(
            line_number,
            raw_line,
            row.get(title_field),
            row.get(artist_field),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def parse_text_playlist(text: str, limit: int = 100) -> dict[str, Any]:
    """Parse pasted text or CSV-like playlist rows into reviewable candidates."""
    if not text or not text.strip():
        raise AutomationError("text must not be empty.")
    if limit < 1 or limit > 500:
        raise AutomationError("limit must be between 1 and 500.")

    candidates = _parse_headered_csv_playlist(text, limit)
    if candidates is None:
        candidates = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            if len(candidates) >= limit:
                break
            title, artist, confidence, issues = _split_playlist_line(raw_line)
            candidate = _playlist_candidate(line_number, raw_line, title, artist, confidence, issues)
            if candidate:
                candidates.append(candidate)

    low_confidence = [candidate for candidate in candidates if candidate["needs_review"]]

    return {
        "count": len(candidates),
        "candidates": candidates,
        "low_confidence_count": len(low_confidence),
        "low_confidence": low_confidence,
        "ready_for_import": bool(candidates) and not low_confidence,
        "hints": [
            "Review low-confidence rows before importing or creating a round.",
            "Preferred format is 'Artist - Title' with one song per line.",
        ],
    }


def _catalog_match_for_candidate(candidate: dict[str, Any]) -> Song | None:
    title = (candidate.get("title") or "").strip()
    artist = (candidate.get("artist") or "").strip()
    if not title or not artist:
        return None
    return (
        Song.query.filter(Song.title.ilike(title), Song.artist.ilike(artist))
        .order_by(Song.used_count.asc(), Song.id.asc())
        .first()
    )


def resolve_text_playlist(
    text: str,
    limit: int = 100,
    min_confidence: float = 0.8,
) -> dict[str, Any]:
    """Parse a text playlist and resolve confident rows against the catalog."""
    parsed = parse_text_playlist(text, limit=limit)
    resolved = []
    unresolved = []
    for candidate in parsed["candidates"]:
        match = None
        if candidate["confidence"] >= min_confidence and not candidate["needs_review"]:
            match = _catalog_match_for_candidate(candidate)

        item = dict(candidate)
        if match:
            item["song"] = _song_summary(match)
            item["song_id"] = match.id
            item["status"] = "resolved"
            item["action"] = "accepted"
            resolved.append(item)
        else:
            item["song"] = None
            item["song_id"] = None
            if candidate["confidence"] < min_confidence:
                item.setdefault("issues", []).append("below_min_confidence")
            elif candidate["artist"]:
                item.setdefault("issues", []).append("not_found_in_catalog")
            item["status"] = "needs_review"
            item["action"] = "review_required"
            unresolved.append(item)

    rows = sorted(resolved + unresolved, key=lambda item: item["line"])
    return {
        "parsed": parsed,
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "skipped_count": 0,
        "resolved": resolved,
        "unresolved": unresolved,
        "skipped": [],
        "rows": rows,
        "ready_for_round": parsed["count"] > 0 and not unresolved,
        "source_positions": [
            {
                "position": index + 1,
                "source_line": item["line"],
                "source_raw": item["raw"],
                "song_id": item["song_id"],
                "resolved": True,
                "status": "resolved",
                "artist": item.get("artist"),
                "title": item.get("title"),
                "action": item.get("action"),
                "reason": None,
            }
            for index, item in enumerate(resolved)
        ],
        "summary": {
            "accepted_count": len(resolved),
            "edited_count": 0,
            "replaced_count": 0,
            "skipped_count": 0,
            "unresolved_count": len(unresolved),
        },
        "hints": [
            "Resolve or correct every unresolved row before creating a round.",
            "Use add_song or import_catalog_item to add missing catalog entries.",
        ],
    }


def _review_decision_for_line(
    review_decisions: list[dict[str, Any]] | dict[int | str, dict[str, Any]] | None,
    line: int,
) -> dict[str, Any]:
    if not review_decisions:
        return {}
    if isinstance(review_decisions, dict):
        decision = review_decisions.get(line) or review_decisions.get(str(line)) or {}
        return decision if isinstance(decision, dict) else {}
    for decision in review_decisions:
        try:
            decision_line = int(decision.get("line"))
        except (AttributeError, TypeError, ValueError):
            continue
        if decision_line == line:
            return decision
    return {}


def _song_for_review_replacement(decision: dict[str, Any]) -> Song | None:
    raw_song_id = decision.get("song_id") or decision.get("replacement_song_id")
    if not raw_song_id:
        return None
    try:
        song_id = int(raw_song_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(Song, song_id)


def _reviewed_text_source_position(
    item: dict[str, Any],
    position: int | None,
    *,
    resolved: bool,
    status: str,
    action: str,
    reason: str | None = None,
) -> dict[str, Any]:
    song_id = item.get("song_id")
    return {
        "position": position,
        "source_line": item.get("line"),
        "source_raw": item.get("raw"),
        "song_id": song_id,
        "resolved": resolved,
        "status": status,
        "artist": item.get("artist"),
        "title": item.get("title"),
        "action": action,
        "reason": reason,
    }


def resolve_text_playlist_review(
    text: str,
    review_decisions: list[dict[str, Any]] | dict[int | str, dict[str, Any]] | None = None,
    limit: int = 100,
    min_confidence: float = 0.8,
) -> dict[str, Any]:
    """Resolve a text playlist after explicit row-level review decisions."""
    parsed = parse_text_playlist(text, limit=limit)
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    summary = {
        "accepted_count": 0,
        "edited_count": 0,
        "replaced_count": 0,
        "skipped_count": 0,
        "unresolved_count": 0,
    }

    for candidate in parsed["candidates"]:
        decision = _review_decision_for_line(review_decisions, candidate["line"])
        explicit_action = (decision.get("action") or "").strip().lower()
        action = explicit_action or ("review_required" if candidate["needs_review"] else "accept")
        item = dict(candidate)
        item["song"] = None
        item["song_id"] = None
        item["action"] = action

        if action == "skip":
            item["status"] = "skipped"
            item["issues"] = list(item.get("issues") or []) + ["skipped_by_reviewer"]
            skipped.append(item)
            rows.append(item)
            summary["skipped_count"] += 1
            continue

        match = None
        if action == "replace":
            match = _song_for_review_replacement(decision)
            if not match:
                item["status"] = "needs_review"
                item["issues"] = list(item.get("issues") or []) + ["replacement_song_not_found"]
                unresolved.append(item)
                rows.append(item)
                continue
            item["title"] = match.title
            item["artist"] = match.artist
            summary["replaced_count"] += 1
        elif action == "edit":
            edited_title = (decision.get("title") or "").strip()
            edited_artist = (decision.get("artist") or "").strip()
            item["title"] = edited_title or None
            item["artist"] = edited_artist or None
            item["issues"] = []
            if not item["title"]:
                item["issues"].append("missing_title")
            if not item["artist"]:
                item["issues"].append("missing_artist")
            match = _catalog_match_for_candidate(item) if not item["issues"] else None
            summary["edited_count"] += 1
        elif action == "accept":
            if candidate["needs_review"] and not explicit_action:
                item["status"] = "needs_review"
                item["issues"] = list(item.get("issues") or []) + ["explicit_review_required"]
                unresolved.append(item)
                rows.append(item)
                continue
            match = _catalog_match_for_candidate(item)
            summary["accepted_count"] += 1
        else:
            item["status"] = "needs_review"
            item["issues"] = list(item.get("issues") or []) + ["review_required"]
            unresolved.append(item)
            rows.append(item)
            continue

        if match:
            item["song"] = _song_summary(match)
            item["song_id"] = match.id
            item["status"] = "resolved"
            resolved.append(item)
        else:
            item["status"] = "needs_review"
            if not item.get("issues"):
                item["issues"] = ["not_found_in_catalog"]
            unresolved.append(item)
        rows.append(item)

    summary["unresolved_count"] = len(unresolved)
    source_positions = [
        _reviewed_text_source_position(
            item,
            index + 1,
            resolved=True,
            status="resolved",
            action=item.get("action") or "accept",
        )
        for index, item in enumerate(resolved)
    ] + [
        _reviewed_text_source_position(
            item,
            None,
            resolved=False,
            status=item.get("status") or "needs_review",
            action=item.get("action") or "review_required",
            reason="skipped_by_reviewer" if item.get("status") == "skipped" else "not_resolved",
        )
        for item in skipped + unresolved
    ]

    return {
        "parsed": parsed,
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "skipped_count": len(skipped),
        "resolved": resolved,
        "unresolved": unresolved,
        "skipped": skipped,
        "rows": rows,
        "ready_for_round": bool(resolved) and not unresolved,
        "source_positions": source_positions,
        "summary": summary,
        "hints": [
            "Low-confidence rows require an explicit accept, edit, skip, or replacement decision.",
            "Skipped rows are reported and do not count toward the eight-song round.",
        ],
    }


def create_round_from_text_playlist(
    text: str,
    name: str | None = None,
    count: int = 8,
    min_confidence: float = 0.8,
    user_id: int | None = None,
    review_decisions: list[dict[str, Any]] | dict[int | str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a manual round from a parsed text playlist only when all rows resolve."""
    if review_decisions:
        resolved = resolve_text_playlist_review(
            text,
            review_decisions=review_decisions,
            limit=max(count * 2, 1),
            min_confidence=min_confidence,
        )
    else:
        resolved = resolve_text_playlist(text, limit=max(count, 1), min_confidence=min_confidence)
    if resolved["unresolved_count"]:
        raise AutomationError(
            "Text playlist has unresolved rows.",
            details={
                "created": False,
                "status": "needs_review",
                "resolution": resolved,
            },
        )
    song_ids = [item["song_id"] for item in resolved["resolved"]]
    if len(song_ids) != count:
        message = f"Text playlist resolved {len(song_ids)} songs; expected exactly {count}."
        raise AutomationError(
            message,
            details={
                "created": False,
                "status": "song_count_mismatch",
                "expected_song_count": count,
                "resolved_song_count": len(song_ids),
                "resolution": resolved,
            },
        )

    round_result = create_round(
        name=name,
        round_type="manual",
        count=count,
        song_ids=song_ids,
        user_id=user_id,
    )
    return {
        "created": True,
        "resolution": resolved,
        "round": round_result["round"],
        "resolved_positions": resolved.get("source_positions", []),
    }


def _song_usage_warning(song: Song, window_start: datetime) -> dict[str, Any] | None:
    if not song.last_used:
        return None
    if song.last_used < window_start:
        return None
    return {
        "song": _song_summary(song),
        "warning": (
            f"Heads up: {song.artist} - {song.title} was used on "
            f"{song.last_used.date().isoformat()}."
        ),
        "last_used": _datetime_payload(song.last_used),
    }


def recent_usage_summary(
    user_id: int | None = None,
    months: int = 3,
    song_ids: list[int] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Summarize recent song and round usage for autonomous round planning."""
    if months < 1 or months > 24:
        raise AutomationError("months must be between 1 and 24.")
    if limit < 1 or limit > 200:
        raise AutomationError("limit must be between 1 and 200.")

    window_start = datetime.utcnow() - timedelta(days=months * 31)
    rounds_query = Round.query.filter(Round.created_at >= window_start)
    rounds = rounds_query.order_by(Round.created_at.desc(), Round.id.desc()).limit(limit).all()

    songs_query = Song.query.filter(Song.last_used.isnot(None)).filter(Song.last_used >= window_start)
    songs = songs_query.order_by(Song.used_count.desc(), Song.last_used.desc()).limit(limit).all()

    selected_warnings = []
    if song_ids:
        selected = Song.query.filter(Song.id.in_(song_ids)).all()
        selected_warnings = [
            warning for song in selected
            if (warning := _song_usage_warning(song, window_start)) is not None
        ]

    user = _find_user(user_id) if user_id is not None else None
    return {
        "window_months": months,
        "window_start": _datetime_payload(window_start),
        "user": None if user is None else {"id": user.id, "username": user.username, "email": user.email},
        "round_count": len(rounds),
        "recent_rounds": [_round_summary(round_obj) for round_obj in rounds],
        "frequent_songs": [_song_summary(song) for song in songs],
        "selected_song_warnings": selected_warnings,
        "guidance": [
            "Avoid selected_song_warnings unless there is a strong thematic reason.",
            "Prefer lower used_count songs when quality and recognizability are comparable.",
        ],
    }


def round_analytics_summary(months: int = 6, limit: int = 20) -> dict[str, Any]:
    """Return catalog and round analytics useful for planning and backlog decisions."""
    if months < 1 or months > 36:
        raise AutomationError("months must be between 1 and 36.")
    if limit < 1 or limit > 100:
        raise AutomationError("limit must be between 1 and 100.")

    window_start = datetime.utcnow() - timedelta(days=months * 31)
    recent_rounds = Round.query.filter(Round.created_at >= window_start).count()
    most_used = (
        Song.query.order_by(Song.used_count.desc(), Song.artist.asc(), Song.title.asc())
        .limit(limit)
        .all()
    )
    stale_candidates = (
        Song.query.filter((Song.used_count == 0) | (Song.used_count.is_(None)))
        .order_by(Song.artist.asc(), Song.title.asc())
        .limit(limit)
        .all()
    )
    missing_preview_count = Song.query.filter(
        Song.preview_url.is_(None),
        Song.spotify_preview_url.is_(None),
        Song.deezer_preview_url.is_(None),
        Song.apple_preview_url.is_(None),
        Song.youtube_preview_url.is_(None),
    ).count()

    genre_rows = db.session.query(Song.genre).order_by(Song.id.asc()).yield_per(1000)
    unknown_genre_count = 0
    genre_counts_by_key: dict[str, int] = {}
    genre_labels_by_key: dict[str, str] = {}
    for (raw_genre,) in genre_rows:
        genre_label = " ".join((raw_genre or "").strip().split())
        if not genre_label or genre_label.casefold() == "unknown":
            unknown_genre_count += 1
            continue

        genre_key = genre_label.casefold()
        genre_labels_by_key.setdefault(genre_key, genre_label)
        genre_counts_by_key[genre_key] = genre_counts_by_key.get(genre_key, 0) + 1

    genre_counts = {
        genre_labels_by_key[genre_key]: count
        for genre_key, count in sorted(
            genre_counts_by_key.items(),
            key=lambda item: (-item[1], genre_labels_by_key[item[0]].casefold()),
        )
    }

    return {
        "window_months": months,
        "window_start": _datetime_payload(window_start),
        "song_count": Song.query.count(),
        "round_count": Round.query.count(),
        "recent_round_count": recent_rounds,
        "missing_preview_count": missing_preview_count,
        "unknown_genre_count": unknown_genre_count,
        "genre_counts": genre_counts,
        "most_used_songs": [_song_summary(song) for song in most_used],
        "unused_candidates": [_song_summary(song) for song in stale_candidates],
        "guidance": [
            "Prefer unused_candidates when they fit the theme and have usable previews.",
            "Treat missing_preview_count as replacement pressure before scheduling email delivery.",
        ],
    }


def quizmaster_context(user_id: int, months: int = 3) -> dict[str, Any]:
    """Return personalization context for an agent planning a quiz round."""
    user = _find_user(user_id)
    preferences = user.preferences
    return {
        "quizmaster": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "name": " ".join(part for part in (user.first_name, user.last_name) if part) or None,
        },
        "preferences": {
            "default_tts_service": preferences.default_tts_service if preferences else "polly",
            "enable_intro": preferences.enable_intro if preferences else True,
            "theme": preferences.theme if preferences else "light",
            "has_intro_mp3": bool(user.intro_mp3),
            "has_replay_mp3": bool(user.replay_mp3),
            "has_outro_mp3": bool(user.outro_mp3),
        },
        "recent_usage": recent_usage_summary(user_id=user.id, months=months, limit=25),
    }


def create_planned_quiz_round(
    quiz_date: str | datetime,
    quizmaster_id: int | None = None,
    theme: str | None = None,
    brief: str | None = None,
    due_at: str | datetime | None = None,
    source_playlist_url: str | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    """Create a planned quiz entry before a concrete round exists."""
    quizmaster = _find_user(quizmaster_id) if quizmaster_id is not None else None
    plan = PlannedQuizRound(
        quiz_date=_parse_datetime_utc(quiz_date),
        quizmaster_id=quizmaster.id if quizmaster else None,
        theme=(theme or "").strip() or None,
        brief=(brief or "").strip() or None,
        source_playlist_url=(source_playlist_url or "").strip() or None,
        due_at=_parse_datetime_utc(due_at) if due_at else None,
        status=status,
    )
    db.session.add(plan)
    db.session.commit()
    return {"created": True, "plan": _planned_quiz_round_summary(plan)}


def list_planned_quiz_rounds(
    quizmaster_id: int | None = None,
    status: str | None = None,
    include_past: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """List planned quiz entries for production-board and MCP callers."""
    if limit < 1 or limit > 200:
        raise AutomationError("limit must be between 1 and 200.")

    query = PlannedQuizRound.query
    if quizmaster_id is not None:
        _find_user(quizmaster_id)
        query = query.filter_by(quizmaster_id=quizmaster_id)
    if status:
        status = status.strip().lower()
        if status not in {'planned', 'drafted', 'blocked', 'approved', 'scheduled', 'sent'}:
            raise AutomationError(f"Invalid planned quiz status: {status!r}.")
        query = query.filter_by(status=status)
    if not include_past:
        query = query.filter(PlannedQuizRound.quiz_date >= datetime.utcnow())

    plans = (
        query.order_by(PlannedQuizRound.quiz_date.asc(), PlannedQuizRound.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(plans),
        "plans": [_planned_quiz_round_summary(plan) for plan in plans],
        "filters": {
            "quizmaster_id": quizmaster_id,
            "status": status,
            "include_past": include_past,
            "limit": limit,
        },
    }


def update_planned_quiz_round(
    plan_id: int,
    quiz_date: str | datetime | None = None,
    quizmaster_id: int | None = None,
    theme: str | None = None,
    brief: str | None = None,
    due_at: str | datetime | None = None,
    source_playlist_url: str | None = None,
    status: str | None = None,
    round_id: int | None = None,
    export_id: int | None = None,
) -> dict[str, Any]:
    """Update a planned quiz entry and optionally link generated artifacts."""
    plan = db.session.get(PlannedQuizRound, plan_id)
    if not plan:
        raise AutomationError(f"Planned quiz round {plan_id} was not found.")

    if quiz_date is not None:
        plan.quiz_date = _parse_datetime_utc(quiz_date)
    if quizmaster_id is not None:
        plan.quizmaster_id = _find_user(quizmaster_id).id
    if theme is not None:
        plan.theme = theme.strip() or None
    if brief is not None:
        plan.brief = brief.strip() or None
    if due_at is not None:
        plan.due_at = _parse_datetime_utc(due_at) if due_at else None
    if source_playlist_url is not None:
        plan.source_playlist_url = source_playlist_url.strip() or None
    if status is not None:
        plan.status = status.strip().lower()
    if round_id is not None:
        if not db.session.get(Round, round_id):
            raise AutomationError(f"Round {round_id} was not found.")
        plan.round_id = round_id
    if export_id is not None:
        if not db.session.get(RoundExport, export_id):
            raise AutomationError(f"RoundExport {export_id} was not found.")
        plan.export_id = export_id
    plan.updated_at = datetime.utcnow()
    db.session.commit()
    return {"updated": True, "plan": _planned_quiz_round_summary(plan)}


def link_planned_quiz_round(
    plan_id: int,
    round_id: int | None = None,
    export_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Link a planned quiz entry to a generated round and/or scheduled export."""
    if round_id is None and export_id is None and status is None:
        raise AutomationError("Provide round_id, export_id, or status to update the plan.")
    return update_planned_quiz_round(
        plan_id,
        round_id=round_id,
        export_id=export_id,
        status=status,
    )


def round_planning_brief(
    user_id: int,
    quiz_date: str | datetime | None = None,
    theme: str | None = None,
    desired_song_count: int = 8,
    months: int = 3,
) -> dict[str, Any]:
    """Build an agent-readable brief for planning a robust themed round."""
    if desired_song_count < 1 or desired_song_count > 25:
        raise AutomationError("desired_song_count must be between 1 and 25.")

    parsed_date = _parse_datetime_utc(quiz_date) if quiz_date else None
    context = quizmaster_context(user_id=user_id, months=months)
    date_notes = []
    if parsed_date:
        weekday = parsed_date.strftime("%A")
        date_notes.append(f"Quiz date is {parsed_date.date().isoformat()} ({weekday}).")
        if parsed_date.month == 12:
            date_notes.append("Seasonal angle available: year-end, winter, holidays.")
        elif parsed_date.month in {6, 7, 8}:
            date_notes.append("Seasonal angle available: summer, festivals, travel.")

    constraints = [
        f"Build exactly {desired_song_count} songs.",
        "Every selected song needs a playable preview before email delivery.",
        "Avoid songs that appear in selected_song_warnings or have high recent used_count.",
        "Prefer mainstream recognizability unless the theme explicitly asks for deeper cuts.",
    ]
    return {
        "theme": theme,
        "quiz_date": _datetime_payload(parsed_date),
        "date_notes": date_notes,
        "desired_song_count": desired_song_count,
        "constraints": constraints,
        "quizmaster_context": context,
        "agent_prompt": (
            "Use this brief to propose a complete music round. Explain any repeated "
            "song risk and return replacement ideas for weak preview candidates."
        ),
    }


def draft_round_audio_scripts(
    round_id: int | None = None,
    user_id: int | None = None,
    quiz_date: str | datetime | None = None,
    theme: str | None = None,
    tone: str = "warm, concise, lightly humorous",
    persist: bool = False,
) -> dict[str, Any]:
    """Draft intro, replay, and outro text for later TTS generation."""
    round_obj = db.session.get(Round, round_id) if round_id is not None else None
    if round_id is not None and not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    user = _find_user(user_id) if user_id is not None else None
    parsed_date = _parse_datetime_utc(quiz_date) if quiz_date else None
    songs = _ordered_round_songs(round_obj) if round_obj else []
    theme_label = theme or (round_obj.name if round_obj and round_obj.name else "music round")
    artist_names = ", ".join(song.artist for song in songs[:3])
    date_phrase = f" on {parsed_date.date().isoformat()}" if parsed_date else ""
    quizmaster_phrase = f" for {user.username}" if user else ""
    song_hint = f" Expect artists like {artist_names}." if artist_names else ""

    scripts = {
        "intro": (
            f"Welcome to the {theme_label}{date_phrase}{quizmaster_phrase}. "
            f"Eight songs, twice through, and no mercy for confident wrong answers.{song_hint}"
        ),
        "replay": (
            "Here comes the second listen. Trust your first instinct, unless your "
            "first instinct was loudly explaining the wrong decade."
        ),
        "outro": (
            "That is the music round. Lock in artist and title, compare notes quietly, "
            "and prepare to defend every spelling choice."
        ),
    }
    result = {
        "round_id": round_id,
        "round_name": round_obj.name if round_obj else None,
        "user_id": user.id if user else None,
        "quiz_date": _datetime_payload(parsed_date),
        "theme": theme_label,
        "tone": tone,
        "scripts": scripts,
        "next_step": "Review the text, then call generate_tts_snippet for intro, replay, and outro.",
    }
    if persist:
        if round_id is None:
            raise AutomationError("round_id is required when persist is true.")
        saved = save_round_audio_scripts(
            round_id=round_id,
            user_id=user.id if user else None,
            scripts=scripts,
            quiz_date=parsed_date,
            theme=theme_label,
            tone=tone,
        )
        result["script_records"] = saved["scripts"]
        result["next_step"] = (
            "Review the saved script records, approve the preferred text, then "
            "call generate_tts_from_script for intro, replay, and outro."
        )
    return result


def _audio_script_summary(script: RoundAudioScript) -> dict[str, Any]:
    return {
        "id": script.id,
        "round_id": script.round_id,
        "user_id": script.user_id,
        "script_type": script.script_type,
        "text": script.text,
        "status": script.status,
        "tone": script.tone,
        "theme": script.theme,
        "cue_position": script.cue_position,
        "quiz_date": _datetime_payload(script.quiz_date),
        "selected": bool(script.selected),
        "generated_mp3_path": script.generated_mp3_path,
        "created_at": _datetime_payload(script.created_at),
        "updated_at": _datetime_payload(script.updated_at),
    }


def _validate_script_type(script_type: str) -> str:
    normalized = (script_type or "").strip().lower()
    if normalized not in {"intro", "replay", "outro", "track_hint"}:
        raise AutomationError("script_type must be intro, replay, outro, or track_hint.")
    return normalized


def _validate_script_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized not in {"draft", "reviewed", "approved", "rejected", "used"}:
        raise AutomationError("status must be draft, reviewed, approved, rejected, or used.")
    return normalized


def save_round_audio_scripts(
    round_id: int,
    scripts: dict[str, str],
    user_id: int | None = None,
    quiz_date: str | datetime | None = None,
    theme: str | None = None,
    tone: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Persist reviewable intro/replay/outro text before assigning TTS audio."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    if not scripts:
        raise AutomationError("scripts must include at least one script text.")
    user = _find_user(user_id) if user_id is not None else round_obj.owner
    normalized_status = _validate_script_status(status)
    parsed_date = _parse_datetime_utc(quiz_date) if quiz_date else None

    created_scripts = []
    for raw_type, text in scripts.items():
        script_type = _validate_script_type(raw_type)
        if not text or not text.strip():
            raise AutomationError(f"{script_type} script text must not be empty.")
        script = RoundAudioScript(
            round_id=round_obj.id,
            user_id=user.id if user else None,
            script_type=script_type,
            text=text.strip(),
            status=normalized_status,
            tone=tone,
            theme=theme,
            quiz_date=parsed_date,
        )
        db.session.add(script)
        created_scripts.append(script)
    db.session.commit()
    return {
        "created": len(created_scripts),
        "round": _round_summary(round_obj),
        "scripts": [_audio_script_summary(script) for script in created_scripts],
    }


def _hint_text_for_song(song: Song, position: int, tone: str) -> str:
    clues: list[str] = [f"Hint for song {position}."]
    if song.year:
        clues.append(f"It comes from {song.year}.")
    if song.genre:
        clues.append(f"Think {song.genre}.")
    if song.popularity:
        clues.append("This one has serious mainstream mileage.")
    if not song.year and not song.genre:
        clues.append("Listen for the era, then lock artist and title.")
    if "funny" in tone.lower() or "humor" in tone.lower() or "humorous" in tone.lower():
        clues.append("Confidence is welcome; overconfidence is traditional.")
    return " ".join(clues)


def draft_round_track_hints(
    round_id: int,
    user_id: int | None = None,
    tone: str = "concise, playful, no title or artist spoilers",
    persist: bool = False,
) -> dict[str, Any]:
    """Draft per-track hint text that can be played before snippets."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    user = _find_user(user_id) if user_id is not None else round_obj.owner
    songs = _ordered_round_songs(round_obj)
    hints = [
        {
            "position": index,
            "song_id": song.id,
            "text": _hint_text_for_song(song, index, tone),
        }
        for index, song in enumerate(songs, start=1)
    ]
    result: dict[str, Any] = {
        "round": _round_summary(round_obj),
        "user_id": user.id if user else None,
        "tone": tone,
        "hints": hints,
        "next_step": "Review hints, then call save_round_track_hints and generate_tts_from_script.",
    }
    if persist:
        saved = save_round_track_hints(
            round_id=round_id,
            hints=hints,
            user_id=user.id if user else None,
            tone=tone,
            status="draft",
        )
        result["script_records"] = saved["scripts"]
        result["next_step"] = "Approve selected hint scripts, then call generate_tts_from_script for each hint."
    return result


def save_round_track_hints(
    round_id: int,
    hints: list[dict[str, Any]],
    user_id: int | None = None,
    tone: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Persist reviewable per-track hint scripts."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")
    if not hints:
        raise AutomationError("hints must include at least one track hint.")
    song_count = len(round_obj.song_id_list)
    user = _find_user(user_id) if user_id is not None else round_obj.owner
    normalized_status = _validate_script_status(status)

    created_scripts = []
    for hint in hints:
        try:
            position = int(hint.get("position"))
        except (TypeError, ValueError):
            raise AutomationError("Each hint needs a numeric position.")
        if position < 1 or position > song_count:
            raise AutomationError(f"Hint position {position} is outside this round's song range.")
        text = (hint.get("text") or "").strip()
        if not text:
            raise AutomationError(f"Hint position {position} text must not be empty.")
        script = RoundAudioScript(
            round_id=round_obj.id,
            user_id=user.id if user else None,
            script_type="track_hint",
            text=text,
            status=normalized_status,
            tone=tone,
            cue_position=position,
        )
        db.session.add(script)
        created_scripts.append(script)
    db.session.commit()
    return {
        "created": len(created_scripts),
        "round": _round_summary(round_obj),
        "scripts": [_audio_script_summary(script) for script in created_scripts],
    }


def list_round_audio_scripts(
    round_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List stored round-audio scripts for review workflows."""
    if limit < 1 or limit > 200:
        raise AutomationError("limit must be between 1 and 200.")
    query = RoundAudioScript.query
    if round_id is not None:
        query = query.filter_by(round_id=round_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if status is not None:
        query = query.filter_by(status=_validate_script_status(status))
    scripts = (
        query.order_by(
            RoundAudioScript.created_at.desc(),
            RoundAudioScript.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return {
        "count": len(scripts),
        "scripts": [_audio_script_summary(script) for script in scripts],
    }


def update_round_audio_script(
    script_id: int,
    text: str | None = None,
    status: str | None = None,
    selected: bool | None = None,
) -> dict[str, Any]:
    """Edit or review one stored round-audio script."""
    script = db.session.get(RoundAudioScript, script_id)
    if not script:
        raise AutomationError(f"RoundAudioScript {script_id} was not found.")
    if text is not None:
        if not text.strip():
            raise AutomationError("text must not be empty.")
        script.text = text.strip()
    if status is not None:
        script.status = _validate_script_status(status)
    if selected is not None:
        script.selected = bool(selected)
    script.updated_at = datetime.utcnow()
    db.session.commit()
    return {"script": _audio_script_summary(script)}


def generate_tts_from_script(
    script_id: int,
    service: str = "openai",
    voice: str | None = None,
    model: str | None = None,
    stability: float | None = None,
    similarity: float | None = None,
) -> dict[str, Any]:
    """Generate a user custom MP3 from an approved stored script."""
    script = db.session.get(RoundAudioScript, script_id)
    if not script:
        raise AutomationError(f"RoundAudioScript {script_id} was not found.")
    if script.status not in {"approved", "reviewed"}:
        raise AutomationError("Script must be reviewed or approved before TTS generation.")
    user_id = script.user_id or (script.round.user_id if script.round else None)
    if user_id is None:
        raise AutomationError("Script has no user or round owner for audio assignment.")

    if script.script_type == "track_hint":
        user = _find_user(user_id)
        mp3_type = f"round_{script.round_id}_hint_{script.cue_position or script.id}"
        path = generate_tts_mp3(
            text=script.text,
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
        generated = {
            "user_id": user.id,
            "mp3_type": script.script_type,
            "path": path,
        }
    else:
        generated = generate_tts_snippet(
            user_id=user_id,
            mp3_type=script.script_type,
            text=script.text,
            service=service,
            voice=voice,
            model=model,
            stability=stability,
            similarity=similarity,
        )
    script.generated_mp3_path = generated["path"]
    script.selected = True
    script.status = "used"
    script.updated_at = datetime.utcnow()
    db.session.commit()
    return {"script": _audio_script_summary(script), "generated": generated}


def _parse_datetime_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _datetime_payload(value: datetime | None) -> str | None:
    return None if value is None else f"{value.isoformat()}Z"


def _round_export_summary(export: RoundExport) -> dict[str, Any]:
    return {
        "id": export.id,
        "round_id": export.round_id,
        "round_name": export.round.name if export.round else None,
        "user_id": export.user_id,
        "export_type": export.export_type,
        "destination": export.destination,
        "status": export.status,
        "scheduled_for": _datetime_payload(export.scheduled_for),
        "processed_at": _datetime_payload(export.processed_at),
        "timestamp": _datetime_payload(export.timestamp),
        "subject": export.subject,
        "body_text": export.body_text,
        "error_message": export.error_message,
    }


def _scheduled_email_error_message(exc: Exception) -> str:
    """Return a persisted, credential-safe scheduled email failure summary."""
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        report = details.get("report")
        if isinstance(report, dict) and report.get("headline"):
            return str(report["headline"])
        quality = details.get("quality")
        if isinstance(quality, dict):
            quality_report = quality.get("report")
            if isinstance(quality_report, dict) and quality_report.get("headline"):
                return str(quality_report["headline"])
            if quality.get("status"):
                return f"Round quality gate failed: {quality['status']}."
        if details.get("status"):
            return f"Scheduled round email failed: {details['status']}."
    return AUTOMATION_SCHEDULED_EMAIL_ERROR


def schedule_round_email(
    round_id: int,
    scheduled_for: str | datetime,
    recipient: str | None = None,
    user_id: int | None = None,
    subject: str | None = None,
    body_text: str | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Generate, inspect, and schedule a robust round email for a future worker run."""
    round_obj = db.session.get(Round, round_id)
    if not round_obj:
        raise AutomationError(f"Round {round_id} was not found.")

    user = _find_user(user_id)
    target = recipient or user.email
    if not target:
        raise AutomationError("No recipient was provided and the selected user has no email.")

    scheduled_at = _parse_datetime_utc(scheduled_for)
    if scheduled_at <= datetime.utcnow():
        raise AutomationError(
            "Scheduled delivery time must be in the future.",
            details={
                "scheduled": False,
                "status": "schedule_in_past",
                "recipient": target,
                "scheduled_for": _datetime_payload(scheduled_at),
                "hints": ["Choose a future delivery time before scheduling the round email."],
            },
        )
    email_health = email_service_health(required=True)
    if not email_health["ok"]:
        message = "Email configuration is not ready for scheduled delivery."
        raise AutomationError(
            message,
            details={
                "scheduled": False,
                "status": "email_unhealthy",
                "recipient": target,
                "scheduled_for": _datetime_payload(scheduled_at),
                "service_health": {"email": email_health},
                "hints": [issue["message"] for issue in email_health["issues"]],
            },
        )

    assets = generate_round_assets(round_id, user_id=user.id)
    quality = inspect_round_package(round_id, user_id=user.id)
    if not quality["ok"]:
        report = quality.get("report") or _round_repair_report(quality)
        send_round_blocked_notification(user=user, round_id=round_id, quality=quality)
        message = "Round quality gate failed: " + "; ".join(quality["hints"])
        raise AutomationError(
            message,
            details={
                "scheduled": False,
                "status": quality["status"],
                "recipient": target,
                "scheduled_for": _datetime_payload(scheduled_at),
                "assets": assets,
                "quality": quality,
                "report": report,
            },
        )

    replaced_exports = []
    if replace_existing:
        existing_exports = (
            RoundExport.query.filter_by(
                round_id=round_id,
                user_id=user.id,
                export_type="email",
                status="scheduled",
            )
            .filter(RoundExport.scheduled_for.isnot(None))
            .all()
        )
        for existing in existing_exports:
            existing.status = "superseded"
            existing.processed_at = datetime.utcnow()
            existing.error_message = "Replaced by a newer scheduled delivery."
            replaced_exports.append(_round_export_summary(existing))

    export = RoundExport(
        round_id=round_id,
        user_id=user.id,
        export_type="email",
        destination=target,
        include_mp3s=True,
        status="scheduled",
        scheduled_for=scheduled_at,
        subject=subject,
        body_text=body_text,
    )
    db.session.add(export)
    db.session.commit()
    return {
        "scheduled": True,
        "export": _round_export_summary(export),
        "replaced_exports": replaced_exports,
        "assets": assets,
        "quality": quality,
    }


def list_scheduled_round_emails(
    user_id: int | None = None,
    include_processed: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List scheduled round email exports."""
    if limit < 1 or limit > 200:
        raise AutomationError("limit must be between 1 and 200.")

    query = RoundExport.query.filter_by(export_type="email").filter(
        RoundExport.scheduled_for.isnot(None)
    )
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if not include_processed:
        query = query.filter_by(status="scheduled")
    exports = (
        query.order_by(RoundExport.scheduled_for.asc(), RoundExport.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(exports),
        "scheduled_exports": [_round_export_summary(item) for item in exports],
    }


def cancel_scheduled_round_email(
    export_id: int,
    user_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a pending scheduled round email before the scheduler sends it."""
    export = db.session.get(RoundExport, export_id)
    if not export:
        raise AutomationError(f"RoundExport {export_id} was not found.")
    if export.export_type != "email" or export.scheduled_for is None:
        raise AutomationError(f"RoundExport {export_id} is not a scheduled email export.")
    if user_id is not None and export.user_id != user_id:
        raise AutomationError(f"RoundExport {export_id} is not owned by user {user_id}.")
    if export.status != "scheduled":
        raise AutomationError(f"RoundExport {export_id} is already {export.status}.")

    export.status = "cancelled"
    export.processed_at = datetime.utcnow()
    export.error_message = reason or "Cancelled before scheduled delivery."
    db.session.commit()
    return {"cancelled": True, "export": _round_export_summary(export)}


def process_due_scheduled_round_emails(
    now: str | datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Send scheduled round emails that are due and still pending."""
    if limit < 1 or limit > 100:
        raise AutomationError("limit must be between 1 and 100.")

    now_utc = _parse_datetime_utc(now) if now is not None else datetime.utcnow()
    due_exports = (
        RoundExport.query.filter_by(export_type="email", status="scheduled")
        .filter(RoundExport.scheduled_for.isnot(None))
        .filter(RoundExport.scheduled_for <= now_utc)
        .order_by(RoundExport.scheduled_for.asc(), RoundExport.id.asc())
        .limit(limit)
        .all()
    )

    results = []
    for export in due_exports:
        export.status = "processing"
        db.session.commit()
        try:
            delivery = email_round(
                export.round_id,
                recipient=export.destination,
                user_id=export.user_id,
                subject=export.subject,
                body_text=export.body_text,
                record_export=False,
            )
            export.status = "success"
            export.processed_at = datetime.utcnow()
            export.error_message = delivery.get("message")
            db.session.commit()
            results.append({"export": _round_export_summary(export), "delivery": delivery})
        except Exception as exc:
            export.status = "failed"
            export.processed_at = datetime.utcnow()
            safe_error_message = _scheduled_email_error_message(exc)
            current_app.logger.error(
                "Scheduled round email export %s failed: %s",
                export.id,
                exc,
                exc_info=True,
            )
            export.error_message = safe_error_message
            db.session.commit()
            details = getattr(exc, "details", None)
            results.append(
                {
                    "export": _round_export_summary(export),
                    "error": safe_error_message,
                    "details": details,
                }
            )

    return {
        "processed_count": len(results),
        "now": _datetime_payload(now_utc),
        "results": results,
    }


def email_round(
    round_id: int,
    recipient: str | None = None,
    user_id: int | None = None,
    subject: str | None = None,
    body_text: str | None = None,
    record_export: bool = True,
) -> dict[str, Any]:
    """Generate assets and send a round as an email attachment bundle."""
    user = _find_user(user_id)
    target = recipient or user.email
    if not target:
        raise AutomationError("No recipient was provided and the selected user has no email.")

    assets = generate_round_assets(round_id, user_id=user.id)
    quality = inspect_round_package(round_id, user_id=user.id)
    if not quality["ok"]:
        report = quality.get("report") or _round_repair_report(quality)
        send_round_blocked_notification(user=user, round_id=round_id, quality=quality)
        message = "Round quality gate failed: " + "; ".join(quality["hints"])
        if record_export:
            db.session.add(
                RoundExport(
                    round_id=round_id,
                    user_id=user.id,
                    export_type="email",
                    destination=target,
                    include_mp3s=True,
                    status="failed",
                    error_message=message,
                    subject=subject,
                    body_text=body_text,
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
                "report": report,
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
    if record_export:
        export = RoundExport(
            round_id=round_id,
            user_id=user.id,
            export_type="email",
            destination=target,
            include_mp3s=True,
            status="success" if success else "failed",
            error_message=None if success else message,
            subject=subject,
            body_text=body_text,
            processed_at=datetime.utcnow(),
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
        path = os.path.join(round_mp3_dir(), f"round_{round_id}.mp3")
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
        path = os.path.join(round_pdf_dir(), f"round_{round_id}.pdf")
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
