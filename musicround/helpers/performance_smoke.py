"""Local performance smoke checks for catalog, round, and MCP-like workflows."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from musicround import db
from musicround.models import Round, Song, User
from musicround.services import automation


@dataclass(frozen=True)
class PerformanceCheck:
    name: str
    threshold_ms: float
    operation: Callable[[], dict[str, Any]]


def _duration_ms(operation: Callable[[], dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    started = perf_counter()
    details = operation()
    return (perf_counter() - started) * 1000, details


def _playlist_text(size: int) -> str:
    return "\n".join(
        f"Smoke Artist {index} - Smoke Song {index}"
        for index in range(1, size + 1)
    )


def _create_synthetic_fixture(size: int) -> dict[str, Any]:
    marker = f"perf-smoke-{uuid4().hex}"
    user = User(username=marker[:80], email=f"{marker}@example.test")
    db.session.add(user)
    db.session.flush()

    songs = []
    for index in range(1, size + 1):
        song = Song(
            title=f"Smoke Song {index}",
            artist=f"Smoke Artist {index % 17}",
            genre="Rock" if index % 2 else "Pop",
            year=1980 + (index % 45),
            tempo=90 + (index % 70),
            preview_url=f"https://example.test/{marker}/{index}.mp3",
            used_count=index % 5,
            source=marker,
        )
        songs.append(song)
        db.session.add(song)
    db.session.flush()

    round_obj = Round(
        name=f"Performance Smoke {marker}",
        round_type="manual",
        round_criteria_used="Performance smoke synthetic fixture",
        songs=",".join(str(song.id) for song in songs[:8]),
        user_id=user.id,
        review_status="draft",
    )
    db.session.add(round_obj)
    db.session.commit()
    return {"marker": marker, "user_id": user.id, "round_id": round_obj.id}


def _cleanup_synthetic_fixture(marker: str) -> None:
    rounds = Round.query.filter(Round.name.like(f"Performance Smoke {marker}%")).all()
    for round_obj in rounds:
        db.session.delete(round_obj)
    songs = Song.query.filter_by(source=marker).all()
    for song in songs:
        db.session.delete(song)
    user = User.query.filter_by(username=marker[:80]).first()
    if user:
        db.session.delete(user)
    db.session.commit()


def run_performance_smoke(
    *,
    sample_size: int = 250,
    include_synthetic: bool = False,
    search_threshold_ms: float = 250.0,
    import_threshold_ms: float = 250.0,
    analytics_threshold_ms: float = 500.0,
    round_review_threshold_ms: float = 750.0,
) -> dict[str, Any]:
    """Run bounded performance checks that agents and CI can execute locally."""
    if sample_size < 8 or sample_size > 5000:
        raise ValueError("sample_size must be between 8 and 5000.")

    fixture: dict[str, Any] | None = None
    if include_synthetic:
        fixture = _create_synthetic_fixture(sample_size)

    try:
        checks: list[PerformanceCheck] = [
            PerformanceCheck(
                "catalog_search",
                search_threshold_ms,
                lambda: automation.find_songs(
                    query="Smoke" if include_synthetic else "a",
                    has_preview=True if include_synthetic else None,
                    limit=20,
                ),
            ),
            PerformanceCheck(
                "playlist_import_parse",
                import_threshold_ms,
                lambda: automation.parse_text_playlist(
                    _playlist_text(sample_size),
                    limit=min(sample_size, 500),
                ),
            ),
            PerformanceCheck(
                "mcp_round_analytics",
                analytics_threshold_ms,
                lambda: automation.round_analytics_summary(months=12, limit=20),
            ),
            PerformanceCheck(
                "mcp_recent_usage",
                analytics_threshold_ms,
                lambda: automation.recent_usage_summary(months=6, limit=25),
            ),
        ]
        if fixture:
            checks.append(
                PerformanceCheck(
                    "round_review_payload",
                    round_review_threshold_ms,
                    lambda: automation.round_review_payload(
                        fixture["round_id"],
                        user_id=fixture["user_id"],
                    ),
                )
            )

        results = []
        for check in checks:
            duration, details = _duration_ms(check.operation)
            results.append(
                {
                    "name": check.name,
                    "duration_ms": round(duration, 3),
                    "threshold_ms": check.threshold_ms,
                    "ok": duration <= check.threshold_ms,
                    "details": _summarize_details(details),
                }
            )

        failed = [result for result in results if not result["ok"]]
        return {
            "ok": not failed,
            "sample_size": sample_size,
            "synthetic": bool(include_synthetic),
            "checks": results,
            "failed_checks": failed,
            "guidance": [
                "Run this locally after search, import, round-rendering, or MCP changes.",
                "Use --synthetic for a self-contained dataset that is cleaned up after the run.",
            ],
        }
    finally:
        if fixture:
            _cleanup_synthetic_fixture(fixture["marker"])


def _summarize_details(details: dict[str, Any]) -> dict[str, Any]:
    if "songs" in details:
        return {
            "count": details.get("count"),
            "total": details.get("total"),
            "cache": details.get("cache"),
            "analytics": details.get("analytics"),
        }
    if "candidates" in details:
        return {
            "count": details.get("count"),
            "low_confidence_count": details.get("low_confidence_count"),
            "ready_for_import": details.get("ready_for_import"),
        }
    if "catalog" in details:
        return {
            "catalog": details.get("catalog"),
            "rounds": details.get("rounds"),
            "recommendations": details.get("recommendations"),
        }
    if "recent_rounds" in details:
        return {
            "round_count": details.get("round_count"),
            "frequent_song_count": len(details.get("frequent_songs", [])),
        }
    if "round" in details:
        return {
            "round_id": details["round"].get("id"),
            "song_count": len(details.get("songs", [])),
            "quality_status": (details.get("quality") or {}).get("status"),
        }
    return {"keys": sorted(details.keys())[:12]}
