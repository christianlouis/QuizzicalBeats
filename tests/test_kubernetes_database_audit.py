"""Tests for credential-safe Kubernetes managed DB manifest audits."""

from musicround.helpers.kubernetes_database_audit import audit_kubernetes_database_manifests


LEGACY_MANIFEST = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: quizzicalbeats-config
data:
  SQLALCHEMY_DATABASE_URI: sqlite:////data/song_data.db
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: quizzicalbeats-secrets
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: quizzicalbeats-secrets
  data:
    - secretKey: PGPASSWORD
      remoteRef:
        key: quizzicalbeats
        property: PGPASSWORD
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      containers:
        - name: web
          readinessProbe:
            httpGet:
              path: /healthz
              port: 5000
          livenessProbe:
            httpGet:
              path: /healthz
              port: 5000
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
          volumeMounts:
            - name: data
              mountPath: /data
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: quizzicalbeats-data
spec:
  accessModes: [ReadWriteOnce]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats-mcp
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: mcp
          readinessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          livenessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
            limits:
              cpu: 250m
              memory: 256Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: quizzicalbeats-backup
spec:
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          affinity:
            podAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                - labelSelector:
                    matchLabels:
                      app: quizzicalbeats
                  topologyKey: kubernetes.io/hostname
          containers:
            - name: backup
              envFrom:
                - configMapRef:
                    name: quizzicalbeats-config
                - secretRef:
                    name: quizzicalbeats-secrets
"""


READY_MANIFEST = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: quizzicalbeats-config
data:
  DATABASE_REQUIRE_MANAGED: "true"
  PGHOST: quizzicalbeats-db-rw.quizzicalbeats.svc
  PGDATABASE: quizzicalbeats
  PGUSER: quizzicalbeats
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: quizzicalbeats-secrets
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: quizzicalbeats-secrets
  data:
    - secretKey: PGPASSWORD
      remoteRef:
        key: quizzicalbeats
        property: PGPASSWORD
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats
spec:
  replicas: 2
  template:
    metadata:
      labels:
        app: quizzicalbeats
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: quizzicalbeats
      containers:
        - name: web
          readinessProbe:
            httpGet:
              path: /healthz
              port: 5000
          livenessProbe:
            httpGet:
              path: /healthz
              port: 5000
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: quizzicalbeats
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: quizzicalbeats
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats-mcp
spec:
  replicas: 2
  template:
    metadata:
      labels:
        app: quizzicalbeats-mcp
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: quizzicalbeats-mcp
      containers:
        - name: mcp
          readinessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          livenessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
            limits:
              cpu: 250m
              memory: 256Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: quizzicalbeats-mcp
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: quizzicalbeats-mcp
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: quizzicalbeats-backup
spec:
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              envFrom:
                - configMapRef:
                    name: quizzicalbeats-config
                - secretRef:
                    name: quizzicalbeats-secrets
"""


def test_manifest_audit_blocks_legacy_sqlite_configmap(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(LEGACY_MANIFEST, encoding="utf-8")

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert result["status"] == "blocked"
    codes = {issue["code"] for issue in result["blocked_issues"]}
    assert "legacy_sqlite_configmap" in codes
    assert "managed_guard_not_enabled" in codes
    assert "/data/song_data.db" not in repr(result)
    warning_codes = {issue["code"] for issue in result["warnings"]}
    assert "single_replica_workload" in warning_codes
    assert "recreate_deployment_strategy" in warning_codes
    assert "rwo_persistent_volume_claim" in warning_codes
    assert "workload_same_node_affinity" in warning_codes


def test_manifest_audit_accepts_managed_guard_and_shared_env(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(READY_MANIFEST, encoding="utf-8")

    result = audit_kubernetes_database_manifests([tmp_path])

    assert result["ok"] is True
    assert result["blocked_issues"] == []
    assert result["warnings"] == []
    assert result["files_scanned"] == 1
    assert {
        item["name"] for item in result["workloads"]
    } == {"quizzicalbeats", "quizzicalbeats-mcp", "quizzicalbeats-backup"}


def test_manifest_audit_blocks_sensitive_database_configmap_without_leaking_values(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            '  DATABASE_REQUIRE_MANAGED: "true"\n',
            '  DATABASE_REQUIRE_MANAGED: "true"\n'
            '  SQLALCHEMY_DATABASE_URI: "postgresql://qb:redaction-fixture@db/qb"\n',
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "database_secret_configmap_value"
        and issue["resource"] == "ConfigMap/quizzicalbeats-config"
        and issue["details"]["keys"] == ["SQLALCHEMY_DATABASE_URI"]
        for issue in result["blocked_issues"]
    )
    assert "redaction-fixture" not in repr(result)
    assert "postgresql://qb" not in repr(result)


def test_manifest_audit_blocks_raw_database_secret_manifest_without_leaking_values(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST
        + """
---
apiVersion: v1
kind: Secret
metadata:
  name: quizzicalbeats-secrets
data:
  PGPASSWORD: cmVkYWN0aW9uLWZpeHR1cmU=
stringData:
  SQLALCHEMY_DATABASE_URI: postgresql://qb:raw-uri-fixture@db/qb
""",
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "database_secret_raw_manifest"
        and issue["resource"] == "Secret/quizzicalbeats-secrets"
        and issue["details"]["keys"] == ["PGPASSWORD", "SQLALCHEMY_DATABASE_URI"]
        for issue in result["blocked_issues"]
    )
    assert "raw-uri-fixture" not in repr(result)
    assert "cmVkYWN0aW9uLWZpeHR1cmU=" not in repr(result)


def test_manifest_audit_blocks_external_secret_without_database_credential_key(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "  data:\n"
            "    - secretKey: PGPASSWORD\n"
            "      remoteRef:\n"
            "        key: quizzicalbeats\n"
            "        property: PGPASSWORD\n",
            "  data:\n"
            "    - secretKey: SMTP_PASSWORD\n"
            "      remoteRef:\n"
            "        key: quizzicalbeats\n"
            "        property: SMTP_PASSWORD\n",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "external_secret_database_keys_missing"
        and issue["resource"] == "ExternalSecret/quizzicalbeats-secrets"
        and issue["details"]["keys"] == ["SMTP_PASSWORD"]
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_blocks_duplicate_external_secret_target(tmp_path):
    duplicate = """
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: quizzicalbeats-secrets-copy
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: quizzicalbeats-secrets
  data:
    - secretKey: PGPASSWORD
      remoteRef:
        key: quizzicalbeats-copy
        property: PGPASSWORD
"""
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(READY_MANIFEST + duplicate, encoding="utf-8")

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "external_secret_target_duplicate"
        and issue["details"]["resources"] == [
            "ExternalSecret/quizzicalbeats-secrets",
            "ExternalSecret/quizzicalbeats-secrets-copy",
        ]
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_blocks_incomplete_split_postgres_keys(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace("  PGUSER: quizzicalbeats\n", ""),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "managed_database_config_keys_missing"
        and issue["resource"] == "ExternalSecret/quizzicalbeats-secrets"
        and issue["details"]["missing_keys"] == ["PGUSER"]
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_blocks_external_secret_without_store_reference(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "  secretStoreRef:\n"
            "    kind: ClusterSecretStore\n"
            "    name: onepassword\n",
            "",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "external_secret_store_ref_missing"
        and issue["resource"] == "ExternalSecret/quizzicalbeats-secrets"
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_blocks_external_secret_with_invalid_store_kind(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace("    kind: ClusterSecretStore\n", "    kind: VaultStore\n"),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "external_secret_store_ref_kind_invalid"
        and issue["resource"] == "ExternalSecret/quizzicalbeats-secrets"
        and issue["details"]["kind"] == "VaultStore"
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_warns_when_external_secret_database_keys_use_data_from(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "  data:\n"
            "    - secretKey: PGPASSWORD\n"
            "      remoteRef:\n"
            "        key: quizzicalbeats\n"
            "        property: PGPASSWORD\n",
            "  dataFrom:\n"
            "    - extract:\n"
            "        key: quizzicalbeats\n",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is True
    assert result["status"] == "warning"
    assert any(
        issue["code"] == "external_secret_database_keys_unverifiable"
        and issue["resource"] == "ExternalSecret/quizzicalbeats-secrets"
        for issue in result["warnings"]
    )


def test_manifest_audit_flags_missing_shared_secret(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "            - secretRef:\n                name: quizzicalbeats-secrets\n",
            "",
            1,
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "database_secret_not_shared"
        and issue["resource"] == "Deployment/quizzicalbeats"
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_blocks_literal_sensitive_database_env_without_leaking_values(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "          envFrom:\n"
            "            - configMapRef:\n",
            "          env:\n"
            "            - name: PGPASSWORD\n"
            "              value: redaction-fixture-value\n"
            "          envFrom:\n"
            "            - configMapRef:\n",
            1,
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "database_secret_literal_env"
        and issue["resource"] == "Deployment/quizzicalbeats"
        and issue["details"]["keys"] == ["PGPASSWORD"]
        for issue in result["blocked_issues"]
    )
    assert "redaction-fixture-value" not in repr(result)


def test_manifest_audit_blocks_direct_database_env_override(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "          envFrom:\n"
            "            - configMapRef:\n",
            "          env:\n"
            "            - name: PGHOST\n"
            "              valueFrom:\n"
            "                configMapKeyRef:\n"
            "                  name: other-db-config\n"
            "                  key: PGHOST\n"
            "          envFrom:\n"
            "            - configMapRef:\n",
            1,
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "database_direct_env_override"
        and issue["resource"] == "Deployment/quizzicalbeats"
        and issue["details"]["keys"] == ["PGHOST"]
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_warns_when_managed_db_uses_app_backup_command(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace(
            "            - name: backup\n"
            "              envFrom:\n",
            "            - name: backup\n"
            "              command: [\"python\", \"/app/run.py\", \"backup\", \"create\", \"--auto\"]\n"
            "              envFrom:\n",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is True
    assert result["status"] == "warning"
    assert any(
        issue["code"] == "application_backup_scheduler_for_managed_db"
        and issue["resource"] == "CronJob/quizzicalbeats-backup"
        for issue in result["warnings"]
    )


def test_manifest_audit_blocks_scheduled_job_execing_web_pod(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST
        + """
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: quizzicalbeats-scheduled-email
spec:
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: scheduled-email
              image: alpine/k8s:1.34.4
              command:
                - sh
                - -ec
                - |
                  pod="$(kubectl get pod -l app=quizzicalbeats -o name | head -n1)"
                  kubectl exec "$pod" -- python -c "print('process due')"
""",
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "scheduled_job_execs_web_pod"
        and issue["resource"] == "CronJob/quizzicalbeats-scheduled-email"
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_warns_for_replicas_without_spread_or_pdb(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST
        .replace(
            "      topologySpreadConstraints:\n"
            "        - maxSkew: 1\n"
            "          topologyKey: kubernetes.io/hostname\n"
            "          whenUnsatisfiable: DoNotSchedule\n"
            "          labelSelector:\n"
            "            matchLabels:\n"
            "              app: quizzicalbeats\n",
            "",
        )
        .replace(
            "---\n"
            "apiVersion: policy/v1\n"
            "kind: PodDisruptionBudget\n"
            "metadata:\n"
            "  name: quizzicalbeats\n"
            "spec:\n"
            "  minAvailable: 1\n"
            "  selector:\n"
            "    matchLabels:\n"
            "      app: quizzicalbeats\n",
            "",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])
    web_warning_codes = {
        issue["code"]
        for issue in result["warnings"]
        if issue.get("resource") == "Deployment/quizzicalbeats"
    }

    assert result["ok"] is True
    assert "topology_spread_missing" in web_warning_codes
    assert "pod_disruption_budget_missing" in web_warning_codes


def test_manifest_audit_blocks_rwo_pvc_mounted_by_multiple_workloads(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        """
apiVersion: v1
kind: ConfigMap
metadata:
  name: quizzicalbeats-config
data:
  DATABASE_REQUIRE_MANAGED: "true"
  PGHOST: quizzicalbeats-db-rw.quizzicalbeats.svc
  PGDATABASE: quizzicalbeats
  PGUSER: quizzicalbeats
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: quizzicalbeats-secrets
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: quizzicalbeats-secrets
  data:
    - secretKey: PGPASSWORD
      remoteRef:
        key: quizzicalbeats
        property: PGPASSWORD
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats
spec:
  replicas: 2
  template:
    metadata:
      labels:
        app: quizzicalbeats
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: quizzicalbeats-data
      containers:
        - name: web
          readinessProbe:
            httpGet:
              path: /healthz
              port: 5000
          livenessProbe:
            httpGet:
              path: /healthz
              port: 5000
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
          volumeMounts:
            - name: data
              mountPath: /data
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: quizzicalbeats
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: quizzicalbeats
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quizzicalbeats-mcp
spec:
  replicas: 2
  template:
    metadata:
      labels:
        app: quizzicalbeats-mcp
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: quizzicalbeats-data
      containers:
        - name: mcp
          readinessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          livenessProbe:
            exec:
              command: ["python", "/app/run.py", "database", "status"]
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
            limits:
              cpu: 250m
              memory: 256Mi
          envFrom:
            - configMapRef:
                name: quizzicalbeats-config
            - secretRef:
                name: quizzicalbeats-secrets
          volumeMounts:
            - name: data
              mountPath: /data
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: quizzicalbeats-mcp
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: quizzicalbeats-mcp
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: quizzicalbeats-backup
spec:
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              envFrom:
                - configMapRef:
                    name: quizzicalbeats-config
                - secretRef:
                    name: quizzicalbeats-secrets
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: quizzicalbeats-data
spec:
  accessModes: [ReadWriteOnce]
""",
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is False
    assert any(
        issue["code"] == "rwo_persistent_volume_claim_multi_consumer"
        and issue["resource"] == "PersistentVolumeClaim/quizzicalbeats-data"
        and issue["details"]["workloads"] == [
            "Deployment/quizzicalbeats",
            "Deployment/quizzicalbeats-mcp",
        ]
        for issue in result["blocked_issues"]
    )


def test_manifest_audit_warns_when_app_workloads_have_no_probes(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST
        .replace(
            "          readinessProbe:\n"
            "            httpGet:\n"
            "              path: /healthz\n"
            "              port: 5000\n"
            "          livenessProbe:\n"
            "            httpGet:\n"
            "              path: /healthz\n"
            "              port: 5000\n",
            "",
        )
        .replace(
            "          readinessProbe:\n"
            "            exec:\n"
            "              command: [\"python\", \"/app/run.py\", \"database\", \"status\"]\n"
            "          livenessProbe:\n"
            "            exec:\n"
            "              command: [\"python\", \"/app/run.py\", \"database\", \"status\"]\n",
            "",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])
    warning_codes = {issue["code"] for issue in result["warnings"]}

    assert result["ok"] is True
    assert "readiness_probe_missing" in warning_codes
    assert "liveness_probe_missing" in warning_codes


def test_manifest_audit_warns_when_app_workloads_lack_resources(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST
        .replace(
            "          resources:\n"
            "            requests:\n"
            "              cpu: 100m\n"
            "              memory: 256Mi\n"
            "            limits:\n"
            "              cpu: 500m\n"
            "              memory: 512Mi\n",
            "",
        )
        .replace(
            "          resources:\n"
            "            requests:\n"
            "              cpu: 50m\n"
            "              memory: 128Mi\n"
            "            limits:\n"
            "              cpu: 250m\n"
            "              memory: 256Mi\n",
            "",
        ),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])
    warnings = [
        issue
        for issue in result["warnings"]
        if issue["code"] == "resource_requirements_missing"
    ]

    assert result["ok"] is True
    assert {issue["resource"] for issue in warnings} == {
        "Deployment/quizzicalbeats",
        "Deployment/quizzicalbeats-mcp",
    }
    assert all("missing" in issue["details"] for issue in warnings)


def test_manifest_audit_warns_when_cronjob_allows_overlap(tmp_path):
    manifest = tmp_path / "qb.yaml"
    manifest.write_text(
        READY_MANIFEST.replace("  concurrencyPolicy: Forbid\n", ""),
        encoding="utf-8",
    )

    result = audit_kubernetes_database_manifests([manifest])

    assert result["ok"] is True
    assert any(
        issue["code"] == "cronjob_concurrency_not_forbid"
        and issue["resource"] == "CronJob/quizzicalbeats-backup"
        and issue["details"]["concurrency_policy"] == "Allow"
        for issue in result["warnings"]
    )
