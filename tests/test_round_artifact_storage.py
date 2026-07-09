"""Tests for generated round artifact storage helpers."""

import os

import pytest

from musicround.helpers.storage_health import (
    check_round_artifact_storage,
    round_artifact_path,
    round_artifact_store,
    round_mp3_path,
    round_pdf_path,
)


def test_filesystem_artifact_store_resolves_round_paths(app):
    with app.app_context():
        assert round_mp3_path(42) == os.path.join(app.config["ROUND_MP3_DIR"], "round_42.mp3")
        assert round_pdf_path(42) == os.path.join(app.config["ROUND_PDF_DIR"], "round_42.pdf")
        assert round_artifact_path("mp3", 7).endswith("round_7.mp3")
        assert round_artifact_path("pdf", 7).endswith("round_7.pdf")


def test_filesystem_artifact_store_reads_writes_and_deletes(app):
    with app.app_context():
        store = round_artifact_store()
        path = store.write_bytes("pdf", 5, b"%PDF-1.4\n%%EOF")

        assert path == round_pdf_path(5)
        assert store.exists("pdf", 5) is True
        assert store.size("pdf", 5) == len(b"%PDF-1.4\n%%EOF")
        assert store.read_bytes("pdf", 5) == b"%PDF-1.4\n%%EOF"
        assert store.delete("pdf", 5) is True
        assert store.exists("pdf", 5) is False
        assert store.delete("pdf", 5) is False


def test_artifact_storage_health_reports_backend(app):
    with app.app_context():
        health = check_round_artifact_storage()

        assert health["ok"] is True
        assert health["backend"] == "filesystem"
        assert {check["label"] for check in health["checks"]} == {
            "Round MP3 directory",
            "Round PDF directory",
        }


def test_artifact_storage_fails_closed_for_unsupported_backend(app):
    with app.app_context():
        app.config["ROUND_ARTIFACT_STORAGE_BACKEND"] = "s3"

        health = check_round_artifact_storage()

        assert health["ok"] is False
        assert health["backend"] == "s3"
        assert health["issues"][0]["code"] == "artifact_storage_backend_unsupported"
        with pytest.raises(RuntimeError, match="Unsupported ROUND_ARTIFACT_STORAGE_BACKEND"):
            round_artifact_store()
