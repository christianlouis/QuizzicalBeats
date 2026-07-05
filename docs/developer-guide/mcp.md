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
| `suggest_replacement_songs` | Suggest catalog songs for one failed round position. |
| `replace_round_song` | Replace one song at a 1-based round position and invalidate generated assets. |
| `suggest_additional_songs` | Suggest catalog songs that can complete an incomplete round. |
| `add_round_song` | Add one song to a round and invalidate generated assets. |
| `recent_usage_summary` | Summarize recent rounds, frequently used songs, and selected-song warnings. |
| `quizmaster_context` | Return quizmaster preferences and recent usage for personalized planning. |
| `round_planning_brief` | Build an agent-readable brief for a robust themed round. |
| `draft_round_audio_scripts` | Draft intro, replay, and outro text before TTS generation. |
| `create_round_from_playlist` | Import a playlist and turn the imported songs into a round. |
| `create_round_from_text_playlist` | Create a complete round from text rows after every row resolves. |
| `round_analytics_summary` | Summarize catalog health, usage frequency, and unused candidates. |
| `generate_round_assets` | Generate the round PDF and/or MP3. |
| `inspect_round_mp3` | Check round MP3 duration, loudness, silence, and clipping indicators. |
| `inspect_round_pdf` | Check round PDF existence and basic structural validity. |
| `inspect_round_package` | Check preview availability and length, expected generated MP3 length, MP3 quality, and PDF integrity. |
| `round_repair_report` | Return package quality plus a human-readable blocked/repair report. |
| `send_round_email` | Generate assets, block on failed package checks, and email only robust round bundles. |
| `schedule_round_email` | Generate and inspect a robust round bundle, then schedule later email delivery. |
| `list_scheduled_round_emails` | List pending or historical scheduled email exports. |
| `process_due_scheduled_round_emails` | Send scheduled round emails that are due. |
| `generate_tts_snippet` | Generate and assign custom intro, replay, or outro TTS MP3s. |

`find_songs` includes `used_count`, `usage_frequency`, and `last_used` for each
result so agents can see how often songs have already appeared in rounds.

The generic datastore CRUD tools operate on mapped SQLAlchemy models, including
`song`, `round`, `tag`, `song_tag`, `user`, `role`, `user_preferences`,
`round_export`, `system_setting`, and `import_job_record`. Read results redact
fields whose names contain `password`, `token`, or `secret` unless
`include_sensitive` is explicitly set.

## Intended Workflow

1. Start with `quizmaster_context`, `recent_usage_summary`, or
   `round_planning_brief` so repeated songs and personalization constraints are
   visible before selecting tracks.
2. Search with `find_songs` to avoid duplicates.
3. Add missing tracks with `add_song` or import platform content with
   `import_catalog_item`.
   For pasted lists, run `parse_text_playlist` first, then
   `resolve_text_playlist`; use `create_round_from_text_playlist` only after
   every row resolves.
4. Create the round with `compile_round` or `create_round_from_playlist`.
   Playlist imports return `needs_more_songs` instead of creating a partial
   round when fewer than the requested eight tracks resolve.
5. Generate PDF and MP3 files with `generate_round_assets`.
6. Inspect the generated files and previews with `inspect_round_package`.
7. Send the completed bundle with `send_round_email`; it reruns the package
   checks and refuses to send if previews or generated assets look wrong.
   To defer delivery, call `schedule_round_email` with an ISO timestamp such as
   `2026-07-09T19:00:00+02:00`; it generates PDF/MP3 and must pass the package
   gate before it creates the scheduled send. Then run
   `process_due_scheduled_round_emails` from a scheduler.

When `inspect_round_package`, `round_repair_report`, or `send_round_email`
returns `needs_substitution`, read the failed `preview_checks` position or the
report's `failed_positions`, call `suggest_replacement_songs`, then call
`replace_round_song`. Regenerate assets after any replacement because the
generated MP3/PDF flags are invalidated.

When the status is `needs_more_songs`, call `suggest_additional_songs`, then
`add_round_song` until the round has exactly eight playable songs. Regenerate
assets and rerun `inspect_round_package` before sending.

For Spotify imports, pass a `user_id` for a user with connected Spotify tokens.
For email, either pass an explicit recipient or use a selected user that has an
email address.

## Custom Audio

Use `generate_tts_snippet` to update the reusable audio segments:

- `intro`: lead-in before the first song.
- `replay`: announcement before the repeat section.
- `outro`: lead-out after the round.

Supported TTS services follow the existing application helper: `openai`, `polly`,
and `elevenlabs`.
