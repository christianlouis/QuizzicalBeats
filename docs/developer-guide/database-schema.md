# Database Schema

This document provides an overview of the Quizzical Beats database schema, including tables, relationships, and key fields.

## Entity Relationship Diagram

The following diagram illustrates the relationships between the main entities in Quizzical Beats:

```
+---------------+       +---------------+       +---------------+
|    User       |       |    Round      |       |    Song       |
+---------------+       +---------------+       +---------------+
| id            |<----->| id            |       | id            |
| username      |       | name          |       | title         |
| email         |       | round_type    |       | artist        |
| password_hash |       | songs         |-------| spotify_id    |
| is_admin      |       | round_criteria|       | deezer_id     |
| roles         |----+  | created_at    |       | isrc          |
| auth_provider |    |  | updated_at    |       | preview_url   |
| oauth_tokens  |    |  | mp3_generated |       | cover_url     |
+---------------+    |  | pdf_generated |       | tags          |----+
      ^              |  +---------------+       | audio_features|    |
      |              |                          +---------------+    |
      |              |                                  ^            |
      |              v                                  |            |
+---------------+  +---------------+       +---------------+         |
| UserPreferences|  |    Role      |       | RoundExport   |         |
+---------------+  +---------------+       +---------------+         |
| id            |  | id            |       | id            |         |
| user_id       |  | name          |       | round_id      |         |
| default_tts   |  | description   |       | user_id       |         |
| enable_intro  |  +---------------+       | export_type   |         |
| theme         |                          | timestamp     |         |
+---------------+                          | destination   |         |
                                           +---------------+         |
                                                                     |
+---------------+                          +---------------+         |
| SystemSetting |                          |     Tag       |<--------+
+---------------+                          +---------------+
| id            |                          | id            |
| key           |                          | name          |
| value         |                          | created_at    |
+---------------+                          +---------------+
```

## Tables

### User

The `User` table stores user account information and authentication details.

| Column                | Type         | Description                                      |
|-----------------------|--------------|--------------------------------------------------|
| id                    | Integer      | Primary key                                      |
| username              | String(80)   | User's display name                              |
| email                 | String(120)  | User's email address                             |
| password_hash         | String(255)  | Hashed password (nullable for OAuth-only users)  |
| first_name            | String(50)   | User's first name                                |
| last_name             | String(50)   | User's last name                                 |
| active                | Boolean      | Account active status                            |
| is_admin              | Boolean      | Administrator privileges flag                    |
| created_at            | DateTime     | Account creation timestamp                       |
| last_login            | DateTime     | Last login timestamp                             |
| reset_token           | String(100)  | Password reset token                             |
| reset_token_expiry    | DateTime     | Token expiration time                            |
| auth_provider         | String(20)   | Authentication provider (local, google, etc.)    |
| spotify_id            | String(100)  | Spotify user ID                                  |
| spotify_token         | Text         | Spotify access token                             |
| spotify_refresh_token | Text         | Spotify refresh token                            |
| spotify_token_expiry  | DateTime     | Spotify token expiration                         |
| google_id             | String(100)  | Google user ID                                   |
| google_token          | Text         | Google access token                              |
| google_refresh_token  | Text         | Google refresh token                             |
| authentik_id          | String(100)  | Authentik user ID                                |
| authentik_token       | Text         | Authentik access token                           |
| authentik_refresh_token | Text       | Authentik refresh token                          |
| dropbox_id            | String(100)  | Dropbox user ID                                  |
| dropbox_token         | Text         | Dropbox access token                             |
| dropbox_refresh_token | Text         | Dropbox refresh token                            |
| dropbox_token_expiry  | DateTime     | Dropbox token expiration                         |
| dropbox_export_path   | String(255)  | User's preferred Dropbox export folder           |
| intro_mp3             | String(255)  | Custom intro MP3 path                            |
| outro_mp3             | String(255)  | Custom outro MP3 path                            |
| replay_mp3            | String(255)  | Custom replay MP3 path                           |

### UserPreferences

The `UserPreferences` table stores user-specific settings.

| Column               | Type         | Description                                      |
|----------------------|--------------|--------------------------------------------------|
| id                   | Integer      | Primary key                                      |
| user_id              | Integer      | Foreign key to User                              |
| default_tts_service  | String(32)   | Default text-to-speech service (polly, etc.)     |
| timezone             | String(64)   | User timezone for scheduling, default `Europe/Berlin` |
| enable_intro         | Boolean      | Whether to enable intro sound                    |
| theme                | String(16)   | UI theme preference (light, dark)                |
| import_job_email_notifications | Boolean | Whether import completion/repair emails are enabled for the user |
| oauth_token_email_notifications | Boolean | Whether Spotify/Dropbox token warning emails are enabled for the user |
| round_blocked_email_notifications | Boolean | Whether quality-gate repair emails are enabled for the user |

### Role

The `Role` table defines user roles for permission management.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| id          | Integer      | Primary key                                      |
| name        | String(50)   | Role name                                        |
| description | String(255)  | Role description                                 |

### user_roles

The `user_roles` table is an association table linking users to roles.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| user_id     | Integer      | Foreign key to User                              |
| role_id     | Integer      | Foreign key to Role                              |

### Song

The `Song` table stores detailed information about music tracks from various sources.

| Column                | Type         | Description                                     |
|-----------------------|--------------|-------------------------------------------------|
| id                    | Integer      | Primary key                                     |
| spotify_id            | String(100)  | Spotify track ID                                |
| deezer_id             | Integer      | Deezer track ID                                 |
| isrc                  | String(20)   | International Standard Recording Code           |
| title                 | String(200)  | Song title                                      |
| artist                | String(200)  | Artist name                                     |
| album_name            | String(200)  | Album name                                      |
| genre                 | String(100)  | Music genre                                     |
| year                  | Integer      | Release year                                    |
| preview_url           | String(500)  | Primary audio preview URL                       |
| cover_url             | String(500)  | Primary album cover URL                         |
| spotify_preview_url   | String(500)  | Spotify-specific preview URL                    |
| deezer_preview_url    | String(500)  | Deezer-specific preview URL                     |
| apple_preview_url     | String(500)  | Apple Music preview URL                         |
| youtube_preview_url   | String(500)  | YouTube preview URL                             |
| spotify_cover_url     | String(500)  | Spotify cover image URL                         |
| deezer_cover_url      | String(500)  | Deezer cover image URL                          |
| apple_cover_url       | String(500)  | Apple Music cover image URL                     |
| popularity            | Integer      | Popularity score (0-100)                        |
| used_count            | Integer      | Number of times used in rounds                  |
| source                | String(20)   | Data source (spotify, deezer, acrcloud)         |
| import_date           | DateTime     | When the song was imported                      |
| added_at              | DateTime     | When the song was added                         |
| last_used             | DateTime     | When the song was last used                     |
| metadata_sources      | String(500)  | Comma-separated list of metadata sources        |
| acousticness          | Float        | Spotify audio feature - acousticness (0.0-1.0)  |
| danceability          | Float        | Spotify audio feature - danceability (0.0-1.0)  |
| energy                | Float        | Spotify audio feature - energy (0.0-1.0)        |
| instrumentalness      | Float        | Spotify audio feature - instrumentalness        |
| key                   | Integer      | Spotify audio feature - musical key             |
| liveness              | Float        | Spotify audio feature - liveness (0.0-1.0)      |
| loudness              | Float        | Spotify audio feature - loudness (dB)           |
| mode                  | Integer      | Spotify audio feature - modality (major/minor)  |
| speechiness           | Float        | Spotify audio feature - speechiness (0.0-1.0)   |
| tempo                 | Float        | Spotify audio feature - tempo (BPM)             |
| time_signature        | Integer      | Spotify audio feature - time signature          |
| valence               | Float        | Spotify audio feature - valence (0.0-1.0)       |
| duration_ms           | Integer      | Track duration in milliseconds                  |
| analysis_url          | String(500)  | URL to full audio analysis                      |
| additional_data       | Text         | Additional data as JSON                         |

**Query indexes:**
- `idx_song_artist_title` supports catalog ordering and artist/title lookup.
- `idx_song_genre_year` supports genre/year round planning and filters.
- `idx_song_usage` supports least-used and recent-usage selection.

### Tag

The `Tag` table stores tags for categorizing songs.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| id          | Integer      | Primary key                                      |
| name        | String(50)   | Tag name                                         |
| created_at  | DateTime     | Creation timestamp                               |

### SongTag

The `SongTag` table links songs to tags.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| song_id     | Integer      | Foreign key to Song                              |
| tag_id      | Integer      | Foreign key to Tag                               |
| created_at  | DateTime     | When the tag was applied                         |

### Round

The `Round` table stores music quiz rounds.

| Column                | Type         | Description                                      |
|-----------------------|--------------|--------------------------------------------------|
| id                    | Integer      | Primary key                                      |
| name                  | String(200)  | Round name                                       |
| round_type            | String(50)   | Type of round (genre, decade, etc.)              |
| round_criteria_used   | String(500)  | Criteria used to generate the round              |
| songs                 | Text         | Comma-separated song IDs in saved order          |
| genre                 | String(100)  | Genre of the round (if applicable)               |
| decade                | String(10)   | Decade of the round (if applicable)              |
| tag                   | String(50)   | Tag of the round (if applicable)                 |
| user_id               | Integer      | Owning quizmaster, if assigned                   |
| visibility            | String(20)   | Round visibility (private, shared, public)       |
| public_token          | String(64)   | Token for read-only public link, when enabled    |
| public_token_created_at | DateTime   | When the public token was created                |
| created_at            | DateTime     | Creation timestamp                               |
| updated_at            | DateTime     | Last update timestamp                            |
| mp3_generated         | Boolean      | Flag indicating if MP3 has been generated        |
| pdf_generated         | Boolean      | Flag indicating if PDF has been generated        |
| last_generated_at     | DateTime     | When files were last generated                   |
| review_status         | String(20)   | draft, reviewed, approved, blocked, rejected, or sent |
| review_notes          | Text         | Human review notes or latest blocking reason     |
| approved_at           | DateTime     | When the round was approved for delivery         |
| approved_by_id        | Integer      | User who approved the round, if known            |

**Query indexes:**
- `idx_round_created_at` supports recent-round lists.
- `idx_round_generation_status` supports readiness and repair views.
- `idx_round_owner_created` supports per-quizmaster round history.
- `idx_round_public_token` supports token-based public round lookup.
- `idx_round_review_status` supports review queues and approval filters.

### RoundShare

The `RoundShare` table stores explicit round access grants.

| Column     | Type        | Description                          |
|------------|-------------|--------------------------------------|
| id         | Integer     | Primary key                          |
| round_id   | Integer     | Foreign key to Round                 |
| user_id    | Integer     | Foreign key to shared user           |
| role       | String(20)  | Share role (viewer, editor, producer) |
| created_at | DateTime    | When the share was created           |

### RoundAccessEvent

The `RoundAccessEvent` table stores an audit trail for ownership and sharing
changes on collaborative rounds.

| Column         | Type        | Description                                  |
|----------------|-------------|----------------------------------------------|
| id             | Integer     | Primary key                                  |
| round_id       | Integer     | Foreign key to Round                         |
| actor_user_id  | Integer     | User who performed the action, when known    |
| target_user_id | Integer     | User whose access changed, when applicable   |
| action         | String(40)  | Event type such as share_created/revoked     |
| role           | String(20)  | Role involved in the event                   |
| details        | Text        | Optional event details                       |
| created_at     | DateTime    | When the event was recorded                  |

### RoundAudioScript

The `RoundAudioScript` table stores reviewable intro, replay, and outro text
before it is turned into quizmaster audio.

| Column             | Type         | Description                                      |
|--------------------|--------------|--------------------------------------------------|
| id                 | Integer      | Primary key                                      |
| round_id           | Integer      | Foreign key to Round                             |
| user_id            | Integer      | Quizmaster whose audio this targets              |
| script_type        | String(20)   | intro, replay, or outro                          |
| text               | Text         | Script text for review                           |
| status             | String(20)   | draft, reviewed, approved, rejected, or used     |
| tone               | String(200)  | Intended tone                                    |
| theme              | String(200)  | Round theme or context                           |
| quiz_date          | DateTime     | Planned quiz date                                |
| selected           | Boolean      | Whether this draft is the selected version       |
| generated_mp3_path | String(500)  | Generated audio path after TTS assignment        |
| created_at         | DateTime     | Creation timestamp                               |
| updated_at         | DateTime     | Last update timestamp                            |

### SeedSource

The `SeedSource` table stores chart, festival, editorial, curated, and playlist
sources that agents can use when planning catalog enrichment.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| id          | Integer      | Primary key                                      |
| name        | String(200)  | Human-readable source name                       |
| source_type | String(50)   | chart, festival, editorial, curated, or playlist |
| provider    | String(100)  | Source owner/provider                            |
| url         | String(500)  | Source URL                                       |
| cadence     | String(50)   | Expected refresh cadence                         |
| active      | Boolean      | Whether agents should consider the source        |
| priority    | Integer      | Lower values are considered first                |
| notes       | Text         | Review notes and source constraints              |
| created_at  | DateTime     | Creation timestamp                               |
| updated_at  | DateTime     | Last update timestamp                            |

### SeedSourceRun

The `SeedSourceRun` table records read/import attempts for configured seed
sources.

| Column         | Type       | Description                                  |
|----------------|------------|----------------------------------------------|
| id             | Integer    | Primary key                                  |
| seed_source_id | Integer    | Foreign key to SeedSource                    |
| status         | String(30) | planned, running, success, partial, failed   |
| started_at     | DateTime   | Run start timestamp                          |
| completed_at   | DateTime   | Run completion timestamp                     |
| songs_seen     | Integer    | Candidate songs seen in the source           |
| songs_imported | Integer    | Songs imported or linked from the source     |
| error_message  | Text       | Safe failure summary                         |
| notes          | Text       | Run notes                                    |

### RoundExport

The `RoundExport` table tracks exports of rounds to various destinations.

| Column        | Type         | Description                                      |
|---------------|--------------|--------------------------------------------------|
| id            | Integer      | Primary key                                      |
| round_id      | Integer      | Foreign key to Round                             |
| user_id       | Integer      | Foreign key to User                              |
| export_type   | String(20)   | Export type (dropbox, email, etc.)               |
| timestamp     | DateTime     | Export timestamp                                 |
| destination   | String(500)  | Destination (path, email, etc.)                  |
| include_mp3s  | Boolean      | Whether MP3s were included                       |
| status        | String(20)   | Export status (success, failed)                  |
| error_message | Text         | Error message if export failed                   |
| scheduled_for | DateTime     | Deferred email send time                         |
| processed_at  | DateTime     | When a scheduled export was processed            |
| subject       | String(500)  | Scheduled or sent email subject                  |
| body_text     | Text         | Scheduled or sent email body                     |

**Query indexes:**
- `idx_round_export_schedule` supports due scheduled-email processing.
- `idx_round_export_round_timestamp` supports round export history views.

### PlannedQuizRound

The `PlannedQuizRound` table stores upcoming quiz dates before a concrete round
or scheduled export exists.

| Column              | Type         | Description                                      |
|---------------------|--------------|--------------------------------------------------|
| id                  | Integer      | Primary key                                      |
| quiz_date           | DateTime     | Planned quiz date                                |
| quizmaster_id       | Integer      | Optional foreign key to User                     |
| theme               | String(200)  | Optional theme or planning label                 |
| brief               | Text         | Agent-facing planning notes                      |
| source_playlist_url | String(500)  | Optional source playlist URL                     |
| due_at              | DateTime     | Optional internal due time before send           |
| status              | String(20)   | planned, drafted, blocked, approved, scheduled, or sent |
| round_id            | Integer      | Optional foreign key to generated Round          |
| export_id           | Integer      | Optional foreign key to scheduled RoundExport    |
| created_at          | DateTime     | Creation timestamp                               |
| updated_at          | DateTime     | Last update timestamp                            |

**Query indexes:**
- `idx_planned_quiz_round_status_due` supports production-board and due-soon
  lookups.
- `idx_planned_quiz_round_quizmaster_date` supports per-quizmaster planning
  views.

### SystemSetting

The `SystemSetting` table stores application-wide settings.

| Column      | Type         | Description                                      |
|-------------|--------------|--------------------------------------------------|
| id          | Integer      | Primary key                                      |
| key         | String(64)   | Setting key                                      |
| value       | Text         | Setting value                                    |

## Key Relationships

### User Relationships

- **User → UserPreferences**: One-to-one. A user has one set of preferences.
- **User ↔ Roles**: Many-to-many through user_roles. A user can have multiple roles, and a role can be assigned to multiple users.
- **User → RoundExports**: One-to-many. A user can create multiple exports.
- **User → PlannedQuizRounds**: One-to-many. A quizmaster can own multiple
  planned quiz dates.

### Song Relationships

- **Song ↔ Tags**: Many-to-many through SongTag. A song can have multiple tags, and a tag can be applied to multiple songs.
- **Song → Rounds**: Many-to-many (implicit). Songs are referenced in the Round.songs field as a JSON string of IDs.

### Round Relationships

- **Round → RoundExports**: One-to-many. A round can have multiple exports.
- **Round → Songs**: Many-to-many (implicit). A round contains multiple songs referenced by ID.
- **Round → PlannedQuizRounds**: One-to-many. A planned quiz date can point at
  the generated round once it exists.

## Data Model Features

### OAuth Integration

The User model integrates OAuth provider information directly:
- Support for Spotify, Google, Authentik and Dropbox OAuth providers
- Token storage and refresh token functionality
- Provider-specific user IDs

### Audio Features

The Song model includes detailed audio features from Spotify:
- Acoustic characteristics (acousticness, instrumentalness)
- Rhythmic characteristics (tempo, time_signature)
- Mood characteristics (valence, energy, danceability)
- Technical characteristics (loudness, key, mode)

### Multi-Source Integration

Songs can be imported from multiple sources:
- Spotify API
- Deezer API
- ACRCloud identification service
- Each song stores source-specific IDs and URLs

### Tagging System

The tagging system allows flexible organization:
- Songs can be tagged for easier categorization
- Tags provide a way to group songs by custom criteria

## Data Migrations

The database schema evolves over time through migrations. Migration scripts are stored in the `migrations/` directory:

- `add_preview_urls.py`: Added Song.preview_url field
- `add_song_fields.py`: Added additional metadata fields to Song
- `add_spotify_audio_features.py`: Added audio analysis data
- `add_oauth_providers.py`: Extended OAuth provider support
- `add_tag_system.py`: Added tagging functionality
- `add_dropbox_oauth.py`: Added Dropbox OAuth support
- `add_dropbox_export_path.py`: Added export path tracking
