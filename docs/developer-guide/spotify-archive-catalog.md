# Offline Spotify Archive Catalog

Quizzical Beats can optionally search a self-hosted, read-only SQLite snapshot
of Spotify track metadata. It is a discovery and enrichment aid, not a source
of playable media.

## Boundaries

- Store and query metadata only. Do not download, ingest, or serve audio files.
- Keep the archive outside the QB PostgreSQL database and `/data` artifact PVC.
- Candidates are review-only. Resolve a selected recording through Deezer before
  using a current preview in a music round.
- Preserve the snapshot provenance as `spotify_archive_2025_07`; it is not a
  current-live popularity signal.

## Runtime Model

The `musicround.spotify_archive_catalog` process opens
`spotify_clean.sqlite3` with `mode=ro`, `immutable=1`, `query_only=ON`,
`mmap_size=0`, and an 8 MiB SQLite page cache. The process never loads the
catalog into Python memory.

Identifier searches use the source Spotify-ID and ISRC indexes. Freitext
queries are limited to a configured popularity floor and interrupted after two
seconds, so a large catalog cannot monopolize the API pod.

The QB browser calls its authenticated `/api/songs/archive-search` proxy. The
internal catalog service must never be exposed through a public ingress.

## ISRC Metadata Backfill

Once the catalog service is healthy, `backfill_songs_from_spotify_archive`
matches QB songs by ISRC in batches of up to 500. It fills missing Spotify IDs,
album/year/duration/cover metadata, repairs missing popularity values, and
records the archive snapshot in `additional_data` and `metadata_sources`.

The backfill does not replace an existing preview URL, title, artist, or valid
current popularity score. Use its dry-run output before an all-catalog write.

## Kubernetes Bootstrap

The GitOps manifest provides a one-shot download Job and a separate catalog
Deployment. The Job selects only `spotify_clean.sqlite3.zst` from the supplied
metadata torrent, uses `seed-time=0` and `seed-ratio=0`, caps unavoidable
in-progress upload bandwidth, validates the SQLite schema, and removes the
compressed copy after decompression.

The catalog Deployment starts at zero replicas because the archive PVC is RWO.
After the Job succeeds, inspect its logs and the resulting file, then change
the Deployment to one replica in GitOps. This avoids a multi-attach race.
