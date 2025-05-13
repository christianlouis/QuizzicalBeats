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
| oauth_id              | String(100)  | Spotify user ID                                  |
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
| enable_intro         | Boolean      | Whether to enable intro sound                    |
| theme                | String(16)   | UI theme preference (light, dark)                |

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
| songs                 | Text         | JSON string of song IDs in order                 |
| genre                 | String(100)  | Genre of the round (if applicable)               |
| decade                | String(10)   | Decade of the round (if applicable)              |
| tag                   | String(50)   | Tag of the round (if applicable)                 |
| created_at            | DateTime     | Creation timestamp                               |
| updated_at            | DateTime     | Last update timestamp                            |
| mp3_generated         | Boolean      | Flag indicating if MP3 has been generated        |
| pdf_generated         | Boolean      | Flag indicating if PDF has been generated        |
| last_generated_at     | DateTime     | When files were last generated                   |

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

### Song Relationships

- **Song ↔ Tags**: Many-to-many through SongTag. A song can have multiple tags, and a tag can be applied to multiple songs.
- **Song → Rounds**: Many-to-many (implicit). Songs are referenced in the Round.songs field as a JSON string of IDs.

### Round Relationships

- **Round → RoundExports**: One-to-many. A round can have multiple exports.
- **Round → Songs**: Many-to-many (implicit). A round contains multiple songs referenced by ID.

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