"""Tests for local performance smoke checks."""

from musicround.helpers.performance_smoke import run_performance_smoke
from musicround.models import Round, Song, User


def test_performance_smoke_runs_synthetic_checks_and_cleans_up(app):
    """Synthetic smoke checks should be self-contained and leave no fixture rows."""
    with app.app_context():
        result = run_performance_smoke(
            sample_size=12,
            include_synthetic=True,
            search_threshold_ms=10_000,
            import_threshold_ms=10_000,
            analytics_threshold_ms=10_000,
            round_review_threshold_ms=10_000,
        )

        assert result["ok"] is True
        assert result["synthetic"] is True
        assert result["sample_size"] == 12
        names = {check["name"] for check in result["checks"]}
        assert {
            "catalog_search",
            "playlist_import_parse",
            "mcp_round_analytics",
            "mcp_recent_usage",
            "round_review_payload",
        }.issubset(names)
        assert Song.query.filter(Song.source.like("perf-smoke-%")).count() == 0
        assert Round.query.filter(Round.name.like("Performance Smoke perf-smoke-%")).count() == 0
        assert User.query.filter(User.username.like("perf-smoke-%")).count() == 0


def test_performance_smoke_reports_threshold_failures(app):
    """Threshold failures should be returned as structured smoke output."""
    with app.app_context():
        result = run_performance_smoke(
            sample_size=8,
            include_synthetic=False,
            search_threshold_ms=0.0,
            import_threshold_ms=0.0,
            analytics_threshold_ms=0.0,
        )

        assert result["ok"] is False
        assert result["failed_checks"]
        assert all(check["duration_ms"] >= 0 for check in result["checks"])
