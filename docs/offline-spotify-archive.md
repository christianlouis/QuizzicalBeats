# Offline Spotify Archive

QuizzicalBeats can enrich existing songs from the July 2025 Spotify metadata
snapshot without calling the live Spotify API. The archive is an internal-only,
read-only service; it does not serve music, previews, or user-facing search
results automatically.

## Data Sets

The archive PVC holds two SQLite files:

| File | Purpose |
| --- | --- |
| `spotify_clean.sqlite3` | Track metadata, exact ISRC and Spotify-ID lookup, release year, duration, album, and snapshot popularity. |
| `spotify_clean_audio_features.sqlite3` | Exact Spotify-ID lookup for tempo, key, mode, time signature, loudness, and the standard Spotify audio features. |

Both files are opened with `mode=ro`, `immutable=1`, an 8 MiB SQLite page
cache, disabled memory mapping, and file-backed temporary tables. The service
therefore does not load either archive into application memory.

## Matching Rules

1. Deezer is the default low-cost provider for missing ISRCs and baseline
   metadata. Existing Deezer IDs are authoritative lookup keys.
2. The archive maps only exact ISRCs or exact Spotify IDs. It never assigns a
   song from a title-only search.
3. A Deezer batch can be pipelined into bounded archive identifier lookups.
   These lookups read only `tracks` and `albums`, avoiding expensive artist and
   cover joins.
4. A full catalog true-up uses one or more disk-backed sequential scans. This
   is preferable to large numbers of random reads on the RWO archive volume.
5. Audio features are filled only when a QB field is empty. Curated values are
   not overwritten.

Every archive write records provenance in `metadata_sources` and
`additional_data`:

- `spotify_archive_2025_07` for exact ISRC metadata
- `spotify_archive_2025_07_audio_features` for audio features

## Internal Service

The service runs as `quizzicalbeats-spotify-archive` and is reachable only
inside the cluster through `SPOTIFY_ARCHIVE_CATALOG_URL`.

| Endpoint | Use |
| --- | --- |
| `GET /healthz` | Check that both SQLite files are present. |
| `GET /v1/search` | Review-only interactive identifier or text search. |
| `POST /v1/isrc-lookup` | Bounded exact ISRC batch lookup. |
| `POST /v1/isrc-bulk-lookup` | Disk-backed sequential ISRC true-up. |
| `POST /v1/audio-features-bulk-lookup` | Disk-backed exact Spotify-ID audio-feature true-up. |

The reader is pinned to the archive PVC's RWO node and uses a `Recreate`
deployment strategy. This prevents a rolling update from attempting a
multi-node volume attachment.

## Operations

For a catalog maintenance run, use this order:

1. Enrich songs with existing Deezer IDs, with paced requests.
2. Resolve each completed batch through exact archive ISRC lookup.
3. Run the offline audio-feature true-up after new Spotify IDs are stored.
4. Verify coverage and provenance in PostgreSQL before closing the operation.

One-off bulk jobs are operational artifacts. Remove their GitOps resource after
completion; retain the reusable matching and provenance logic in application
code.
