# Managed Database Migration Runbook

This runbook moves Quizzical Beats from the legacy `/data/song_data.db` SQLite
database to a managed SQL database without exposing credentials in logs or Git.

## Ownership

- Secret owner: `quizzicalbeats/quizzicalbeats-secrets` in the existing
  1Password-backed ExternalSecret flow.
- Required secret key: `SQLALCHEMY_DATABASE_URI`.
- Production guard: set `DATABASE_REQUIRE_MANAGED=true` in Kubernetes config.
  The app accepts common truthy values such as `true`, `1`, `yes`, and `on`.
- The URI value must stay in 1Password or the generated Kubernetes Secret. Do
  not commit it to Git and do not print it in logs.

## Preflight

1. Confirm the current pod still uses SQLite without printing credentials:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database status
   ```

2. Create a final SQLite backup before migration:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py backup create --auto
   ```

3. Copy `/data/song_data.db` out of the pod or snapshot the PVC before any
   import into the managed database.

4. Add or update `SQLALCHEMY_DATABASE_URI` in the 1Password item
   `quizzicalbeats/quizzicalbeats-secrets`. The target should be a managed SQL
   database. PostgreSQL is preferred for production.

## Dry Run

1. Restore the SQLite backup into a disposable workspace.
2. Import into a disposable managed database using a tested migration tool such
   as `pgloader` or an equivalent schema-aware export/import process.
3. Start the app against the disposable managed URI and run:

   ```bash
   python /app/run.py database status
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

2. Deploy the app with `DATABASE_REQUIRE_MANAGED=true` and without a ConfigMap
   `SQLALCHEMY_DATABASE_URI` fallback.
3. Restart the web deployment after the secret has synced:

   ```bash
   kubectl -n quizzicalbeats rollout restart deploy/quizzicalbeats
   kubectl -n quizzicalbeats rollout status deploy/quizzicalbeats
   ```

4. Verify without printing credentials:

   ```bash
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database status
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
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats -c web -- python /app/run.py database status
   kubectl -n quizzicalbeats exec deploy/quizzicalbeats-mcp -c mcp -- python /app/run.py database status
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
