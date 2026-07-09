"""Storage health checks for generated round artifacts."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from flask import current_app

ROUND_ARTIFACT_KINDS = {"mp3", "pdf"}
SUPPORTED_ROUND_ARTIFACT_BACKENDS = {"filesystem"}


class FilesystemRoundArtifactStore:
    """Filesystem implementation for generated round artifacts."""

    backend = "filesystem"

    def directory(self, kind: str) -> str:
        if kind == "mp3":
            return round_mp3_dir()
        if kind == "pdf":
            return round_pdf_dir()
        raise ValueError(f"Unsupported round artifact kind: {kind}")

    def filename(self, kind: str, round_id: int) -> str:
        if kind not in ROUND_ARTIFACT_KINDS:
            raise ValueError(f"Unsupported round artifact kind: {kind}")
        return f"round_{round_id}.{kind}"

    def path(self, kind: str, round_id: int) -> str:
        return os.path.join(self.directory(kind), self.filename(kind, round_id))

    def exists(self, kind: str, round_id: int) -> bool:
        return os.path.exists(self.path(kind, round_id))

    def size(self, kind: str, round_id: int) -> int:
        return os.path.getsize(self.path(kind, round_id))

    def read_bytes(self, kind: str, round_id: int) -> bytes:
        with open(self.path(kind, round_id), "rb") as artifact_file:
            return artifact_file.read()

    def write_bytes(self, kind: str, round_id: int, data: bytes) -> str:
        path = self.path(kind, round_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as artifact_file:
            artifact_file.write(data)
        return path

    def delete(self, kind: str, round_id: int) -> bool:
        path = self.path(kind, round_id)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True

    def inventory(self, kind: str) -> dict[str, Any]:
        if kind not in ROUND_ARTIFACT_KINDS:
            raise ValueError(f"Unsupported round artifact kind: {kind}")
        directory = self.directory(kind)
        result: dict[str, Any] = {
            "kind": kind,
            "file_count": 0,
            "total_bytes": 0,
            "ok": True,
            "error": None,
        }
        try:
            for name in os.listdir(directory):
                path = os.path.join(directory, name)
                if not os.path.isfile(path):
                    continue
                if not name.startswith("round_") or not name.endswith(f".{kind}"):
                    continue
                result["file_count"] += 1
                result["total_bytes"] += os.path.getsize(path)
        except OSError as exc:
            result["ok"] = False
            result["error"] = str(exc)
        return result


def round_artifact_store() -> FilesystemRoundArtifactStore:
    """Return the configured generated-round artifact store."""
    backend = current_app.config.get("ROUND_ARTIFACT_STORAGE_BACKEND", "filesystem")
    if backend not in SUPPORTED_ROUND_ARTIFACT_BACKENDS:
        raise RuntimeError(
            f"Unsupported ROUND_ARTIFACT_STORAGE_BACKEND={backend!r}. "
            "Only 'filesystem' is available in this deployment."
        )
    return FilesystemRoundArtifactStore()


def round_mp3_dir() -> str:
    """Return the configured MP3 artifact directory."""
    return current_app.config.get("ROUND_MP3_DIR", "/data/rounds")


def round_pdf_dir() -> str:
    """Return the configured PDF artifact directory."""
    return current_app.config.get("ROUND_PDF_DIR", "/data/pdfs")


def round_artifact_path(kind: str, round_id: int) -> str:
    """Return the resolved artifact path for a generated round file."""
    return round_artifact_store().path(kind, round_id)


def round_mp3_path(round_id: int) -> str:
    """Return the resolved MP3 artifact path for a round."""
    return round_artifact_path("mp3", round_id)


def round_pdf_path(round_id: int) -> str:
    """Return the resolved PDF artifact path for a round."""
    return round_artifact_path("pdf", round_id)


def round_artifact_storage_capabilities() -> dict[str, Any]:
    """Return backend-neutral capabilities for generated round artifact storage."""
    backend = current_app.config.get("ROUND_ARTIFACT_STORAGE_BACKEND", "filesystem")
    supported = backend in SUPPORTED_ROUND_ARTIFACT_BACKENDS
    capabilities: dict[str, Any] = {
        "backend": backend,
        "supported": supported,
        "supported_backends": sorted(SUPPORTED_ROUND_ARTIFACT_BACKENDS),
        "artifact_kinds": sorted(ROUND_ARTIFACT_KINDS),
        "supports_direct_file_paths": backend == "filesystem",
        "supports_cloud_storage": False,
        "supports_background_sync": False,
        "supports_shared_multi_replica": False,
        "mcp_asset_responses_stable": supported,
        "ha_blocking": backend == "filesystem",
        "configured_paths": {},
        "warnings": [],
    }
    if backend == "filesystem":
        capabilities["configured_paths"] = {
            "mp3": round_mp3_dir(),
            "pdf": round_pdf_dir(),
        }
        capabilities["warnings"].append(
            {
                "code": "filesystem_artifacts_block_multi_replica_ha",
                "severity": "warning",
                "message": (
                    "Generated MP3/PDF artifacts still use local filesystem paths; "
                    "use shared or object storage before treating web replicas as stateless."
                ),
                "hint": (
                    "Keep one web replica or move ROUND_ARTIFACT_STORAGE_BACKEND "
                    "to a shared/object backend once one is configured."
                ),
            }
        )
    elif not supported:
        capabilities["warnings"].append(
            {
                "code": "artifact_storage_backend_unsupported",
                "severity": "error",
                "message": f"Unsupported round artifact storage backend: {backend}",
                "hint": (
                    "Set ROUND_ARTIFACT_STORAGE_BACKEND=filesystem or install a "
                    "supported artifact backend."
                ),
            }
        )
    return capabilities


def round_artifact_storage_inventory(
    include_mp3: bool = True,
    include_pdf: bool = True,
) -> dict[str, Any]:
    """Return backend-neutral generated round artifact inventory."""
    backend = current_app.config.get("ROUND_ARTIFACT_STORAGE_BACKEND", "filesystem")
    inventory: dict[str, Any] = {
        "backend": backend,
        "ok": True,
        "artifacts": {},
        "total_file_count": 0,
        "total_bytes": 0,
        "issues": [],
    }
    if backend not in SUPPORTED_ROUND_ARTIFACT_BACKENDS:
        inventory["ok"] = False
        inventory["issues"].append(
            {
                "code": "artifact_storage_backend_unsupported",
                "severity": "error",
                "message": f"Unsupported round artifact storage backend: {backend}",
            }
        )
        return inventory

    store = round_artifact_store()
    kinds = []
    if include_mp3:
        kinds.append("mp3")
    if include_pdf:
        kinds.append("pdf")
    for kind in kinds:
        item = store.inventory(kind)
        inventory["artifacts"][kind] = item
        if not item["ok"]:
            inventory["ok"] = False
            inventory["issues"].append(
                {
                    "code": f"artifact_storage_{kind}_inventory_failed",
                    "severity": "warning",
                    "message": f"Could not inspect {kind.upper()} artifact inventory.",
                }
            )
            continue
        inventory["total_file_count"] += item["file_count"]
        inventory["total_bytes"] += item["total_bytes"]
    return inventory


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
    backend = current_app.config.get("ROUND_ARTIFACT_STORAGE_BACKEND", "filesystem")
    capabilities = round_artifact_storage_capabilities()
    inventory = round_artifact_storage_inventory(
        include_mp3=include_mp3,
        include_pdf=include_pdf,
    )
    if backend not in SUPPORTED_ROUND_ARTIFACT_BACKENDS:
        hint = (
            "Set ROUND_ARTIFACT_STORAGE_BACKEND=filesystem or install a "
            "supported artifact backend."
        )
        return {
            "ok": False,
            "backend": backend,
            "capabilities": capabilities,
            "inventory": inventory,
            "checks": [],
            "issues": [
                {
                    "code": "artifact_storage_backend_unsupported",
                    "severity": "error",
                    "message": f"Unsupported round artifact storage backend: {backend}",
                    "details": {
                        "backend": backend,
                        "hint": hint,
                    },
                }
            ],
            "hints": [hint],
        }

    checks = []
    if include_mp3:
        checks.append(
            _check_writable_directory(round_mp3_dir(), "Round MP3 directory", create=create)
        )
    if include_pdf:
        checks.append(
            _check_writable_directory(round_pdf_dir(), "Round PDF directory", create=create)
        )

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
        "backend": backend,
        "capabilities": capabilities,
        "inventory": inventory,
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


def round_artifact_storage_readiness(allow_ha_blocking: bool = False) -> dict[str, Any]:
    """Return operator readiness for generated round artifact storage."""
    health = check_round_artifact_storage()
    capabilities = health.get("capabilities") or {}
    ha_blocking = bool(capabilities.get("ha_blocking"))
    issues = list(health.get("issues") or [])
    ha_ready = bool(health.get("ok")) and not ha_blocking

    if ha_blocking:
        issues.append(
            {
                "code": "artifact_storage_ha_blocking",
                "severity": "warning",
                "message": (
                    "Generated round artifacts still use a backend that blocks "
                    "multi-replica HA."
                ),
                "details": {
                    "hint": (
                        "Use --allow-ha-blocking for single-writer deployments, "
                        "or move artifacts to shared/object storage before "
                        "scaling web replicas."
                    )
                },
            }
        )

    ok = bool(health.get("ok")) and (allow_ha_blocking or ha_ready)
    if not health.get("ok"):
        status = "error"
        next_action = "Fix artifact storage health before generating or delivering rounds."
    elif ha_blocking and not allow_ha_blocking:
        status = "warning"
        next_action = "Keep one web replica or move generated artifacts to shared/object storage."
    else:
        status = "ok"
        next_action = "Artifact storage is ready for the selected deployment mode."

    return {
        "ok": ok,
        "status": status,
        "allow_ha_blocking": allow_ha_blocking,
        "writable_ok": bool(health.get("ok")),
        "ha_ready": ha_ready,
        "backend": health.get("backend"),
        "capabilities": capabilities,
        "inventory": health.get("inventory", {}),
        "issues": issues,
        "next_action": next_action,
    }
