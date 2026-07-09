"""Tests for generated round artifact storage helpers."""

import os

import pytest

from musicround.helpers.storage_health import (
    check_round_artifact_storage,
    round_artifact_path,
    round_artifact_store,
    round_artifact_storage_capabilities,
    round_artifact_storage_inventory,
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


def test_filesystem_artifact_store_reports_inventory(app, tmp_path):
    with app.app_context():
        app.config["ROUND_MP3_DIR"] = str(tmp_path / "rounds")
        app.config["ROUND_PDF_DIR"] = str(tmp_path / "pdfs")
        os.makedirs(app.config["ROUND_MP3_DIR"], exist_ok=True)
        os.makedirs(app.config["ROUND_PDF_DIR"], exist_ok=True)
        store = round_artifact_store()
        store.write_bytes("mp3", 1, b"1234")
        store.write_bytes("pdf", 2, b"abcdef")
        (tmp_path / "rounds" / "ignore.tmp").write_bytes(b"not an artifact")

        inventory = round_artifact_storage_inventory()

        assert inventory["ok"] is True
        assert inventory["backend"] == "filesystem"
        assert inventory["artifacts"]["mp3"]["file_count"] == 1
        assert inventory["artifacts"]["mp3"]["total_bytes"] == 4
        assert inventory["artifacts"]["pdf"]["file_count"] == 1
        assert inventory["artifacts"]["pdf"]["total_bytes"] == 6
        assert inventory["total_file_count"] == 2
        assert inventory["total_bytes"] == 10
        assert "round_1.mp3" not in str(inventory)


def test_artifact_storage_health_reports_backend(app):
    with app.app_context():
        health = check_round_artifact_storage()

        assert health["ok"] is True
        assert health["backend"] == "filesystem"
        assert health["capabilities"]["supported"] is True
        assert health["capabilities"]["ha_blocking"] is True
        assert health["inventory"]["backend"] == "filesystem"
        assert "mp3" in health["inventory"]["artifacts"]
        assert "pdf" in health["inventory"]["artifacts"]
        assert {check["label"] for check in health["checks"]} == {
            "Round MP3 directory",
            "Round PDF directory",
        }


def test_filesystem_artifact_storage_capabilities_report_ha_warning(app):
    with app.app_context():
        capabilities = round_artifact_storage_capabilities()

        assert capabilities["backend"] == "filesystem"
        assert capabilities["supported_backends"] == ["filesystem"]
        assert capabilities["artifact_kinds"] == ["mp3", "pdf"]
        assert capabilities["supports_direct_file_paths"] is True
        assert capabilities["supports_cloud_storage"] is False
        assert capabilities["supports_background_sync"] is False
        assert capabilities["supports_shared_multi_replica"] is False
        assert capabilities["mcp_asset_responses_stable"] is True
        assert capabilities["ha_blocking"] is True
        assert capabilities["configured_paths"] == {
            "mp3": app.config["ROUND_MP3_DIR"],
            "pdf": app.config["ROUND_PDF_DIR"],
        }
        assert capabilities["warnings"][0]["code"] == (
            "filesystem_artifacts_block_multi_replica_ha"
        )


def test_artifact_storage_fails_closed_for_unsupported_backend(app):
    with app.app_context():
        app.config["ROUND_ARTIFACT_STORAGE_BACKEND"] = "s3"

        health = check_round_artifact_storage()

        assert health["ok"] is False
        assert health["backend"] == "s3"
        assert health["capabilities"]["supported"] is False
        assert health["inventory"]["ok"] is False
        assert health["capabilities"]["ha_blocking"] is False
        assert health["issues"][0]["code"] == "artifact_storage_backend_unsupported"
        with pytest.raises(RuntimeError, match="Unsupported ROUND_ARTIFACT_STORAGE_BACKEND"):
            round_artifact_store()
