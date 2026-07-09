# Managed Database Migration Runbook

This runbook moves Quizzical Beats from the legacy `/data/song_data.db` SQLite
database to a managed SQL database without exposing credentials in logs or Git.

## Ownership

- Secret owner: `quizzicalbeats/quizzicalbeats-secrets` in the existing
  1Password-backed ExternalSecret flow.
- Required database config: either `SQLALCHEMY_DATABASE_URI` or the standard
  PostgreSQL component variables `PGHOST`, `PGDATABASE`, `PGUSER`, and
  `PGPASSWORD`. `PGPORT` defaults to `5432`.
- Precedence rule: the database resolver uses `SQLALCHEMY_DATABASE_URI` first
  whenever it is set. Remove or blank the URI before relying on the PG*
  component variables.
- Production guard: set `DATABASE_REQUIRE_MANAGED=true` in Kubernetes config.
  The app accepts common truthy values such as `true`, `1`, `yes`, and `on`.
- Database credentials must stay in 1Password, CNPG-generated Kubernetes
  Secrets, or equivalent secretKeyRef entries. Do not commit them to Git and
  do not print them in logs.

## Preflight

1. Confirm the current pod still uses SQLite without printing credentials:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database status
   ```

   For MCP agents, smoke scripts, or automation, use the equivalent JSON form.
   It reports only redacted targets and PG* key names, never database passwords
   or SQLite file paths:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database status --json
   ```

   To let an agent or operator decide the next cutover action, print the
   credential-safe checklist. It never prints database passwords or raw SQLite
   file paths, and in `--json` mode it is intended for MCP/automation
   hand-offs:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database cutover-plan --json
   ```

   Before changing GitOps manifests, run the credential-safe manifest audit
   against the QuizzicalBeats manifest directory. It reports key names,
   workload wiring, SQLite fallbacks, and `/data` coupling without reading or
   printing secret values:

   ```bash
   python run.py database manifest-audit --path apps/quizzicalbeats --json
   ```

   The audit must not report `legacy_sqlite_configmap`,
   `managed_guard_not_enabled`, `database_secret_configmap_value`, or
   `database_secret_literal_env`, `database_secret_raw_manifest`, or
   `external_secret_database_keys_missing`, or
   `external_secret_store_ref_missing`, `external_secret_store_ref_kind_invalid`,
   `external_secret_target_duplicate`, or
   `managed_database_config_keys_missing`, or
   `database_direct_env_override`, or
   `rwo_persistent_volume_claim_multi_consumer`, or
   `scheduled_job_execs_web_pod` before live
   cutover. Warnings about `/data` mounts, `application_backup_scheduler_for_managed_db`,
   `topology_spread_missing`, `pod_disruption_budget_missing`,
   `readiness_probe_missing`, `liveness_probe_missing`, or
   `resource_requirements_missing` can remain during the database cutover if
   artifacts still use the existing volume, but they must be addressed before
   multi-replica HA. `external_secret_database_keys_unverifiable` means the
   ExternalSecret uses `dataFrom`; manually confirm the external item exposes
   `PGPASSWORD` or `SQLALCHEMY_DATABASE_URI` before cutover.
   `managed_database_config_keys_unverifiable` means `dataFrom` may provide
   missing PG* keys that are not visible in Git; verify the external item or
   switch to explicit key mappings before the maintenance window.
   `cronjob_concurrency_not_forbid` should also be cleared for scheduled email,
   backup, and repair jobs before they are trusted in production automation.
   `rwo_persistent_volume_claim_multi_consumer` means more than one workload
   mounts the same `ReadWriteOnce` claim; move shared artifacts to object/shared
   storage or keep the claim attached to one workload before the HA cutover.
   `scheduled_job_execs_web_pod` means a scheduled automation still shells into
   the first web pod it finds; replace it with the application image running
   `python /app/run.py scheduled-emails process-due --json`.

   Before the managed database cutover, run the stricter preflight. It fails
   with exit code `78` while legacy SQLite is still active or the PG*
   configuration is incomplete:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight
   ```

   The preflight command also supports `--json` for automation while preserving
   the same exit-code semantics.

   During early migration work, use `--allow-sqlite` only to collect the same
   diagnostics without blocking on the current SQLite state:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight --allow-sqlite
   ```

2. Create a final SQLite backup before migration:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py backup create --auto
   ```

3. Copy `/data/song_data.db` out of the pod or snapshot the PVC before any
   import into the managed database.

4. Add the managed database configuration. For PostgreSQL/CNPG, prefer
   `PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` from Kubernetes
   `secretKeyRef` entries so no full URI secret needs to be stored.
   `PGPASSWORD` and `SQLALCHEMY_DATABASE_URI` must not be ConfigMap values or
   literal `env.value` entries in GitOps manifests. Do not commit raw
   Kubernetes `Secret` documents that contain these keys; use the
   1Password-backed `ExternalSecret` target or reference CNPG-generated
   Secrets. The `ExternalSecret` must reference the approved `SecretStore` or
   `ClusterSecretStore`; a target Secret name alone does not prove the
   controller can sync it. Exactly one ExternalSecret should own the
   `quizzicalbeats-secrets` target. If `secretStoreRef.kind` is set, it must be
   either `SecretStore` or `ClusterSecretStore`. Prefer explicit ExternalSecret
   `data.secretKey` mappings for `PGPASSWORD` or `SQLALCHEMY_DATABASE_URI`; if
   `dataFrom` is used, verify the external item contents through 1Password or
   the external secret owner before the cutover. Remove or blank
   `SQLALCHEMY_DATABASE_URI` before using the
   component variables; a set URI wins over PG* values by design. A complete
   `SQLALCHEMY_DATABASE_URI` in the 1Password item
   `quizzicalbeats/quizzicalbeats-secrets` is still supported.
   Web, MCP, and scheduled jobs should import database settings through the
   shared `quizzicalbeats-config` and `quizzicalbeats-secrets` `envFrom`
   entries only; direct DB-specific `env` entries can override those shared
   values and split workloads during cutover.

## Dry Run

1. Restore the SQLite backup into a disposable workspace.
2. Point the app environment at the disposable managed database. Prefer the
   component variables so the password can come from a Secret key:

   ```bash
   export PGHOST=quizzicalbeats-db-rw.quizzicalbeats.svc
   export PGDATABASE=quizzicalbeats
   export PGUSER=quizzicalbeats
   export PGPASSWORD='from-secret-manager'
   unset SQLALCHEMY_DATABASE_URI
   ```

3. Run the built-in dry run first. It prints only row counts and redacted
   targets, never the source path or database password:

   ```bash
   python /app/run.py database migrate-sqlite --source /restore/song_data.db
   ```

4. Execute only after the dry run looks right. The target database must be
   empty unless `--replace-target` is explicitly passed after taking a backup:

   ```bash
   python /app/run.py database migrate-sqlite \
     --source /restore/song_data.db \
     --execute
   ```

5. Start the app against the disposable managed URI and run:

   ```bash
   python /app/run.py database preflight
   python -m pytest tests/test_app_factory.py tests/test_automation_service.py
   ```

6. Verify the core counts match the SQLite source: songs, rounds, users, tags,
   and scheduled exports.

## Production Cutover

The current GitOps target for Quizzical Beats should use a dedicated
CloudNativePG cluster named `quizzicalbeats-postgresql-ha`. Keep the application
database name and owner as `quizzicalbeats`, set `PGHOST` to
`quizzicalbeats-postgresql-ha-rw.quizzicalbeats.svc.cluster.local`, and map the
existing 1Password field `DB_PASSWORD` to both:

- `PGPASSWORD` in the shared `quizzicalbeats-secrets` Secret for the app.
- `password` in the CNPG bootstrap Secret, with `username: quizzicalbeats`.

Do not require a new raw password in Git or logs. The 1Password item currently
uses `DB_PASSWORD`, so an ExternalSecret must publish the app-facing
`PGPASSWORD` key explicitly. After moving scheduled email into the app image,
remove the pod-exec ServiceAccount, Role, and RoleBinding. The MCP deployment
does not need `/data`; run it without the PVC mount and use two replicas with a
PodDisruptionBudget and hostname topology spread. Keep the web deployment on
one replica until `/data` artifact storage is externalized.

1. Ensure External Secrets has synced the updated 1Password item:

   ```bash
   kubectl -n quizzicalbeats get externalsecret quizzicalbeats-secrets
   kubectl -n quizzicalbeats get externalsecret quizzicalbeats-cnpg-app
   ```

   Verify the ConfigMap and Secret expose the component variable key names
   without printing values:

   ```bash
   kubectl -n quizzicalbeats get configmap quizzicalbeats-config -o json \
     | jq -r '.data | keys[]' \
     | grep -E '^(PGHOST|PGDATABASE|PGUSER|DATABASE_REQUIRE_MANAGED)$'

   kubectl -n quizzicalbeats get secret quizzicalbeats-secrets -o json \
     | jq -r '.data | keys[]' \
     | grep '^PGPASSWORD$'
   ```

2. Deploy the app with `DATABASE_REQUIRE_MANAGED=true` and without a ConfigMap
   `SQLALCHEMY_DATABASE_URI` SQLite fallback.
3. Run the production dry run from a one-off pod or the web pod with the new
   target database environment. Do not pass `--execute` until backup and
   rollback are confirmed:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- \
     python /app/run.py database migrate-sqlite --source /data/song_data.db
   ```

4. Execute the copy during the maintenance window:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- \
     python /app/run.py database migrate-sqlite \
       --source /data/song_data.db \
       --execute
   ```

5. Restart the web deployment after the secret has synced:

   ```bash
   kubectl -n quizzicalbeats rollout restart deploy/quizzicalbeats
   kubectl -n quizzicalbeats rollout status deploy/quizzicalbeats
   ```

6. Verify without printing credentials:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python - <<'PY'
   from musicround import create_app, db
   from musicround.models import Song, Round, User
   app = create_app()
   with app.app_context():
       print({"songs": Song.query.count(), "rounds": Round.query.count(), "users": User.query.count()})
   PY
   ```

7. Verify web, MCP, and scheduled-email execution share the same config:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats-mcp -c mcp -- python /app/run.py database preflight
   kubectl -n quizzicalbeats create job --from=cronjob/quizzicalbeats-scheduled-email qb-db-cutover-smoke
   kubectl -n quizzicalbeats logs job/qb-db-cutover-smoke
   ```

   The scheduled-email CronJob should run the application image directly with:

   ```bash
   python /app/run.py scheduled-emails process-due --json
   ```

   Avoid scheduler definitions that shell out to `kubectl exec` into a web pod;
   they work only while there is a single web pod and undermine the HA target.

8. Verify the backup path after the managed database is active:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py backup readiness --json
   ```

   For PostgreSQL or another managed SQL backend this command must fail closed
   until a native database backup or snapshot path is documented and scheduled.
   The app-level ZIP backup is only valid for SQLite database files; it can
   still cover local media/config artifacts, but it is not the managed database
   backup.

   Inspect the `database_backup` section in the JSON output for the
   credential-safe PostgreSQL backup strategy, expected `PG*` environment key
   names, and command templates for native dumps or CloudNativePG snapshots.

## Rollback

1. Disable `DATABASE_REQUIRE_MANAGED` in the ConfigMap only if emergency
   rollback to SQLite is required.
2. Restore the last known-good `/data/song_data.db` backup or PVC snapshot.
3. Reintroduce the SQLite URI only as an emergency rollback, then restart the
   web deployment.
4. Record the reason for rollback and keep the managed URI secret in
   1Password for investigation; do not paste it into the issue or logs.
