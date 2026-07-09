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
| #126 Move production database configuration off SQLite `/data` | Operational / partial | Managed DB config, migration CLI, credential-safe cutover plan CLI, Kubernetes manifest audit, direct scheduled-email CLI, MCP config diagnostics, runbook, Compose managed-db profile, warnings when `SQLALCHEMY_DATABASE_URI` masks complete split PG* secrets, ExternalSecret DB-key/store-name/store-kind/owner checks, split-PG completeness checks, direct DB-env override blockers, scheduled-email web-pod exec blockers, and manifest blockers for ConfigMap/literal/raw-Secret `PGPASSWORD` or database URI values | Live Kubernetes secret/config cutover and scheduled-email smoke remain. |
| #12 Remove SQLite/RWO singleton | Operational / partial | Same as #126, plus app config hardening, manifest audit warnings for single replicas, Recreate strategy, RWO PVCs, `/data` mounts, RWO multi-workload mount blockers, same-node backup affinity, app-backup CronJobs under managed SQL, overlapping CronJobs, missing topology spread/PDB coverage, missing readiness/liveness probes, missing CPU/memory requests/limits, ConfigMap/literal/raw-Secret DB secret blockers, ExternalSecret DB-key/store-name/store-kind/owner checks, split-PG completeness checks, direct DB-env override blockers, and backup readiness CLI that fails closed on managed SQL | Requires managed DB cutover, stateless replicas, and backup replacement. |
| #17/#48/#49 Repair and clean broken round emails | Operational / partial | Quality gate, batch package audit, and repair tooling exist; MP3 duration drift below the default 30s tolerance is non-blocking | Needs live QB/Gmail inspection and cleanup, not repo-only code. |
| #33 Alert Amplifier notifications | Partial | Global import-job email toggle, completed/dead-letter status emails, per-user profile opt-outs, dry-run/send CLI for Spotify/Dropbox token warnings, quality-gate repair emails for blocked rounds, SMTP verification CLI, and admin notification digest | Optional push channels and any future in-product digest UI remain. |

## Recently Closed From This Crosswalk

- #31 Server Stability production hardening
- #36 Performance Pulse
- #29 Search Supercharge
- #25 Asset preview and approval page before email delivery
- #21 Draft review and approval state for generated rounds
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
