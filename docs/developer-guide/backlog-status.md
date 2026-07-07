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
| #56 Add readiness and schedule status columns to rounds list | Ready to close | `musicround/routes/rounds.py`, `musicround/templates/rounds.html`, `tests/test_rounds_routes.py` | Verify deployed rounds list after release. |
| #57 Normalize and curate tags shown in the round builder | Ready to close | `musicround/routes/generate.py`, `tests/test_generate.py` | Verify production tag dropdown contains no internal import tags. |
| #58 Reduce song library memory usage and lazy-load previews | Ready to close | `musicround/routes/core.py`, `musicround/templates/view_songs.html`, `tests/test_final_coverage.py` | Browser-smoke large catalog after deploy. |
| #65 ROADMAP.md / TODO.md status drift | Ready to close after this doc lands | `ROADMAP.md`, `TODO.md`, this status page | Close once this crosswalk is merged. |
| #66 Add retry and dead-letter handling for import jobs | Ready to close | `musicround/helpers/import_queue.py`, `musicround/services/automation.py`, `tests/test_import_queue.py` | Verify one failed import can be retried in production. |
| #67 Expose import progress events for active jobs | Ready to close | `musicround/mcp_server.py`, `musicround/services/automation.py`, `musicround/templates/import_queue_status.html` | Optional browser auto-refresh polish can be a separate issue. |
| #68 Add text and CSV playlist parser service | Ready to close | `musicround/services/automation.py`, `musicround/mcp_server.py`, `tests/test_automation_service.py` | None for parser/MCP scope. |
| #69 Add review workflow for low-confidence text imports | Ready to close after deploy smoke | Browser review UI, exact eight-song create gate, MCP/parser review payloads | Smoke paste one unresolved and one complete eight-song text list. |
| #70 Add quizmaster preference model and MCP summary | Ready to close | `UserPreferences`, `quizmaster_context`, MCP docs | Verify one real quizmaster context call in MCP after deploy. |
| #71 Add planned quiz date model for scheduled round generation | Ready to close | `PlannedQuizRound`, browser calendar, MCP planning tools | Verify upcoming production quiz dates render after deploy. |
| #72 Add recent usage and fatigue summary API for agents | Ready to close | `recent_usage_summary`, `round_analytics_summary`, `round_planning_brief` | None for API/MCP scope. |
| #73 Add MCP tool to draft round intro, replay, and outro scripts | Ready to close | `draft_round_audio_scripts`, MCP docs, round detail actions | Verify one draft for a real round after deploy. |
| #74 Store and review generated TTS scripts before audio assignment | Ready to close | `RoundAudioScript`, review routes, `generate_tts_from_script` | Verify approved script-to-audio assignment with configured TTS provider. |
| #75 Add chart and festival seed source registry | Partial | `SeedSource`, `SeedSourceRun`, admin views, MCP registry/run tools | Scrapers/importers for individual chart/festival providers remain separate slices. |
| #79 Add round ownership and sharing roles | Partial | `RoundShare`, `RoundAccessEvent`, owner filtering, edit checks, MCP share tools, browser share/revoke UI | Public links and richer roles remain open. |
| #126 Move production database configuration off SQLite `/data` | Operational / partial | Managed DB config, migration CLI, runbook, Compose managed-db profile | Live Kubernetes secret/config cutover and scheduled-email smoke remain. |
| #12 Remove SQLite/RWO singleton | Operational / partial | Same as #126, plus app config hardening | Requires managed DB cutover, stateless replicas, and backup replacement. |
| #17/#48/#49 Repair and clean broken round emails | Operational | Quality gate and repair tooling exist | Needs live QB/Gmail inspection and cleanup, not repo-only code. |

## Next Local Work Blocks

1. Close or comment the "ready to close" issues after a release smoke confirms
   the linked browser/MCP behavior.
2. For #75, add first provider-specific source fetchers on top of the registry.
3. For #79, add optional public read-only links and richer role policy around
   `RoundShare`.
5. For #126/#12, continue with live deployment configuration only through the
   existing 1Password-backed secret flow and credential-safe Kubernetes checks.
