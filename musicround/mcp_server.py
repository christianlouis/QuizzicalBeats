"""MCP server for agentic Quizzical Beats workflows.

Run with:
    python -m musicround.mcp_server
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from musicround import create_app
from musicround.services import automation


mcp = FastMCP("Quizzical Beats")


@lru_cache(maxsize=1)
def _app():
    """Create the Flask app once for the MCP server process."""
    return create_app()


def _with_app_context(func, *args, **kwargs) -> dict[str, Any]:
    """Run a service function inside the Quizzical Beats app context."""
    app = _app()
    with app.app_context():
        return func(*args, **kwargs)


@mcp.tool()
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
    """Search the local Quizzical Beats catalog before adding a song."""
    return _with_app_context(
        automation.find_songs,
        query=query,
        title=title,
        artist=artist,
        genre=genre,
        year=year,
        year_min=year_min,
        year_max=year_max,
        has_preview=has_preview,
        unused_only=unused_only,
        offset=offset,
        order_by=order_by,
        spotify_id=spotify_id,
        deezer_id=deezer_id,
        isrc=isrc,
        limit=limit,
    )


@mcp.tool()
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
    """Add a song to Quizzical Beats if it is not already present."""
    return _with_app_context(
        automation.add_song,
        title=title,
        artist=artist,
        album_name=album_name,
        genre=genre,
        year=year,
        preview_url=preview_url,
        cover_url=cover_url,
        spotify_id=spotify_id,
        deezer_id=deezer_id,
        isrc=isrc,
        tags=tags,
        source=source,
    )


@mcp.tool()
def datastore_schema() -> dict[str, Any]:
    """Describe every datastore object type available to generic CRUD tools."""
    return _with_app_context(automation.datastore_schema)


@mcp.tool()
def database_configuration_summary() -> dict[str, Any]:
    """Return credential-safe database readiness details for cutover planning."""
    return _with_app_context(automation.database_configuration_summary)


@mcp.tool()
def database_cutover_plan() -> dict[str, Any]:
    """Return credential-safe managed database cutover steps for agents."""
    return _with_app_context(automation.database_cutover_plan_summary)


@mcp.tool()
def list_datastore_objects(
    object_type: str,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str | None = None,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """List datastore objects such as songs, rounds, users, tags, exports, and settings."""
    return _with_app_context(
        automation.list_datastore_objects,
        object_type=object_type,
        filters=filters,
        limit=limit,
        offset=offset,
        order_by=order_by,
        include_sensitive=include_sensitive,
    )


@mcp.tool()
def get_datastore_object(
    object_type: str,
    object_id: Any,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Fetch one datastore object by primary key."""
    return _with_app_context(
        automation.get_datastore_object,
        object_type=object_type,
        object_id=object_id,
        include_sensitive=include_sensitive,
    )


@mcp.tool()
def create_datastore_object(
    object_type: str,
    fields: dict[str, Any],
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Create one datastore object from scalar column fields."""
    return _with_app_context(
        automation.create_datastore_object,
        object_type=object_type,
        fields=fields,
        include_sensitive=include_sensitive,
    )


@mcp.tool()
def update_datastore_object(
    object_type: str,
    object_id: Any,
    fields: dict[str, Any],
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Update scalar column fields on one datastore object."""
    return _with_app_context(
        automation.update_datastore_object,
        object_type=object_type,
        object_id=object_id,
        fields=fields,
        include_sensitive=include_sensitive,
    )


@mcp.tool()
def delete_datastore_object(object_type: str, object_id: Any) -> dict[str, Any]:
    """Delete one datastore object by primary key."""
    return _with_app_context(
        automation.delete_datastore_object,
        object_type=object_type,
        object_id=object_id,
    )


@mcp.tool()
def import_catalog_item(
    service_name: str,
    item_type: str,
    item_id_or_url: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Import a Spotify or Deezer track, album, or playlist into the catalog."""
    return _with_app_context(
        automation.import_catalog_item,
        service_name=service_name,
        item_type=item_type,
        item_id_or_url=item_id_or_url,
        user_id=user_id,
    )


@mcp.tool()
def import_progress_events(
    user_id: int | None = None,
    include_recent: bool = True,
    limit: int = 20,
) -> dict[str, Any]:
    """Return import queue and job status for polling clients."""
    return _with_app_context(
        automation.import_progress_events,
        user_id=user_id,
        include_recent=include_recent,
        limit=limit,
    )


@mcp.tool()
def retry_import_job(job_id: int, reset_attempts: bool = False) -> dict[str, Any]:
    """Retry a failed or dead-letter import job."""
    return _with_app_context(
        automation.retry_import_job,
        job_id=job_id,
        reset_attempts=reset_attempts,
    )


@mcp.tool()
def parse_text_playlist(text: str, limit: int = 100) -> dict[str, Any]:
    """Parse pasted text or CSV-like playlists into reviewable song candidates."""
    return _with_app_context(automation.parse_text_playlist, text=text, limit=limit)


@mcp.tool()
def resolve_text_playlist(
    text: str,
    limit: int = 100,
    min_confidence: float = 0.8,
) -> dict[str, Any]:
    """Resolve a parsed text playlist against existing catalog songs."""
    return _with_app_context(
        automation.resolve_text_playlist,
        text=text,
        limit=limit,
        min_confidence=min_confidence,
    )


@mcp.tool()
def compile_round(
    name: str | None = None,
    round_type: str = "random",
    count: int = 8,
    criteria: str | None = None,
    song_ids: list[int] | None = None,
    user_id: int | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    """Compile songs into a named quiz round."""
    return _with_app_context(
        automation.create_round,
        name=name,
        round_type=round_type,
        count=count,
        criteria=criteria,
        song_ids=song_ids,
        user_id=user_id,
        visibility=visibility,
    )


@mcp.tool()
def rename_round(round_id: int, name: str | None) -> dict[str, Any]:
    """Set or clear the display name for a round."""
    return _with_app_context(automation.rename_round, round_id=round_id, name=name)


@mcp.tool()
def set_round_owner(
    round_id: int,
    user_id: int | None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Assign or clear the quizmaster owner for a round."""
    return _with_app_context(
        automation.set_round_owner,
        round_id=round_id,
        user_id=user_id,
        visibility=visibility,
    )


@mcp.tool()
def share_round(
    round_id: int,
    user_id: int,
    role: str = "viewer",
) -> dict[str, Any]:
    """Share a round with another quizmaster as viewer or editor via system automation."""
    return _with_app_context(
        automation.share_round,
        round_id=round_id,
        user_id=user_id,
        role=role,
    )


@mcp.tool()
def list_round_shares(round_id: int) -> dict[str, Any]:
    """List explicit share grants for a round."""
    return _with_app_context(automation.list_round_shares, round_id=round_id)


@mcp.tool()
def revoke_round_share(
    round_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Remove a user's share grant from a round via system automation."""
    return _with_app_context(
        automation.revoke_round_share,
        round_id=round_id,
        user_id=user_id,
    )


@mcp.tool()
def list_round_access_events(
    round_id: int,
    requester_user_id: int,
    limit: int = 50,
) -> dict[str, Any]:
    """List recent ownership and sharing audit events for a round."""
    return _with_app_context(
        automation.list_round_access_events,
        round_id=round_id,
        limit=limit,
        requester_user_id=requester_user_id,
    )


@mcp.tool()
def enable_round_public_link(round_id: int) -> dict[str, Any]:
    """Enable a token-based read-only public link for a round via system automation."""
    return _with_app_context(
        automation.enable_round_public_link,
        round_id=round_id,
    )


@mcp.tool()
def disable_round_public_link(round_id: int) -> dict[str, Any]:
    """Disable a token-based read-only public link for a round via system automation."""
    return _with_app_context(
        automation.disable_round_public_link,
        round_id=round_id,
    )


@mcp.tool()
def get_public_round(public_token: str) -> dict[str, Any]:
    """Fetch read-only round data for an active public round token."""
    return _with_app_context(
        automation.get_public_round,
        public_token=public_token,
    )


@mcp.tool()
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
    """Create or update a chart, festival, editorial, curated, or playlist seed source."""
    return _with_app_context(
        automation.register_seed_source,
        name=name,
        source_type=source_type,
        provider=provider,
        url=url,
        cadence=cadence,
        priority=priority,
        active=active,
        notes=notes,
    )


@mcp.tool()
def list_seed_sources(
    source_type: str | None = None,
    active: bool | None = True,
    include_runs: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """List configured catalog seed sources for agent planning."""
    return _with_app_context(
        automation.list_seed_sources,
        source_type=source_type,
        active=active,
        include_runs=include_runs,
        limit=limit,
    )


@mcp.tool()
def seed_default_seed_sources() -> dict[str, Any]:
    """Create or update the default chart and festival seed-source registry."""
    return _with_app_context(
        automation.seed_default_seed_sources,
    )


@mcp.tool()
def record_seed_source_run(
    seed_source_id: int,
    status: str,
    songs_seen: int = 0,
    songs_imported: int = 0,
    error_message: str | None = None,
    notes: str | None = None,
    completed: bool = True,
) -> dict[str, Any]:
    """Record a seed-source read/import attempt for later planning context."""
    return _with_app_context(
        automation.record_seed_source_run,
        seed_source_id=seed_source_id,
        status=status,
        songs_seen=songs_seen,
        songs_imported=songs_imported,
        error_message=error_message,
        notes=notes,
        completed=completed,
    )


@mcp.tool()
def fetch_seed_source_candidates(
    seed_source_id: int,
    text: str | None = None,
    limit: int = 100,
    timeout_seconds: float = 20.0,
    record_run: bool = True,
) -> dict[str, Any]:
    """Read a seed source into reviewable candidates without importing songs."""
    return _with_app_context(
        automation.fetch_seed_source_candidates,
        seed_source_id=seed_source_id,
        text=text,
        limit=limit,
        timeout_seconds=timeout_seconds,
        record_run=record_run,
    )


@mcp.tool()
def suggest_replacement_songs(
    round_id: int,
    position: int,
    limit: int = 10,
    query: str | None = None,
    require_deezer_id: bool = True,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
) -> dict[str, Any]:
    """Suggest replacement songs for one failed round position."""
    return _with_app_context(
        automation.suggest_replacement_songs,
        round_id=round_id,
        position=position,
        limit=limit,
        query=query,
        require_deezer_id=require_deezer_id,
        verify_previews=verify_previews,
        min_preview_seconds=min_preview_seconds,
    )


@mcp.tool()
def replace_round_song(
    round_id: int,
    position: int,
    replacement_song_id: int,
    inspect_after: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Replace one song at a 1-based round position and invalidate generated assets."""
    return _with_app_context(
        automation.replace_round_song,
        round_id=round_id,
        position=position,
        replacement_song_id=replacement_song_id,
        inspect_after=inspect_after,
        user_id=user_id,
    )


@mcp.tool()
def suggest_additional_songs(
    round_id: int,
    limit: int = 10,
    query: str | None = None,
    require_deezer_id: bool = True,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
) -> dict[str, Any]:
    """Suggest catalog songs that can be added to an incomplete round."""
    return _with_app_context(
        automation.suggest_additional_songs,
        round_id=round_id,
        limit=limit,
        query=query,
        require_deezer_id=require_deezer_id,
        verify_previews=verify_previews,
        min_preview_seconds=min_preview_seconds,
    )


@mcp.tool()
def add_round_song(
    round_id: int,
    song_id: int,
    position: int | None = None,
    inspect_after: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Add one song to a round at a 1-based position or append it."""
    return _with_app_context(
        automation.add_round_song,
        round_id=round_id,
        song_id=song_id,
        position=position,
        inspect_after=inspect_after,
        user_id=user_id,
    )


@mcp.tool()
def recent_usage_summary(
    user_id: int | None = None,
    months: int = 3,
    song_ids: list[int] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Summarize recent song usage and warn when selected songs were used recently."""
    return _with_app_context(
        automation.recent_usage_summary,
        user_id=user_id,
        months=months,
        song_ids=song_ids,
        limit=limit,
    )


@mcp.tool()
def quizmaster_context(user_id: int, months: int = 3) -> dict[str, Any]:
    """Return quizmaster personalization context and recent usage for round planning."""
    return _with_app_context(
        automation.quizmaster_context,
        user_id=user_id,
        months=months,
    )


@mcp.tool()
def round_planning_brief(
    user_id: int,
    quiz_date: str | None = None,
    theme: str | None = None,
    desired_song_count: int = 8,
    months: int = 3,
) -> dict[str, Any]:
    """Build an agent-readable brief for planning a robust themed music round."""
    return _with_app_context(
        automation.round_planning_brief,
        user_id=user_id,
        quiz_date=quiz_date,
        theme=theme,
        desired_song_count=desired_song_count,
        months=months,
    )


@mcp.tool()
def create_planned_quiz_round(
    quiz_date: str,
    quizmaster_id: int | None = None,
    theme: str | None = None,
    brief: str | None = None,
    due_at: str | None = None,
    source_playlist_url: str | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    """Create a planned quiz date before a concrete round exists."""
    return _with_app_context(
        automation.create_planned_quiz_round,
        quiz_date=quiz_date,
        quizmaster_id=quizmaster_id,
        theme=theme,
        brief=brief,
        due_at=due_at,
        source_playlist_url=source_playlist_url,
        status=status,
    )


@mcp.tool()
def list_planned_quiz_rounds(
    quizmaster_id: int | None = None,
    status: str | None = None,
    include_past: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """List planned quiz dates for agents and production-board views."""
    return _with_app_context(
        automation.list_planned_quiz_rounds,
        quizmaster_id=quizmaster_id,
        status=status,
        include_past=include_past,
        limit=limit,
    )


@mcp.tool()
def update_planned_quiz_round(
    plan_id: int,
    quiz_date: str | None = None,
    quizmaster_id: int | None = None,
    theme: str | None = None,
    brief: str | None = None,
    due_at: str | None = None,
    source_playlist_url: str | None = None,
    status: str | None = None,
    round_id: int | None = None,
    export_id: int | None = None,
) -> dict[str, Any]:
    """Update a planned quiz date and optional linked deliverables."""
    return _with_app_context(
        automation.update_planned_quiz_round,
        plan_id=plan_id,
        quiz_date=quiz_date,
        quizmaster_id=quizmaster_id,
        theme=theme,
        brief=brief,
        due_at=due_at,
        source_playlist_url=source_playlist_url,
        status=status,
        round_id=round_id,
        export_id=export_id,
    )


@mcp.tool()
def link_planned_quiz_round(
    plan_id: int,
    round_id: int | None = None,
    export_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Link a planned quiz date to a generated round or scheduled export."""
    return _with_app_context(
        automation.link_planned_quiz_round,
        plan_id=plan_id,
        round_id=round_id,
        export_id=export_id,
        status=status,
    )


@mcp.tool()
def draft_round_audio_scripts(
    round_id: int | None = None,
    user_id: int | None = None,
    quiz_date: str | None = None,
    theme: str | None = None,
    tone: str = "warm, concise, lightly humorous",
    persist: bool = False,
) -> dict[str, Any]:
    """Draft intro, replay, and outro script text before generating TTS audio."""
    return _with_app_context(
        automation.draft_round_audio_scripts,
        round_id=round_id,
        user_id=user_id,
        quiz_date=quiz_date,
        theme=theme,
        tone=tone,
        persist=persist,
    )


@mcp.tool()
def save_round_audio_scripts(
    round_id: int,
    scripts: dict[str, str],
    user_id: int | None = None,
    quiz_date: str | None = None,
    theme: str | None = None,
    tone: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Persist reviewable intro, replay, and outro script text for a round."""
    return _with_app_context(
        automation.save_round_audio_scripts,
        round_id=round_id,
        scripts=scripts,
        user_id=user_id,
        quiz_date=quiz_date,
        theme=theme,
        tone=tone,
        status=status,
    )


@mcp.tool()
def draft_round_track_hints(
    round_id: int,
    user_id: int | None = None,
    tone: str = "concise, playful, no title or artist spoilers",
    persist: bool = False,
) -> dict[str, Any]:
    """Draft per-track hint text that can be played before each first-listen snippet."""
    return _with_app_context(
        automation.draft_round_track_hints,
        round_id=round_id,
        user_id=user_id,
        tone=tone,
        persist=persist,
    )


@mcp.tool()
def save_round_track_hints(
    round_id: int,
    hints: list[dict[str, Any]],
    user_id: int | None = None,
    tone: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Persist reviewable per-track hint scripts with one-based positions."""
    return _with_app_context(
        automation.save_round_track_hints,
        round_id=round_id,
        hints=hints,
        user_id=user_id,
        tone=tone,
        status=status,
    )


@mcp.tool()
def list_round_audio_scripts(
    round_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List stored intro, replay, and outro script drafts."""
    return _with_app_context(
        automation.list_round_audio_scripts,
        round_id=round_id,
        user_id=user_id,
        status=status,
        limit=limit,
    )


@mcp.tool()
def update_round_audio_script(
    script_id: int,
    text: str | None = None,
    status: str | None = None,
    selected: bool | None = None,
) -> dict[str, Any]:
    """Edit, review, approve, reject, or select one stored script."""
    return _with_app_context(
        automation.update_round_audio_script,
        script_id=script_id,
        text=text,
        status=status,
        selected=selected,
    )


@mcp.tool()
def generate_tts_from_script(
    script_id: int,
    service: str = "openai",
    voice: str | None = None,
    model: str | None = None,
    stability: float | None = None,
    similarity: float | None = None,
) -> dict[str, Any]:
    """Generate and assign a custom MP3 from a reviewed or approved stored script."""
    return _with_app_context(
        automation.generate_tts_from_script,
        script_id=script_id,
        service=service,
        voice=voice,
        model=model,
        stability=stability,
        similarity=similarity,
    )


@mcp.tool()
def create_round_from_playlist(
    service_name: str,
    playlist_id_or_url: str,
    name: str | None = None,
    count: int = 8,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Import a Spotify or Deezer playlist and turn it into a quiz round."""
    try:
        return _with_app_context(
            automation.create_round_from_playlist,
            service_name=service_name,
            playlist_id_or_url=playlist_id_or_url,
            name=name,
            count=count,
            user_id=user_id,
        )
    except automation.AutomationError as exc:
        if exc.details:
            return exc.details
        raise


@mcp.tool()
def create_round_from_text_playlist(
    text: str,
    name: str | None = None,
    count: int = 8,
    min_confidence: float = 0.8,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Create a complete manual round from text rows that all resolve to catalog songs."""
    try:
        return _with_app_context(
            automation.create_round_from_text_playlist,
            text=text,
            name=name,
            count=count,
            min_confidence=min_confidence,
            user_id=user_id,
        )
    except automation.AutomationError as exc:
        if exc.details:
            return exc.details
        raise


@mcp.tool()
def round_analytics_summary(months: int = 6, limit: int = 20) -> dict[str, Any]:
    """Return catalog and round analytics for planning and fatigue checks."""
    return _with_app_context(
        automation.round_analytics_summary,
        months=months,
        limit=limit,
    )


@mcp.tool()
def generate_round_assets(
    round_id: int,
    user_id: int | None = None,
    include_pdf: bool = True,
    include_mp3: bool = True,
) -> dict[str, Any]:
    """Generate the PDF and/or MP3 files for a round."""
    return _with_app_context(
        automation.generate_round_assets,
        round_id=round_id,
        user_id=user_id,
        include_pdf=include_pdf,
        include_mp3=include_mp3,
    )


@mcp.tool()
def generate_round_assets_batch(
    round_ids: list[int],
    user_id: int | None = None,
    include_pdf: bool = True,
    include_mp3: bool = True,
) -> dict[str, Any]:
    """Generate PDF and/or MP3 files for several rounds."""
    return _with_app_context(
        automation.generate_round_assets_batch,
        round_ids=round_ids,
        user_id=user_id,
        include_pdf=include_pdf,
        include_mp3=include_mp3,
    )


@mcp.tool()
def inspect_round_mp3(path: str | None = None, round_id: int | None = None) -> dict[str, Any]:
    """Check a round MP3 for duration, loudness, clipping, and silence issues."""
    return _with_app_context(automation.inspect_mp3_quality, path=path, round_id=round_id)


@mcp.tool()
def inspect_round_pdf(path: str | None = None, round_id: int | None = None) -> dict[str, Any]:
    """Check that a round PDF exists and has a valid basic PDF structure."""
    return _with_app_context(automation.inspect_pdf_quality, path=path, round_id=round_id)


@mcp.tool()
def inspect_round_package(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Check previews, generated MP3 length, MP3 quality, and PDF integrity before sending."""
    return _with_app_context(
        automation.inspect_round_package,
        round_id=round_id,
        user_id=user_id,
        expected_song_count=expected_song_count,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )


@mcp.tool()
def round_repair_report(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Return package quality plus a human-readable repair report."""
    return _with_app_context(
        automation.round_repair_report,
        round_id=round_id,
        user_id=user_id,
        expected_song_count=expected_song_count,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )


@mcp.tool()
def inspect_round_package_batch(
    round_ids: list[int],
    user_id: int | None = None,
    expected_song_count: int = 8,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Inspect several round packages and return sendable vs repair-needed IDs."""
    return _with_app_context(
        automation.inspect_round_package_batch,
        round_ids=round_ids,
        user_id=user_id,
        expected_song_count=expected_song_count,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )


@mcp.tool()
def round_repair_plan(
    round_id: int,
    user_id: int | None = None,
    expected_song_count: int = 8,
    replacement_limit: int = 5,
    additional_limit: int = 10,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Return a read-only repair plan with replacement and add-song candidates."""
    return _with_app_context(
        automation.round_repair_plan,
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


@mcp.tool()
def round_repair_plan_batch(
    round_ids: list[int],
    user_id: int | None = None,
    expected_song_count: int = 8,
    replacement_limit: int = 5,
    additional_limit: int = 10,
    verify_previews: bool = False,
    min_preview_seconds: float = 20.0,
    max_preview_seconds: float = 35.0,
    duration_tolerance_seconds: float = automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Return read-only repair plans for several rounds in one call."""
    return _with_app_context(
        automation.round_repair_plan_batch,
        round_ids=round_ids,
        user_id=user_id,
        expected_song_count=expected_song_count,
        replacement_limit=replacement_limit,
        additional_limit=additional_limit,
        verify_previews=verify_previews,
        min_preview_seconds=min_preview_seconds,
        max_preview_seconds=max_preview_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )


@mcp.tool()
def schedule_round_email(
    round_id: int,
    scheduled_for: str,
    recipient: str | None = None,
    user_id: int | None = None,
    subject: str | None = None,
    body_text: str | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Schedule a round email for a future worker run."""
    return _with_app_context(
        automation.schedule_round_email,
        round_id=round_id,
        scheduled_for=scheduled_for,
        recipient=recipient,
        user_id=user_id,
        subject=subject,
        body_text=body_text,
        replace_existing=replace_existing,
    )


@mcp.tool()
def list_scheduled_round_emails(
    user_id: int | None = None,
    include_processed: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List scheduled round email exports."""
    return _with_app_context(
        automation.list_scheduled_round_emails,
        user_id=user_id,
        include_processed=include_processed,
        limit=limit,
    )


@mcp.tool()
def cancel_scheduled_round_email(
    export_id: int,
    user_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a pending scheduled round email before the scheduler sends it."""
    return _with_app_context(
        automation.cancel_scheduled_round_email,
        export_id=export_id,
        user_id=user_id,
        reason=reason,
    )


@mcp.tool()
def process_due_scheduled_round_emails(
    now: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Send scheduled round emails that are due and still pending."""
    return _with_app_context(
        automation.process_due_scheduled_round_emails,
        now=now,
        limit=limit,
    )


@mcp.tool()
def send_round_email(
    round_id: int,
    recipient: str | None = None,
    user_id: int | None = None,
    subject: str | None = None,
    body_text: str | None = None,
) -> dict[str, Any]:
    """Generate assets and email the completed round bundle."""
    try:
        return _with_app_context(
            automation.email_round,
            round_id=round_id,
            recipient=recipient,
            user_id=user_id,
            subject=subject,
            body_text=body_text,
        )
    except automation.AutomationError as exc:
        if exc.details:
            return exc.details
        raise


@mcp.tool()
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
    """Generate and assign a custom intro, replay, or outro TTS MP3."""
    return _with_app_context(
        automation.generate_tts_snippet,
        user_id=user_id,
        mp3_type=mp3_type,
        text=text,
        service=service,
        voice=voice,
        model=model,
        stability=stability,
        similarity=similarity,
    )


if __name__ == "__main__":
    mcp.run()
