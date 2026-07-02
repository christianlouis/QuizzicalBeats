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
| `compile_round` | Create a named round from explicit song IDs or selection criteria. |
| `rename_round` | Set or clear a round name. |
| `suggest_replacement_songs` | Suggest catalog songs for one failed round position. |
| `replace_round_song` | Replace one song at a 1-based round position and invalidate generated assets. |
| `create_round_from_playlist` | Import a playlist and turn the imported songs into a round. |
| `generate_round_assets` | Generate the round PDF and/or MP3. |
| `inspect_round_mp3` | Check round MP3 duration, loudness, silence, and clipping indicators. |
| `inspect_round_pdf` | Check round PDF existence and basic structural validity. |
| `inspect_round_package` | Check preview availability and length, expected generated MP3 length, MP3 quality, and PDF integrity. |
| `send_round_email` | Generate assets, block on failed package checks, and email only robust round bundles. |
| `generate_tts_snippet` | Generate and assign custom intro, replay, or outro TTS MP3s. |

`find_songs` includes `used_count`, `usage_frequency`, and `last_used` for each
result so agents can see how often songs have already appeared in rounds.

The generic datastore CRUD tools operate on mapped SQLAlchemy models, including
`song`, `round`, `tag`, `song_tag`, `user`, `role`, `user_preferences`,
`round_export`, `system_setting`, and `import_job_record`. Read results redact
fields whose names contain `password`, `token`, or `secret` unless
`include_sensitive` is explicitly set.

## Intended Workflow

1. Search with `find_songs` to avoid duplicates.
2. Add missing tracks with `add_song` or import platform content with
   `import_catalog_item`.
3. Create the round with `compile_round` or `create_round_from_playlist`.
   Playlist imports return `needs_more_songs` instead of creating a partial
   round when fewer than the requested eight tracks resolve.
4. Generate PDF and MP3 files with `generate_round_assets`.
5. Inspect the generated files and previews with `inspect_round_package`.
6. Send the completed bundle with `send_round_email`; it reruns the package
   checks and refuses to send if previews or generated assets look wrong.

When `inspect_round_package` or `send_round_email` returns
`needs_substitution`, read the failed `preview_checks` position, call
`suggest_replacement_songs`, then call `replace_round_song`. Regenerate assets
after any replacement because the generated MP3/PDF flags are invalidated.

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
