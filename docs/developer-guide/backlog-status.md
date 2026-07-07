# Agentic Backlog Status

Last updated: July 7, 2026

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
| #69 Add review workflow for low-confidence text imports | Ready to close after deploy smoke | Browser review UI, exact eight-song create gate, MCP/parser review payloads | Smoke paste one unresolved and one complete eight-song text list. |
| #75 Add chart and festival seed source registry | Ready to close | `SeedSource`, `SeedSourceRun`, admin views, MCP registry/run tools, read-only source candidate fetcher, default chart/festival source seeding | Close after the seed-source MCP tools are visible in the deployed app. |
| #126 Move production database configuration off SQLite `/data` | Operational / partial | Managed DB config, migration CLI, MCP config diagnostics, runbook, Compose managed-db profile | Live Kubernetes secret/config cutover and scheduled-email smoke remain. |
| #12 Remove SQLite/RWO singleton | Operational / partial | Same as #126, plus app config hardening | Requires managed DB cutover, stateless replicas, and backup replacement. |
| #17/#48/#49 Repair and clean broken round emails | Operational | Quality gate and repair tooling exist; MP3 duration drift below the default 30s tolerance is non-blocking | Needs live QB/Gmail inspection and cleanup, not repo-only code. |

## Recently Closed From This Crosswalk

- #25 Asset preview and approval page before email delivery
- #56 Readiness and schedule status columns on the rounds list
- #57 Normalized, curated round-builder tags
- #58 Lazy-loaded song previews and paginated song library browsing
- #65 ROADMAP.md / TODO.md status drift
- #66 Import retry and dead-letter handling
- #67 Import progress events
- #68 Text and CSV playlist parser service
- #70 Quizmaster preferences and MCP summary
- #71 Planned quiz date model and MCP planning tools
- #72 Recent usage and fatigue summary for agents
- #73 MCP drafting for intro, replay, and outro scripts
- #74 Reviewable TTS script records and generation handoff
- #79 Round ownership and sharing roles

## Next Local Work Blocks

1. Smoke #69 in the browser with one unresolved and one complete eight-song
   text list, then close it if the review loop behaves correctly.
2. Close #75 after deploy smoke confirms the seed-source MCP tools are visible.
3. For #126/#12, continue with live deployment configuration only through the
   existing 1Password-backed secret flow and credential-safe Kubernetes checks.
