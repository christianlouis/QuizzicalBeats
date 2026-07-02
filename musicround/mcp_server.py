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
def compile_round(
    name: str | None = None,
    round_type: str = "random",
    count: int = 8,
    criteria: str | None = None,
    song_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Compile songs into a named quiz round."""
    return _with_app_context(
        automation.create_round,
        name=name,
        round_type=round_type,
        count=count,
        criteria=criteria,
        song_ids=song_ids,
    )


@mcp.tool()
def rename_round(round_id: int, name: str | None) -> dict[str, Any]:
    """Set or clear the display name for a round."""
    return _with_app_context(automation.rename_round, round_id=round_id, name=name)


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
    duration_tolerance_seconds: float = 6.0,
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
