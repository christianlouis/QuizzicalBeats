# Agentic Backlog Status

Last updated: July 9, 2026

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
- **Milestone**: roadmap-scale issue; pick or create a smaller task only when
  the current milestone cannot be closed in one local work block.

## Current Issue Crosswalk

| Issue | Status | Evidence in repo | Remaining work |
| --- | --- | --- | --- |
| #12 Remove SQLite/RWO singleton | Operational / partial | Production no longer uses SQLite as the application database, CNPG PostgreSQL is live, SQLite rows were migrated, Web/MCP/scheduled email use PostgreSQL, rollout strategy avoids RWO replacement deadlocks, backup readiness fails closed for managed SQL, artifact storage capabilities flag filesystem storage as HA-blocking, and storage inventory is visible in service health/admin health | Generated MP3/PDF artifacts still depend on `/data` RWO storage, web is still one replica, and database-native backup/snapshot handling still needs validation before the host-loss HA acceptance criteria can close. |
| #32 External Music Data and chart ingestion | Milestone / open | Seed-source registry, candidate previewing, idempotent default seed sources, and MCP helpers exist | Scheduled ingestion, normalization into planning metadata, review UI, and source-rate-limit governance remain. |
| #33 Alert Amplifier notifications | Milestone / mostly complete | Import-job status emails, per-user notification preferences, OAuth token warning email CLI, quality-gate repair emails, SMTP verification CLI, and admin digest with service-health and backup-readiness findings exist | Optional push channels and any future in-product digest UI remain. |
| #34 Storage Sanctuary multi-provider storage | Milestone / open | Storage health checks gate MP3/PDF generation and delivery; filesystem paths are configurable through `ROUND_MP3_DIR`, `ROUND_PDF_DIR`, and `DATA_DIR`; service health and admin health expose backend capabilities, HA-blocking warnings, and generated artifact inventory totals | Add object/cloud backend support, backup export storage, admin sync controls, and stable MCP asset responses independent of the backend. |
| #35 Collaboration Core shared rounds | Milestone / partial | Round ownership, viewer/editor/producer grants, public read-only links, route-level edit checks, and sharing audit events exist | Comment/admin roles, invitations, presence, revision history, and comment threads remain. |

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
- #126 Move production database configuration off SQLite `/data`
- #17 Repair and resend broken July-October 2026 music rounds
- #26 Roadmap tracker
- #37 Deployment Dynamo CI/CD and maintenance
- #48 Remove or archive already-sent broken Gmail messages
- #49 Repair July-October 2026 QB rounds and resend only passing bundles
- #212 Prevent RWO multi-attach deadlocks during web rollouts
- #213 Silence SQLite-only migration errors on PostgreSQL startup
- #217 Expose artifact storage HA capabilities in health payload
- #218 Expose generated artifact inventory in service health
- #219 Surface artifact storage readiness on admin system health

## Next Local Work Blocks

1. For #34/#12, add the next shared/object-storage backend implementation
   behind the existing artifact storage abstraction and capability payload.
2. For #12, replace the managed-SQL backup readiness blocker with a validated
   database-native backup or snapshot path.
3. For #33, either implement optional push channels or split them into a future
   explicitly optional issue so the notification milestone can close cleanly.
4. For #35, add invitation UX or revision/audit history as the next
   browser-verifiable collaboration slice.
