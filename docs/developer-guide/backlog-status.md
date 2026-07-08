# Agentic Backlog Status

Last updated: July 8, 2026

This page keeps the GitHub issue backlog aligned with what is actually present
in the codebase. It is meant for coding agents before they pick the next local
work block: do not rebuild a slice listed as "ready to close"; either close the
issue after verification or continue with the remaining follow-up.

## Status Key

- **Ready to close**: implemented in code and covered by focused tests or
  documentation.
- **Partial**: a meaningful core slice exists, but the GitHub issue still has
  remaining acceptance criteria.
- **Open**: not yet implemented beyond planning or documentation.
- **Operational**: requires live QB, Gmail, Kubernetes, or secret-backed
  verification rather than only repository changes.

## Current Issue Crosswalk

| Issue | Status | Evidence in repo | Remaining work |
| --- | --- | --- | --- |
| #126 Move production database configuration off SQLite `/data` | Operational / partial | Managed DB config, migration CLI, MCP config diagnostics, runbook, Compose managed-db profile, and warnings when `SQLALCHEMY_DATABASE_URI` masks complete split PG* secrets | Live Kubernetes secret/config cutover and scheduled-email smoke remain. |
| #12 Remove SQLite/RWO singleton | Operational / partial | Same as #126, plus app config hardening | Requires managed DB cutover, stateless replicas, and backup replacement. |
| #31 Server Stability production hardening | Partial | Gunicorn entrypoint, ProxyFix/HTTPS handling, secure cookie defaults, and configurable app-level security headers with HSTS on HTTPS | Reverse proxy/SSL termination validation, static asset optimization, compression, and live production smoke remain. |
| #17/#48/#49 Repair and clean broken round emails | Operational | Quality gate and repair tooling exist; MP3 duration drift below the default 30s tolerance is non-blocking | Needs live QB/Gmail inspection and cleanup, not repo-only code. |
| #33 Alert Amplifier notifications | Partial | Global import-job email toggle, completed/dead-letter status emails, per-user profile opt-outs, dry-run/send CLI for Spotify/Dropbox token warnings, quality-gate repair emails for blocked rounds, SMTP verification CLI, and admin notification digest | Optional push channels and any future in-product digest UI remain. |

## Recently Closed From This Crosswalk

- #25 Asset preview and approval page before email delivery
- #56 Readiness and schedule status columns on the rounds list
- #57 Normalized, curated round-builder tags
- #58 Lazy-loaded song previews and paginated song library browsing
- #65 ROADMAP.md / TODO.md status drift
- #66 Import retry and dead-letter handling
- #67 Import progress events
- #68 Text and CSV playlist parser service
- #69 Low-confidence text-import review workflow
- #30 Textual Transport text/CSV paste, upload, review, and MCP path
- #28 Progress Pulse import status tracking
- #70 Quizmaster preferences and MCP summary
- #71 Planned quiz date model and MCP planning tools
- #72 Recent usage and fatigue summary for agents
- #73 MCP drafting for intro, replay, and outro scripts
- #74 Reviewable TTS script records and generation handoff
- #75 Chart and festival seed source registry
- #79 Round ownership and sharing roles

## Next Local Work Blocks

1. For #126/#12, continue with live deployment configuration only through the
   existing 1Password-backed secret flow and credential-safe Kubernetes checks.
