"""Application data-path helpers."""

from __future__ import annotations

import os

from flask import current_app


def app_data_dir() -> str:
    """Return the configured application data directory."""
    return current_app.config.get("DATA_DIR", "/data")


def app_data_path(*parts: str) -> str:
    """Return a path below the configured application data directory."""
    return os.path.join(app_data_dir(), *parts)


def backup_dir() -> str:
    """Return the configured backup directory."""
    return app_data_path("backups")


def custom_mp3_dir() -> str:
    """Return the configured custom MP3 base directory."""
    return app_data_path("custommp3")
