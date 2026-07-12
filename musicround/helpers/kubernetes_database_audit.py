"""Credential-safe Kubernetes manifest audit for managed DB cutovers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from musicround.helpers.database_config import bool_from_config, is_legacy_data_sqlite_uri


DATABASE_KEYS = {
    "SQLALCHEMY_DATABASE_URI",
    "DATABASE_REQUIRE_MANAGED",
    "PGHOST",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPORT",
    "PGSSLMODE",
    "SQLALCHEMY_POSTGRES_SCHEME",
}
SENSITIVE_LITERAL_DATABASE_KEYS = {"SQLALCHEMY_DATABASE_URI", "PGPASSWORD"}
SENSITIVE_CONFIGMAP_DATABASE_KEYS = {"SQLALCHEMY_DATABASE_URI", "PGPASSWORD"}
SENSITIVE_RAW_SECRET_DATABASE_KEYS = {"SQLALCHEMY_DATABASE_URI", "PGPASSWORD"}
REQUIRED_EXTERNAL_SECRET_DATABASE_KEYS = {"SQLALCHEMY_DATABASE_URI", "PGPASSWORD"}
REQUIRED_SPLIT_POSTGRES_KEYS = {"PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"}
VALID_EXTERNAL_SECRET_STORE_KINDS = {"SecretStore", "ClusterSecretStore"}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
EXPECTED_WORKLOADS = {
    "quizzicalbeats": "web",
    "quizzicalbeats-mcp": "mcp",
}


@dataclass(frozen=True)
class KubernetesDocument:
    path: str
    index: int
    data: dict[str, Any]


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    resource: str | None = None,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "severity": severity,
        "message": message,
        "resource": resource,
        "hint": hint,
        "details": details or {},
    }
    return {key: value for key, value in payload.items() if value not in (None, {}, [])}


def _yaml_documents(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - only used without PyYAML installed
        raise RuntimeError("PyYAML is required for Kubernetes manifest auditing.") from exc

    with path.open("r", encoding="utf-8") as handle:
        loaded = list(yaml.safe_load_all(handle))
    return [doc for doc in loaded if isinstance(doc, dict)]


def _iter_manifest_files(paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for value in paths:
        path = Path(value)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.yaml")))
            files.extend(sorted(path.rglob("*.yml")))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            files.append(path)
    return sorted({item.resolve() for item in files if item.exists()})


def _load_documents(paths: Iterable[str | Path]) -> list[KubernetesDocument]:
    documents: list[KubernetesDocument] = []
    for path in _iter_manifest_files(paths):
        for index, data in enumerate(_yaml_documents(path), start=1):
            documents.append(KubernetesDocument(str(path), index, data))
    return documents


def _resource_name(doc: KubernetesDocument) -> str:
    data = doc.data
    metadata = data.get("metadata") or {}
    return f"{data.get('kind', 'Unknown')}/{metadata.get('name', 'unnamed')}"


def _container_specs(template_spec: dict[str, Any]) -> list[dict[str, Any]]:
    containers = list(template_spec.get("containers") or [])
    containers.extend(template_spec.get("initContainers") or [])
    return [container for container in containers if isinstance(container, dict)]


def _pod_template_spec(resource: dict[str, Any]) -> dict[str, Any]:
    kind = resource.get("kind")
    spec = resource.get("spec") or {}
    if kind == "CronJob":
        return (
            spec.get("jobTemplate", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
    return spec.get("template", {}).get("spec", {})


def _pod_template_metadata(resource: dict[str, Any]) -> dict[str, Any]:
    kind = resource.get("kind")
    spec = resource.get("spec") or {}
    if kind == "CronJob":
        return (
            spec.get("jobTemplate", {})
            .get("spec", {})
            .get("template", {})
            .get("metadata", {})
        )
    return spec.get("template", {}).get("metadata", {})


def _workload_replicas(resource: dict[str, Any]) -> int | None:
    kind = resource.get("kind")
    if kind not in {"Deployment", "StatefulSet"}:
        return None
    replicas = (resource.get("spec") or {}).get("replicas", 1)
    try:
        return int(replicas)
    except (TypeError, ValueError):
        return None


def _strategy_type(resource: dict[str, Any]) -> str | None:
    if resource.get("kind") != "Deployment":
        return None
    strategy = (resource.get("spec") or {}).get("strategy") or {}
    return strategy.get("type") or "RollingUpdate"


def _cronjob_concurrency_policy(resource: dict[str, Any]) -> str | None:
    if resource.get("kind") != "CronJob":
        return None
    return (resource.get("spec") or {}).get("concurrencyPolicy")


def _has_required_pod_affinity_to_app(template_spec: dict[str, Any], app_label: str) -> bool:
    affinity = template_spec.get("affinity") or {}
    pod_affinity = affinity.get("podAffinity") or {}
    required = pod_affinity.get("requiredDuringSchedulingIgnoredDuringExecution") or []
    for rule in required:
        selector = (rule.get("labelSelector") or {}).get("matchLabels") or {}
        if selector.get("app") == app_label:
            return True
    return False


def _env_from_names(container: dict[str, Any]) -> dict[str, list[str]]:
    config_maps = []
    secrets = []
    for entry in container.get("envFrom") or []:
        if not isinstance(entry, dict):
            continue
        config_name = (entry.get("configMapRef") or {}).get("name")
        secret_name = (entry.get("secretRef") or {}).get("name")
        if config_name:
            config_maps.append(config_name)
        if secret_name:
            secrets.append(secret_name)
    return {"config_maps": sorted(config_maps), "secrets": sorted(secrets)}


def _direct_env_keys(container: dict[str, Any]) -> list[str]:
    keys = []
    for entry in container.get("env") or []:
        if isinstance(entry, dict) and entry.get("name") in DATABASE_KEYS:
            keys.append(entry["name"])
    return sorted(keys)


def _literal_sensitive_database_env_keys(container: dict[str, Any]) -> list[str]:
    keys = []
    for entry in container.get("env") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("name")
        value = entry.get("value")
        if key in SENSITIVE_LITERAL_DATABASE_KEYS and value not in (None, ""):
            keys.append(key)
    return sorted(keys)


def _sensitive_configmap_database_keys(config_data: dict[str, Any]) -> list[str]:
    keys = []
    for key in SENSITIVE_CONFIGMAP_DATABASE_KEYS:
        value = config_data.get(key)
        if key == "SQLALCHEMY_DATABASE_URI" and is_legacy_data_sqlite_uri(value):
            continue
        if value not in (None, ""):
            keys.append(key)
    return sorted(keys)


def _sensitive_raw_secret_database_keys(secret_data: dict[str, Any]) -> list[str]:
    keys = set()
    for section_name in ("data", "stringData"):
        section = secret_data.get(section_name) or {}
        if not isinstance(section, dict):
            continue
        for key in SENSITIVE_RAW_SECRET_DATABASE_KEYS:
            if key in section:
                keys.add(key)
    return sorted(keys)


def _external_secret_keys(resource: dict[str, Any]) -> list[str]:
    keys = []
    for entry in (resource.get("spec") or {}).get("data") or []:
        if not isinstance(entry, dict):
            continue
        secret_key = entry.get("secretKey")
        if secret_key:
            keys.append(str(secret_key))
    return sorted(set(keys))


def _external_secret_uses_data_from(resource: dict[str, Any]) -> bool:
    data_from = (resource.get("spec") or {}).get("dataFrom") or []
    return any(isinstance(entry, dict) for entry in data_from)


def _external_secret_store_ref(resource: dict[str, Any]) -> dict[str, str]:
    store_ref = (resource.get("spec") or {}).get("secretStoreRef") or {}
    if not isinstance(store_ref, dict):
        return {}
    return {
        key: str(value)
        for key, value in store_ref.items()
        if key in {"kind", "name"} and value
    }


def _uses_data_mount(template_spec: dict[str, Any]) -> bool:
    for container in _container_specs(template_spec):
        for mount in container.get("volumeMounts") or []:
            if isinstance(mount, dict) and mount.get("mountPath") == "/data":
                return True
    return False


def _persistent_volume_claim_mounts(template_spec: dict[str, Any]) -> list[str]:
    volume_claims = {}
    for volume in template_spec.get("volumes") or []:
        if not isinstance(volume, dict):
            continue
        claim_name = (volume.get("persistentVolumeClaim") or {}).get("claimName")
        volume_name = volume.get("name")
        if volume_name and claim_name:
            volume_claims[str(volume_name)] = str(claim_name)

    mounted_claims = set()
    for container in _container_specs(template_spec):
        for mount in container.get("volumeMounts") or []:
            if not isinstance(mount, dict):
                continue
            claim_name = volume_claims.get(mount.get("name"))
            if claim_name:
                mounted_claims.add(claim_name)
    return sorted(mounted_claims)


def _has_topology_spread(template_spec: dict[str, Any]) -> bool:
    constraints = template_spec.get("topologySpreadConstraints") or []
    return any(isinstance(item, dict) and item.get("topologyKey") for item in constraints)


def _has_probe(containers: list[dict[str, Any]], probe_name: str) -> bool:
    return any(isinstance(container.get(probe_name), dict) for container in containers)


def _missing_resource_requirements(containers: list[dict[str, Any]]) -> list[str]:
    missing = []
    for container in containers:
        name = container.get("name") or "unnamed"
        resources = container.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        missing_keys = []
        for section_name, section in (("requests", requests), ("limits", limits)):
            for resource_name in ("cpu", "memory"):
                if resource_name not in section:
                    missing_keys.append(f"{section_name}.{resource_name}")
        if missing_keys:
            missing.append(f"{name}: {', '.join(missing_keys)}")
    return sorted(missing)


def _selector_matches_labels(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    match_labels = selector.get("matchLabels") or {}
    if not match_labels:
        return False
    return all(labels.get(key) == value for key, value in match_labels.items())


def _command_text(container: dict[str, Any]) -> str:
    parts = []
    for key in ("command", "args"):
        value = container.get(key) or []
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.extend(str(item) for item in value)
    return "\n".join(parts)


def audit_kubernetes_database_manifests(paths: Iterable[str | Path]) -> dict[str, Any]:
    """Audit Kubernetes manifests for managed-database cutover readiness."""
    documents = _load_documents(paths)
    issues: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []

    config_maps: dict[str, dict[str, str]] = {}
    raw_secret_key_sets: dict[str, list[str]] = {}
    external_secret_targets: set[str] = set()
    external_secret_summaries: dict[str, list[dict[str, Any]]] = {}
    persistent_volume_claims: dict[str, dict[str, Any]] = {}
    pod_disruption_budgets: list[dict[str, Any]] = []
    managed_guard_enabled = False

    for doc in documents:
        data = doc.data
        kind = data.get("kind")
        metadata = data.get("metadata") or {}
        name = metadata.get("name")
        namespace = metadata.get("namespace")
        resource = _resource_name(doc)
        if kind == "ConfigMap":
            config_data = data.get("data") or {}
            config_maps[str(name)] = config_data
            managed_guard_enabled = managed_guard_enabled or bool_from_config(
                config_data.get("DATABASE_REQUIRE_MANAGED")
            )
        elif kind == "Secret":
            secret_keys = _sensitive_raw_secret_database_keys(data)
            if secret_keys:
                raw_secret_key_sets[str(name)] = secret_keys
        elif kind == "ExternalSecret":
            target_name = (data.get("spec") or {}).get("target", {}).get("name")
            if target_name:
                target = str(target_name)
                external_secret_targets.add(target)
                external_secret_summaries.setdefault(target, []).append(
                    {
                        "resource": resource,
                        "secret_keys": _external_secret_keys(data),
                        "uses_data_from": _external_secret_uses_data_from(data),
                        "secret_store_ref": _external_secret_store_ref(data),
                    }
                )
        elif kind == "PersistentVolumeClaim":
            persistent_volume_claims[str(name)] = data.get("spec") or {}
        elif kind == "PodDisruptionBudget":
            pod_disruption_budgets.append(data.get("spec") or {})
        resources.append(
            {
                "resource": resource,
                "namespace": namespace,
                "path": doc.path,
                "document_index": doc.index,
            }
        )

    for name, config_data in config_maps.items():
        uri = config_data.get("SQLALCHEMY_DATABASE_URI")
        require_managed = config_data.get("DATABASE_REQUIRE_MANAGED")
        sensitive_config_keys = _sensitive_configmap_database_keys(config_data)
        if sensitive_config_keys:
            issues.append(
                _issue(
                    "database_secret_configmap_value",
                    "blocker",
                    "ConfigMap contains sensitive database configuration values.",
                    resource=f"ConfigMap/{name}",
                    hint=(
                        "Move database passwords and complete database URIs to "
                        "quizzicalbeats-secrets through the 1Password-backed "
                        "ExternalSecret flow."
                    ),
                    details={"keys": sensitive_config_keys},
                )
            )
        if is_legacy_data_sqlite_uri(uri):
            issues.append(
                _issue(
                    "legacy_sqlite_configmap",
                    "blocker",
                    "ConfigMap still sets the legacy SQLite database URI.",
                    resource=f"ConfigMap/{name}",
                    hint=(
                        "Remove SQLALCHEMY_DATABASE_URI from the ConfigMap or replace it "
                        "with managed SQL secret wiring before cutover."
                    ),
                )
            )
        if not bool_from_config(require_managed):
            issues.append(
                _issue(
                    "managed_guard_not_enabled",
                    "blocker",
                    "DATABASE_REQUIRE_MANAGED is not enabled in the ConfigMap.",
                    resource=f"ConfigMap/{name}",
                    hint="Set DATABASE_REQUIRE_MANAGED=true after managed SQL is configured.",
                )
            )

    for name, secret_keys in raw_secret_key_sets.items():
        issues.append(
            _issue(
                "database_secret_raw_manifest",
                "blocker",
                "Manifest contains a raw Kubernetes Secret with sensitive database keys.",
                resource=f"Secret/{name}",
                hint=(
                    "Reference CNPG-generated Secrets or use the 1Password-backed "
                    "ExternalSecret flow instead of committing Secret data to GitOps."
                ),
                details={"keys": secret_keys},
            )
        )

    workload_summaries: dict[str, dict[str, Any]] = {}
    for doc in documents:
        data = doc.data
        kind = data.get("kind")
        if kind not in WORKLOAD_KINDS:
            continue
        metadata = data.get("metadata") or {}
        name = str(metadata.get("name") or "")
        resource = _resource_name(doc)
        template_spec = _pod_template_spec(data)
        template_metadata = _pod_template_metadata(data)
        pod_labels = template_metadata.get("labels") or {}
        containers = _container_specs(template_spec)
        env_from = {"config_maps": set(), "secrets": set()}
        direct_database_env = set()
        literal_sensitive_database_env = set()
        command = "\n".join(_command_text(container) for container in containers)
        for container in containers:
            names = _env_from_names(container)
            env_from["config_maps"].update(names["config_maps"])
            env_from["secrets"].update(names["secrets"])
            direct_database_env.update(_direct_env_keys(container))
            literal_sensitive_database_env.update(
                _literal_sensitive_database_env_keys(container)
            )

        summary = {
            "resource": resource,
            "kind": kind,
            "name": name,
            "pod_labels": dict(sorted(pod_labels.items())),
            "replicas": _workload_replicas(data),
            "strategy": _strategy_type(data),
            "concurrency_policy": _cronjob_concurrency_policy(data),
            "env_from": {
                "config_maps": sorted(env_from["config_maps"]),
                "secrets": sorted(env_from["secrets"]),
            },
            "direct_database_env": sorted(direct_database_env),
            "literal_sensitive_database_env": sorted(literal_sensitive_database_env),
            "uses_data_mount": _uses_data_mount(template_spec),
            "persistent_volume_claim_mounts": _persistent_volume_claim_mounts(template_spec),
            "has_topology_spread": _has_topology_spread(template_spec),
            "has_readiness_probe": _has_probe(containers, "readinessProbe"),
            "has_liveness_probe": _has_probe(containers, "livenessProbe"),
            "missing_resource_requirements": _missing_resource_requirements(containers),
            "has_pod_disruption_budget": any(
                _selector_matches_labels(pdb.get("selector") or {}, pod_labels)
                for pdb in pod_disruption_budgets
            ),
            "requires_web_pod_affinity": _has_required_pod_affinity_to_app(
                template_spec,
                "quizzicalbeats",
            ),
            "delegates_to_web_pod": "kubectl" in command and "exec" in command,
            "runs_application_backup": "backup" in command and "create" in command,
        }
        workload_summaries[name] = summary

    for name, label in EXPECTED_WORKLOADS.items():
        summary = workload_summaries.get(name)
        if not summary:
            issues.append(
                _issue(
                    "expected_workload_missing",
                    "blocker",
                    f"Expected {label} workload is missing from the manifests.",
                    resource=name,
                )
            )
            continue
        if "quizzicalbeats-config" not in summary["env_from"]["config_maps"]:
            issues.append(
                _issue(
                    "database_config_not_shared",
                    "blocker",
                    "Workload does not import the shared QB ConfigMap.",
                    resource=summary["resource"],
                    hint="Use the shared ConfigMap so web, MCP, and jobs resolve the same DB config.",
                )
            )
        if "quizzicalbeats-secrets" not in summary["env_from"]["secrets"]:
            issues.append(
                _issue(
                    "database_secret_not_shared",
                    "blocker",
                    "Workload does not import the shared QB Secret.",
                    resource=summary["resource"],
                    hint="Use the shared Secret so managed DB credentials are available consistently.",
                )
            )
        if summary["literal_sensitive_database_env"]:
            issues.append(
                _issue(
                    "database_secret_literal_env",
                    "blocker",
                    "Workload defines sensitive database configuration as literal environment values.",
                    resource=summary["resource"],
                    hint=(
                        "Use secretKeyRef/envFrom through quizzicalbeats-secrets or "
                        "the 1Password-backed ExternalSecret flow."
                    ),
                    details={"keys": summary["literal_sensitive_database_env"]},
                )
            )
        if summary["direct_database_env"]:
            issues.append(
                _issue(
                    "database_direct_env_override",
                    "blocker",
                    "Workload defines database environment keys directly instead of relying only on the shared ConfigMap/Secret pair.",
                    resource=summary["resource"],
                    hint=(
                        "Remove direct DB env entries so web, MCP, and jobs all resolve "
                        "database config from quizzicalbeats-config and quizzicalbeats-secrets."
                    ),
                    details={"keys": summary["direct_database_env"]},
                )
            )
        if summary["uses_data_mount"]:
            issues.append(
                _issue(
                    "data_volume_still_mounted",
                    "warning",
                    "Workload still mounts /data; keep DB cutover separate from artifact storage removal.",
                    resource=summary["resource"],
                )
            )
        if summary["kind"] in {"Deployment", "StatefulSet"} and (summary["replicas"] or 1) < 2:
            issues.append(
                _issue(
                    "single_replica_workload",
                    "warning",
                    "Workload is configured for fewer than two replicas.",
                    resource=summary["resource"],
                    hint="Use at least two replicas with topology spread after state is externalized.",
                    details={"replicas": summary["replicas"] or 1},
                )
            )
        if (
            label in {"web", "mcp"}
            and summary["kind"] in {"Deployment", "StatefulSet"}
            and summary["missing_resource_requirements"]
        ):
            issues.append(
                _issue(
                    "resource_requirements_missing",
                    "warning",
                    "Workload containers do not define complete CPU/memory requests and limits.",
                    resource=summary["resource"],
                    hint="Set CPU and memory requests/limits so replicas can be scheduled predictably.",
                    details={"missing": summary["missing_resource_requirements"]},
                )
            )
        if (
            label in {"web", "mcp"}
            and summary["kind"] in {"Deployment", "StatefulSet"}
            and not summary["has_readiness_probe"]
        ):
            issues.append(
                _issue(
                    "readiness_probe_missing",
                    "warning",
                    "Workload has no readiness probe.",
                    resource=summary["resource"],
                    hint="Add a readiness probe so rollouts and traffic routing wait for QB startup.",
                )
            )
        if (
            label in {"web", "mcp"}
            and summary["kind"] in {"Deployment", "StatefulSet"}
            and not summary["has_liveness_probe"]
        ):
            issues.append(
                _issue(
                    "liveness_probe_missing",
                    "warning",
                    "Workload has no liveness probe.",
                    resource=summary["resource"],
                    hint="Add a liveness probe so Kubernetes can recover stuck app containers.",
                )
            )
        if (
            label in {"web", "mcp"}
            and summary["kind"] in {"Deployment", "StatefulSet"}
            and (summary["replicas"] or 1) >= 2
            and not summary["has_topology_spread"]
        ):
            issues.append(
                _issue(
                    "topology_spread_missing",
                    "warning",
                    "Replicated workload does not define topology spread constraints.",
                    resource=summary["resource"],
                    hint="Spread replicas across nodes or zones before claiming host-loss resilience.",
                )
            )
        if (
            label in {"web", "mcp"}
            and summary["kind"] in {"Deployment", "StatefulSet"}
            and (summary["replicas"] or 1) >= 2
            and not summary["has_pod_disruption_budget"]
        ):
            issues.append(
                _issue(
                    "pod_disruption_budget_missing",
                    "warning",
                    "Replicated workload has no matching PodDisruptionBudget.",
                    resource=summary["resource"],
                    hint="Add a PDB so voluntary disruptions do not drain every replica at once.",
                )
            )
        if summary["strategy"] == "Recreate":
            issues.append(
                _issue(
                    "recreate_deployment_strategy",
                    "warning",
                    "Deployment uses Recreate strategy, which prevents zero-downtime rollouts.",
                    resource=summary["resource"],
                    hint="Use RollingUpdate after SQLite/RWO coupling has been removed.",
                )
            )
    for summary in workload_summaries.values():
        if summary["requires_web_pod_affinity"]:
            issues.append(
                _issue(
                    "workload_same_node_affinity",
                    "warning",
                    "Workload requires scheduling on the same node as the web pod.",
                    resource=summary["resource"],
                    hint="Remove same-node affinity once backup/export no longer needs the web PVC.",
                )
            )
        if summary["kind"] == "CronJob" and summary["concurrency_policy"] != "Forbid":
            issues.append(
                _issue(
                    "cronjob_concurrency_not_forbid",
                    "warning",
                    "CronJob does not prevent overlapping runs.",
                    resource=summary["resource"],
                    hint=(
                        "Set concurrencyPolicy: Forbid for scheduled email, backup, "
                        "and repair jobs that must not overlap."
                    ),
                    details={"concurrency_policy": summary["concurrency_policy"] or "Allow"},
                )
            )
        if managed_guard_enabled and summary["runs_application_backup"]:
            issues.append(
                _issue(
                    "application_backup_scheduler_for_managed_db",
                    "warning",
                    "Backup workload still runs the SQLite-only application backup command.",
                    resource=summary["resource"],
                    hint=(
                        "Use native managed database backups or snapshots for the DB; "
                        "the app ZIP backup is not the managed SQL backup."
                    ),
                )
            )

    if "quizzicalbeats-secrets" not in external_secret_targets:
        issues.append(
            _issue(
                "external_secret_target_missing",
                "blocker",
                "No ExternalSecret targets the shared quizzicalbeats-secrets Secret.",
                hint="Wire managed DB credentials through the existing ExternalSecret flow.",
            )
        )
    else:
        secret_summaries = external_secret_summaries.get("quizzicalbeats-secrets") or []
        if len(secret_summaries) > 1:
            issues.append(
                _issue(
                    "external_secret_target_duplicate",
                    "blocker",
                    "Multiple ExternalSecrets target the shared quizzicalbeats-secrets Secret.",
                    hint=(
                        "Keep a single owner for quizzicalbeats-secrets so web, MCP, "
                        "and jobs do not see racing secret updates."
                    ),
                    details={
                        "resources": sorted(
                            summary["resource"] for summary in secret_summaries
                        )
                    },
                )
            )
        secret_summary = secret_summaries[0] if secret_summaries else {}
        secret_keys = set(secret_summary.get("secret_keys") or [])
        uses_data_from = bool(secret_summary.get("uses_data_from"))
        secret_store_ref = secret_summary.get("secret_store_ref") or {}
        config_keys = set()
        for config_data in config_maps.values():
            config_keys.update(str(key) for key in config_data)
        published_database_keys = config_keys | secret_keys
        has_database_key = bool(secret_keys & REQUIRED_EXTERNAL_SECRET_DATABASE_KEYS)
        if not secret_store_ref.get("name"):
            issues.append(
                _issue(
                    "external_secret_store_ref_missing",
                    "blocker",
                    "ExternalSecret does not reference a SecretStore or ClusterSecretStore.",
                    resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                    hint=(
                        "Set spec.secretStoreRef.name so the controller can sync "
                        "quizzicalbeats-secrets from the approved secret backend."
                    ),
                )
            )
        store_kind = secret_store_ref.get("kind")
        if store_kind and store_kind not in VALID_EXTERNAL_SECRET_STORE_KINDS:
            issues.append(
                _issue(
                    "external_secret_store_ref_kind_invalid",
                    "blocker",
                    "ExternalSecret references an unsupported secret store kind.",
                    resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                    hint="Use SecretStore or ClusterSecretStore in spec.secretStoreRef.kind.",
                    details={"kind": store_kind},
                )
            )
        if not has_database_key and uses_data_from:
            issues.append(
                _issue(
                    "external_secret_database_keys_unverifiable",
                    "warning",
                    "ExternalSecret uses dataFrom, so database credential keys cannot be statically verified.",
                    resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                    hint=(
                        "Confirm the external item exposes PGPASSWORD or SQLALCHEMY_DATABASE_URI "
                        "before cutover."
                    ),
                )
            )
        elif not has_database_key:
            issues.append(
                _issue(
                    "external_secret_database_keys_missing",
                    "blocker",
                    "ExternalSecret does not publish a database password or complete database URI key.",
                    resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                    hint=(
                        "Map PGPASSWORD or SQLALCHEMY_DATABASE_URI into "
                        "quizzicalbeats-secrets without exposing the value."
                    ),
                    details={"keys": sorted(secret_keys)},
                )
            )
        missing_split_keys = sorted(REQUIRED_SPLIT_POSTGRES_KEYS - published_database_keys)
        if "SQLALCHEMY_DATABASE_URI" not in secret_keys and missing_split_keys:
            if uses_data_from:
                issues.append(
                    _issue(
                        "managed_database_config_keys_unverifiable",
                        "warning",
                        "Managed database config uses dataFrom, so split PostgreSQL keys cannot be fully verified statically.",
                        resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                        hint=(
                            "Confirm PGHOST, PGDATABASE, PGUSER, and PGPASSWORD are present "
                            "before cutover, or map them explicitly."
                        ),
                        details={"missing_static_keys": missing_split_keys},
                    )
                )
            else:
                issues.append(
                    _issue(
                        "managed_database_config_keys_missing",
                        "blocker",
                        "Managed database config does not publish a full SQLAlchemy URI or complete split PostgreSQL keys.",
                        resource=secret_summary.get("resource") or "ExternalSecret/quizzicalbeats-secrets",
                        hint=(
                            "Provide SQLALCHEMY_DATABASE_URI through the shared Secret, or publish "
                            "PGHOST, PGDATABASE, PGUSER, and PGPASSWORD across the shared ConfigMap/Secret."
                        ),
                        details={"missing_keys": missing_split_keys},
                    )
                )

    for name, spec in persistent_volume_claims.items():
        access_modes = spec.get("accessModes") or []
        if "ReadWriteOnce" in access_modes:
            issues.append(
                _issue(
                    "rwo_persistent_volume_claim",
                    "warning",
                    "PersistentVolumeClaim uses ReadWriteOnce and cannot be mounted by multiple nodes.",
                    resource=f"PersistentVolumeClaim/{name}",
                    hint="Keep it only for artifacts, or replace with shared/object storage for HA.",
                    details={"access_modes": access_modes},
                )
            )
            consumers = sorted(
                summary["resource"]
                for summary in workload_summaries.values()
                if name in summary["persistent_volume_claim_mounts"]
            )
            if len(consumers) > 1:
                issues.append(
                    _issue(
                        "rwo_persistent_volume_claim_multi_consumer",
                        "blocker",
                        "ReadWriteOnce PersistentVolumeClaim is mounted by multiple QB workloads.",
                        resource=f"PersistentVolumeClaim/{name}",
                        hint=(
                            "Move shared artifacts to object/shared storage or keep the RWO claim "
                            "attached to only one workload before HA cutover."
                        ),
                        details={"workloads": consumers},
                    )
                )

    for name, summary in workload_summaries.items():
        if summary["delegates_to_web_pod"]:
            issues.append(
                _issue(
                    "scheduled_job_execs_web_pod",
                    "blocker",
                    "A workload delegates execution into the web pod instead of running the app image directly.",
                    resource=summary["resource"],
                    hint=(
                        "Run scheduled automation in the application image directly, "
                        "for example python /app/run.py scheduled-emails process-due --json."
                    ),
                )
            )

    blockers = [issue for issue in issues if issue["severity"] == "blocker"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    return {
        "ok": not blockers,
        "status": "blocked" if blockers else ("warning" if warnings else "ok"),
        "files_scanned": len(_iter_manifest_files(paths)),
        "resources_scanned": len(resources),
        "workloads": sorted(workload_summaries.values(), key=lambda item: item["resource"]),
        "issues": issues,
        "blocked_issues": blockers,
        "warnings": warnings,
        "guidance": [
            "This audit checks manifest shape and key names only; it never reads secret values.",
            "Run it before the live managed database cutover and again after GitOps changes land.",
        ],
    }
