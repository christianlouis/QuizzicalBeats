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

   Before the managed database cutover, run the stricter preflight. It fails
   with exit code `78` while legacy SQLite is still active or the PG*
   configuration is incomplete:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight
   ```

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
   `secretKeyRef` entries so no full URI secret needs to be stored. Remove or
   blank `SQLALCHEMY_DATABASE_URI` before using the component variables; a set
   URI wins over PG* values by design. A complete `SQLALCHEMY_DATABASE_URI` in
   the 1Password item `quizzicalbeats/quizzicalbeats-secrets` is still
   supported.

## Dry Run

1. Restore the SQLite backup into a disposable workspace.
2. Import into a disposable managed database using a tested migration tool such
   as `pgloader` or an equivalent schema-aware export/import process.
3. Start the app against the disposable managed URI and run:

   ```bash
   python /app/run.py database preflight
   python -m pytest tests/test_app_factory.py tests/test_automation_service.py
   ```

4. Verify the core counts match the SQLite source: songs, rounds, users, tags,
   and scheduled exports.

## Production Cutover

1. Ensure External Secrets has synced the updated 1Password item:

   ```bash
   kubectl -n quizzicalbeats get externalsecret quizzicalbeats-secrets
   kubectl -n quizzicalbeats get secret quizzicalbeats-secrets \
     -o jsonpath='{.data.SQLALCHEMY_DATABASE_URI}' >/dev/null
   ```

   If using CNPG component variables instead, verify the app deployment has
   `PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` configured without
   printing their values, then confirm the referenced Secret exposes those keys
   without printing the secret data:

   ```bash
   kubectl -n quizzicalbeats get deploy quizzicalbeats \
     -o jsonpath='{range .spec.template.spec.containers[?(@.name=="web")].env[*]}{.name}{"\n"}{end}' \
     | grep -E '^(PGHOST|PGDATABASE|PGUSER|PGPASSWORD)$'

   kubectl -n quizzicalbeats get secret quizzicalbeats-secrets -o json \
     | jq -r '.data | keys[]' \
     | grep -E '^(PGHOST|PGDATABASE|PGUSER|PGPASSWORD)$'
   ```

2. Deploy the app with `DATABASE_REQUIRE_MANAGED=true` and without a ConfigMap
   `SQLALCHEMY_DATABASE_URI` SQLite fallback.
3. Restart the web deployment after the secret has synced:

   ```bash
   kubectl -n quizzicalbeats rollout restart deploy/quizzicalbeats
   kubectl -n quizzicalbeats rollout status deploy/quizzicalbeats
   ```

4. Verify without printing credentials:

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

5. Verify web, MCP, and scheduled-email execution share the same config:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database preflight
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats-mcp -c mcp -- python /app/run.py database preflight
   kubectl -n quizzicalbeats create job --from=cronjob/quizzicalbeats-scheduled-email qb-db-cutover-smoke
   ```

## Rollback

1. Disable `DATABASE_REQUIRE_MANAGED` in the ConfigMap only if emergency
   rollback to SQLite is required.
2. Restore the last known-good `/data/song_data.db` backup or PVC snapshot.
3. Reintroduce the SQLite URI only as an emergency rollback, then restart the
   web deployment.
4. Record the reason for rollback and keep the managed URI secret in
   1Password for investigation; do not paste it into the issue or logs.
