"""Tests for generated round artifact storage helpers."""

import os
from io import BytesIO

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


class _FakeS3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class _FakeS3Paginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, Bucket, Prefix):
        contents = [
            {"Key": key, "Size": len(value)}
            for key, value in self.client.objects.items()
            if key.startswith(Prefix)
        ]
        return [{"Contents": contents}]


class _FakeS3Client:
    def __init__(self):
        self.objects = {}

    def head_bucket(self, Bucket):
        return {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _FakeS3Error("404")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _FakeS3Error("404")
        return {"Body": BytesIO(self.objects[Key])}

    def download_fileobj(self, Bucket, Key, Fileobj):
        Fileobj.write(self.objects[Key])

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body.read() if hasattr(Body, "read") else Body
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)
        return {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _FakeS3Paginator(self)


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
        assert capabilities["supported_backends"] == ["filesystem", "s3"]
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


def test_s3_artifact_store_reads_writes_and_reports_shared_capabilities(app, monkeypatch, tmp_path):
    from musicround.helpers import storage_health

    client = _FakeS3Client()
    monkeypatch.setattr(storage_health, "_s3_client", lambda: client)
    with app.app_context():
        app.config.update(
            ROUND_ARTIFACT_STORAGE_BACKEND="s3",
            ROUND_ARTIFACT_S3_BUCKET="quiz-artifacts",
            ROUND_ARTIFACT_S3_PREFIX="production",
            ROUND_ARTIFACT_CACHE_DIR=str(tmp_path / "cache"),
        )
        store = round_artifact_store()
        path = store.write_bytes("mp3", 9, b"mp3-bytes")

        assert path.endswith("round_9.mp3")
        assert store.exists("mp3", 9) is True
        assert store.size("mp3", 9) == 9
        assert store.read_bytes("mp3", 9) == b"mp3-bytes"
        assert round_artifact_path("mp3", 9) == path
        assert round_artifact_storage_inventory(include_pdf=False)["total_bytes"] == 9
        health = check_round_artifact_storage(include_pdf=False)
        assert health["ok"] is True
        assert health["checks"][0]["label"] == "S3 artifact bucket"
        capabilities = round_artifact_storage_capabilities()
        assert capabilities["supports_cloud_storage"] is True
        assert capabilities["supports_shared_multi_replica"] is True
        assert capabilities["ha_blocking"] is False
        assert store.delete("mp3", 9) is True
        assert store.exists("mp3", 9) is False


def test_s3_artifact_storage_fails_closed_when_bucket_is_missing(app):
    with app.app_context():
        app.config["ROUND_ARTIFACT_STORAGE_BACKEND"] = "s3"
        app.config["ROUND_ARTIFACT_S3_BUCKET"] = ""

        health = check_round_artifact_storage()

        assert health["ok"] is False
        assert health["inventory"]["issues"][0]["code"] == "artifact_storage_not_configured"
        assert health["checks"][0]["code"] == "artifact_storage_not_writable"


def test_artifact_storage_fails_closed_for_unsupported_backend(app):
    with app.app_context():
        app.config["ROUND_ARTIFACT_STORAGE_BACKEND"] = "unsupported"

        health = check_round_artifact_storage()

        assert health["ok"] is False
        assert health["backend"] == "unsupported"
        assert health["capabilities"]["supported"] is False
        assert health["inventory"]["ok"] is False
        assert health["capabilities"]["ha_blocking"] is True
        assert health["issues"][0]["code"] == "artifact_storage_backend_unsupported"
        with pytest.raises(RuntimeError, match="Unsupported ROUND_ARTIFACT_STORAGE_BACKEND"):
            round_artifact_store()
