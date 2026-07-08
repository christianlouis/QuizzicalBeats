# MCP Interface

Quizzical Beats includes an MCP server for agentic round production workflows.
It exposes the same catalog, round, export, email, and custom-audio capabilities
used by the Flask application.

## Run Locally

Install dependencies and start the MCP server from the repository root:

```bash
pip install -r requirements.txt
python -m musicround.mcp_server
```

For a production streamable HTTP endpoint, run the authenticated ASGI entrypoint:

```bash
MCP_BEARER_TOKEN=... uvicorn musicround.mcp_http:app --host 0.0.0.0 --port 8000
```

If `MCP_BEARER_TOKEN` is not set, the HTTP entrypoint falls back to
`AUTOMATION_TOKEN`. Set `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS` when the
server is exposed behind a reverse proxy or ingress.

The server uses the normal Quizzical Beats Flask configuration. Set the same
environment variables you use for the web app, including `SECRET_KEY`,
`AUTOMATION_TOKEN`, database configuration, mail settings, and any Spotify,
Deezer, OpenAI, AWS Polly, or ElevenLabs credentials needed by the tools you
plan to call.

## Tools

The MCP server exposes these tools:

| Tool | Purpose |
| --- | --- |
| `find_songs` | Search the existing Quizzical Beats catalog before adding duplicates. |
| `add_song` | Add or update a catalog song, including platform IDs and tags. |
| `datastore_schema` | Describe all mapped datastore object types, columns, and primary keys. |
| `database_configuration_summary` | Report credential-safe database backend, managed-DB guard, and PG* readiness for cutover checks. |
| `database_cutover_plan` | Return credential-safe managed database cutover steps and the next blocked or ready action. |
| `list_datastore_objects` | List persisted objects with optional exact-match filters, ordering, limit, and offset. |
| `get_datastore_object` | Fetch one persisted object by primary key. |
| `create_datastore_object` | Create one persisted object from scalar column fields. |
| `update_datastore_object` | Update scalar column fields on one persisted object. |
| `delete_datastore_object` | Delete one persisted object by primary key. |
| `import_catalog_item` | Import a Spotify or Deezer track, album, or playlist. |
| `import_progress_events` | Return queue and job progress for polling clients. |
| `retry_import_job` | Requeue a failed or dead-letter import job for manual recovery. |
| `parse_text_playlist` | Parse pasted text or CSV-like playlists into reviewable song candidates. |
| `resolve_text_playlist` | Match parsed text rows against existing catalog songs. |
| `compile_round` | Create a named round from explicit song IDs or selection criteria. |
| `rename_round` | Set or clear a round name. |
| `set_round_owner` | Assign or clear the quizmaster owner for a round. |
| `share_round` | Share a round with another quizmaster as viewer, editor, or producer via system automation. |
| `list_round_shares` | List explicit share grants for a round. |
| `revoke_round_share` | Remove a user's share grant from a round via system automation. |
| `list_round_access_events` | List recent ownership and sharing audit events for a round; requires an owner/admin requester. |
| `enable_round_public_link` | Enable a token-based read-only public link for a round. |
| `disable_round_public_link` | Disable a token-based read-only public link for a round. |
| `get_public_round` | Fetch read-only round data for an active public round token. |
| `register_seed_source` | Create or update a chart, festival, editorial, curated, or playlist seed source. |
| `list_seed_sources` | List configured catalog seed sources for agent planning. |
| `seed_default_seed_sources` | Create or update the default mainstream chart and rock/metal festival source registry. |
| `record_seed_source_run` | Record seed-source read/import attempts and outcomes. |
| `fetch_seed_source_candidates` | Read a seed source URL or pasted text into reviewable candidates without importing songs. |
| `find_songs` | Search the catalog with relevance ranking, match explanations, filters for genre/year/preview/usage/tag/tempo, facets, suggestions, and short-lived cache metadata. |
| `suggest_replacement_songs` | Suggest catalog songs for a failed, unplayable, or overused song. |
| `replace_round_song` | Replace one song at a 1-based round position and invalidate generated assets. |
| `suggest_additional_songs` | Suggest catalog songs that can complete an incomplete round. |
| `add_round_song` | Add one song to a round and invalidate generated assets. |
| `recent_usage_summary` | Summarize recent rounds, frequently used songs, and selected-song warnings. |
| `quizmaster_context` | Return quizmaster preferences and recent usage for personalized planning. |
| `round_planning_brief` | Build an agent-readable structured brief for a robust themed round. |
| `create_planned_quiz_round` | Create a planned quiz date before a concrete round exists. |
| `list_planned_quiz_rounds` | List planned quiz dates for agents and production-board views. |
| `update_planned_quiz_round` | Update a planned quiz date and optional linked deliverables. |
| `link_planned_quiz_round` | Link a planned quiz date to a generated round or scheduled export. |
| `draft_round_audio_scripts` | Draft intro, replay, and outro text before TTS generation. |
| `save_round_audio_scripts` | Persist reviewable intro, replay, and outro script drafts. |
| `list_round_audio_scripts` | List stored script drafts by round, user, or review status. |
| `update_round_audio_script` | Edit, review, approve, reject, or select one stored script. |
| `generate_tts_from_script` | Generate and assign custom audio from an approved stored script. |
| `create_round_from_playlist` | Import a playlist and turn the imported songs into a round. |
| `create_round_from_text_playlist` | Create a complete round from text rows after every row resolves. |
| `round_analytics_summary` | Summarize catalog health, usage frequency, and unused candidates. |
| `generate_round_assets` | Generate the round PDF and/or MP3 and return the round review URL path. |
| `generate_round_assets_batch` | Generate PDF and/or MP3 files for several rounds without aborting the whole batch. |
| `round_review_payload` | Return songs, preview status, usage warnings, scripts, assets, quality, and repair hints for approval. |
| `update_round_review_status` | Mark a round draft, reviewed, approved, blocked, rejected, or sent. |
| `inspect_round_mp3` | Check round MP3 duration, loudness, silence, and clipping indicators. |
| `inspect_round_pdf` | Check round PDF existence and basic structural validity. |
| `inspect_round_package` | Check preview availability and length, expected generated MP3 length, MP3 quality, and PDF integrity. |
| `round_repair_report` | Return package quality plus a human-readable blocked/repair report. |
| `inspect_round_package_batch` | Audit several rounds at once and split sendable round IDs from repair-needed IDs. |
| `round_repair_plan` | Return a read-only repair plan with replacement and add-song candidates for a blocked round. |
| `round_repair_plan_batch` | Return read-only repair plans for several blocked rounds in one call. |
| `send_round_email` | Generate assets, block on failed package checks, and email only robust round bundles. |
| `schedule_round_email` | Generate and inspect a robust round bundle, then schedule later email delivery; use `replace_existing=true` when rescheduling the same quiz round. |
| `list_scheduled_round_emails` | List pending or historical scheduled email exports. |
| `cancel_scheduled_round_email` | Cancel a pending scheduled round email before the scheduler sends it. |
| `process_due_scheduled_round_emails` | Send scheduled round emails that are due. |
| `generate_tts_snippet` | Generate and assign custom intro, replay, or outro TTS MP3s. |

`find_songs` supports `query`, `title`, `artist`, `genre`, `year`,
`year_min`, `year_max`, `has_preview`, `unused_only`, platform IDs,
`limit`, `offset`, and `order_by`. It includes `used_count`,
`usage_frequency`, and `last_used` for each result so agents can see how often
songs have already appeared in rounds and avoid tracks without playable
previews.

The generic datastore CRUD tools operate on mapped SQLAlchemy models, including
`song`, `round`, `round_share`, `round_access_event`, `round_audio_script`,
`tag`, `song_tag`, `user`, `role`, `user_preferences`, `planned_quiz_round`, `round_export`,
`system_setting`, and `import_job_record`. Read results redact fields whose
names contain `password`, `token`, or `secret` unless `include_sensitive` is
explicitly set.

## Intended Workflow

1. Create or load upcoming quiz work with `create_planned_quiz_round` and
   `list_planned_quiz_rounds` when the date is known before the round exists.
2. Start with `quizmaster_context`, `recent_usage_summary`, or
   `round_planning_brief` so repeated songs and personalization constraints are
   visible before selecting tracks.
   `round_planning_brief` accepts `theme`, `quiz_date`, `language`,
   `audience`, `difficulty`, `mood`, `user_id`, `must_include`, `avoid`, and
   `notes`. It returns a stable `brief` object plus `round_planning_context`
   with constraints, review notes, recent usage, and selection/rejection
   guidance so an agent can explain why candidates were accepted or skipped.
3. Search with `find_songs` to avoid duplicates.
4. Add missing tracks with `add_song` or import platform content with
   `import_catalog_item`.
   For pasted lists, run `parse_text_playlist` first, then
   `resolve_text_playlist`; use `create_round_from_text_playlist` only after
   every row resolves.
5. Create the round with `compile_round` or `create_round_from_playlist`.
   Playlist imports return `needs_more_songs` instead of creating a partial
   round when fewer than the requested eight tracks resolve. Spotify playlist
   imports include `resolved_positions` with playlist position, Spotify track
   ID, artist, title, QB song ID, status, and failure reason so agents can
   repair specific positions.
6. Link the plan to the generated round with `link_planned_quiz_round`.
7. Generate PDF and MP3 files with `generate_round_assets` or
   `generate_round_assets_batch`; send the returned `review_url_path` to the
   quizmaster when a human should inspect the bundle preview page before
   scheduling or delivery.
8. Inspect the generated files and previews with `inspect_round_package`, then
   call `round_review_payload` to review songs, preview status, usage warnings,
   generated audio scripts, asset status, and repair hints.
9. Mark the round `approved` with `update_round_review_status` before delivery.
   `send_round_email` and `schedule_round_email` refuse draft, blocked,
   rejected, or merely reviewed rounds unless an admin-level workflow passes an
   explicit override.
10. Send the completed bundle with `send_round_email`; it reruns the package
   checks and refuses to send if previews or generated assets look wrong.
11. For several blocked rounds, call `round_repair_plan_batch`, apply only the
   explicit `replace_round_song` / `add_round_song` actions selected from each
   plan, regenerate assets with `generate_round_assets_batch`, then rerun
   `inspect_round_package_batch`.
   To defer delivery, call `schedule_round_email` with an ISO timestamp such as
   `2026-07-09T19:00:00+02:00`; it generates PDF/MP3 and must pass the package
   gate before it creates the scheduled send. The timestamp must be in the
   future. Set `replace_existing=true` for correction runs so only the latest
   pending email remains scheduled. Then run `process_due_scheduled_round_emails`
   from a scheduler.

When `inspect_round_package`, `round_repair_report`, or `send_round_email`
returns `needs_substitution`, read the failed `preview_checks` position or the
report's `failed_positions`, call `suggest_replacement_songs`, then call
`replace_round_song`. A position-based replacement search must include both
`round_id` and the 1-based `position`; otherwise use a standalone `song_id`,
`artist`/`title`, free-text `theme`, or preference hints such as
`preferred_genre`, `preferred_decade`, `preferred_mood`, `preferred_artist`,
`prefer_same_genre`, `prefer_same_decade`, and structured `constraints`.
Candidates include `platform_ids`, `preview`, `usage_history`,
`constraint_matches`, and human-readable `explanation` fields so an agent can
pick a playable, fresh replacement and explain the choice. Regenerate assets
after any replacement because the generated MP3/PDF flags are invalidated.

`inspect_round_package` distinguishes hard blockers from review warnings. The
`ok` field is false only when blocking issues exist, while `warnings` and
`report.warnings` should be surfaced to the user or agent as repair hints. Small
MP3 duration differences can be warnings; mismatches large enough to resemble a
missing preview slot remain blocking render failures.

When the status is `needs_more_songs`, call `suggest_additional_songs`, then
`add_round_song` until the round has exactly eight playable songs. Regenerate
assets and rerun `inspect_round_package` before sending.

For Spotify imports, pass a `user_id` for a user with connected Spotify tokens.
For email, either pass an explicit recipient or use a selected user that has an
email address.

## Custom Audio

Use `draft_round_audio_scripts` with `persist=true` or
`save_round_audio_scripts` to store reviewable text before audio generation.
After review, use `update_round_audio_script` to mark a script `approved`, then
`generate_tts_from_script` to update the reusable audio segment. Direct
generation with `generate_tts_snippet` remains available for trusted text.

- `intro`: lead-in before the first song.
- `replay`: announcement before the repeat section.
- `outro`: lead-out after the round.

Supported TTS services follow the existing application helper: `openai`, `polly`,
and `elevenlabs`.
