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
| `import_catalog_item` | Import a Spotify or Deezer track, album, or playlist. |
| `compile_round` | Create a named round from explicit song IDs or selection criteria. |
| `rename_round` | Set or clear a round name. |
| `create_round_from_playlist` | Import a playlist and turn the imported songs into a round. |
| `generate_round_assets` | Generate the round PDF and/or MP3. |
| `inspect_round_mp3` | Check round MP3 duration, loudness, silence, and clipping indicators. |
| `inspect_round_pdf` | Check round PDF existence and basic structural validity. |
| `send_round_email` | Generate assets and email the finished round bundle. |
| `generate_tts_snippet` | Generate and assign custom intro, replay, or outro TTS MP3s. |

## Intended Workflow

1. Search with `find_songs` to avoid duplicates.
2. Add missing tracks with `add_song` or import platform content with
   `import_catalog_item`.
3. Create the round with `compile_round` or `create_round_from_playlist`.
4. Generate PDF and MP3 files with `generate_round_assets`.
5. Inspect the generated files with `inspect_round_pdf` and `inspect_round_mp3`.
6. Send the completed bundle with `send_round_email`.

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
