"""Storage health checks for generated round artifacts."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from flask import current_app


def round_mp3_dir() -> str:
    """Return the configured MP3 artifact directory."""
    return current_app.config.get("ROUND_MP3_DIR", "/data/rounds")


def round_pdf_dir() -> str:
    """Return the configured PDF artifact directory."""
    return current_app.config.get("ROUND_PDF_DIR", "/data/pdfs")


def _check_writable_directory(path: str, label: str, create: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "label": label,
        "path": path,
        "exists": os.path.exists(path),
        "is_dir": False,
        "writable": False,
        "ok": False,
        "code": None,
        "message": None,
        "hint": None,
    }

    if not result["exists"] and create:
        try:
            os.makedirs(path, exist_ok=True)
            result["exists"] = True
        except OSError as exc:
            result["code"] = "artifact_storage_missing"
            result["message"] = f"{label} does not exist and could not be created: {exc}"
            result["hint"] = f"Create {path} and make it writable by the QuizzicalBeats process."
            return result

    if not result["exists"]:
        result["code"] = "artifact_storage_missing"
        result["message"] = f"{label} does not exist: {path}"
        result["hint"] = f"Create {path} and make it writable by the QuizzicalBeats process."
        return result

    result["is_dir"] = os.path.isdir(path)
    if not result["is_dir"]:
        result["code"] = "artifact_storage_not_directory"
        result["message"] = f"{label} is not a directory: {path}"
        result["hint"] = f"Replace {path} with a writable directory."
        return result

    if not os.access(path, os.W_OK):
        result["code"] = "artifact_storage_not_writable"
        result["message"] = f"{label} is not writable: {path}"
        result["hint"] = f"Fix ownership or permissions for {path}."
        return result

    try:
        with tempfile.NamedTemporaryFile(prefix=".qb-write-", dir=path):
            pass
    except OSError as exc:
        result["code"] = "artifact_storage_not_writable"
        result["message"] = f"{label} failed a write probe: {exc}"
        result["hint"] = f"Fix ownership, permissions, or free space for {path}."
        return result

    result["writable"] = True
    result["ok"] = True
    return result


def check_round_artifact_storage(
    include_mp3: bool = True,
    include_pdf: bool = True,
    create: bool = False,
) -> dict[str, Any]:
    """Check directories required for round artifacts."""
    checks = []
    if include_mp3:
        checks.append(_check_writable_directory(round_mp3_dir(), "Round MP3 directory", create=create))
    if include_pdf:
        checks.append(_check_writable_directory(round_pdf_dir(), "Round PDF directory", create=create))

    issues = []
    for check in checks:
        if check["ok"]:
            continue
        issues.append(
            {
                "code": check["code"],
                "severity": "error",
                "message": check["message"],
                "details": {
                    "label": check["label"],
                    "path": check["path"],
                    "exists": check["exists"],
                    "is_dir": check["is_dir"],
                    "writable": check["writable"],
                    "hint": check["hint"],
                },
            }
        )

    return {
        "ok": not issues,
        "checks": checks,
        "issues": issues,
        "hints": [issue["details"]["hint"] for issue in issues],
    }


def require_round_artifact_storage(
    include_mp3: bool = True,
    include_pdf: bool = True,
    create: bool = False,
) -> dict[str, Any]:
    """Return healthy storage info or raise RuntimeError with details."""
    health = check_round_artifact_storage(
        include_mp3=include_mp3,
        include_pdf=include_pdf,
        create=create,
    )
    if health["ok"]:
        return health
    hints = "; ".join(health["hints"])
    raise RuntimeError(f"Round artifact storage is not ready. {hints}")


def storage_error_response() -> dict[str, Any]:
    """Return a compact user-facing payload for unhealthy artifact storage."""
    health = check_round_artifact_storage()
    return {
        "success": False,
        "error": "Round artifact storage is not ready.",
        "storage": health,
        "hint": "; ".join(health["hints"]),
    }
