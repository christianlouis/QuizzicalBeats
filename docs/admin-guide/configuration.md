# Configuration Guide

This guide explains how to configure Quizzical Beats for different environments and use cases.

## Environment Variables

Quizzical Beats uses environment variables for configuration. These can be set in the `.env` file or directly in your environment.

### Core Configuration

```bash
# Debug settings
DEBUG=True
SECRET_KEY=your-secret-key-here-make-it-long-and-random
```

### API Keys and Services

```bash
# OpenAI API settings
OPENAI_API_KEY=your-openai-api-key
OPENAI_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_SEARCH_MODEL=gpt-4o-mini-search-preview

# Translation and language services
DEEPL_API_KEY=your-deepl-api-key
MEANINGCLOUD_API_KEY=your-meaningcloud-api-key

# Audio services
ELEVENLABS_API_KEY=your-elevenlabs-api-key
ACRCLOUD_TOKEN=your-acrcloud-token

# Music APIs
LASTFM_API_KEY=your-lastfm-api-key
```

## Music Metadata APIs

Quizzical Beats uses multiple API services to gather comprehensive music metadata. Configuring these services enhances the quality and completeness of your music library.

### Last.fm

Last.fm provides genre information and tag data that's often missing from streaming services:

- **Configuration**: Set the `LASTFM_API_KEY` environment variable
- **Usage**: Automatically enriches tracks with genre metadata
- **Benefits**: Improves genre-based round generation
- **Obtain API Key**: [Last.fm API](https://www.last.fm/api/account/create)

### Spotify

Spotify provides comprehensive track metadata and audio features analysis:

- **Configuration**: Set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
- **Usage**: Primary source for song previews, artwork, and audio characteristics
- **Benefits**: Enables audio feature analysis (tempo, danceability, energy, etc.)
- **Obtain API Keys**: [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)

### Deezer

Deezer serves as an alternative source for track metadata and previews:

- **Configuration**: Set `DEEZER_APP_ID` and `DEEZER_APP_SECRET`
- **Usage**: Alternative source when Spotify data is unavailable
- **Benefits**: Provides additional preview URLs and metadata
- **Obtain API Keys**: [Deezer Developers](https://developers.deezer.com/myapps)

### ACRCloud

ACRCloud can be used for music recognition and metadata enrichment:

- **Configuration**: Set `ACRCLOUD_TOKEN`
- **Usage**: Identify songs from audio samples
- **Benefits**: Enhanced metadata lookups using audio fingerprinting
- **Obtain API Keys**: [ACRCloud](https://www.acrcloud.com/)

### Metadata Enrichment Process

When a song is imported into Quizzical Beats:

1. The system first checks if the song has an ISRC (International Standard Recording Code)
2. If an ISRC is available, it's used to find metadata across all configured services
3. The system consolidates data from multiple sources to create a comprehensive record
4. If an ISRC is unavailable, the system relies on the original source's data
5. Genre information is converted to tags for improved searchability

For optimal metadata quality, we recommend configuring at least Spotify and Last.fm APIs.

### Database Configuration

```bash
# SQLite fallback for local development. Leave SQLALCHEMY_DATABASE_URI unset.
SQLALCHEMY_TRACK_MODIFICATIONS=False

# Application file storage
DATA_DIR=/data
ROUND_ARTIFACT_STORAGE_BACKEND=filesystem
ROUND_MP3_DIR=/data/rounds
ROUND_PDF_DIR=/data/pdfs

# S3-compatible generated-artifact storage (optional)
# Keep ROUND_ARTIFACT_STORAGE_BACKEND=filesystem until this bucket has been
# verified with `python run.py storage readiness --json`.
# ROUND_ARTIFACT_STORAGE_BACKEND=s3
# ROUND_ARTIFACT_S3_ENDPOINT_URL=https://s3.example.net
# ROUND_ARTIFACT_S3_BUCKET=quizzicalbeats-artifacts
# ROUND_ARTIFACT_S3_PREFIX=production
# ROUND_ARTIFACT_S3_REGION=eu-central-1
# ROUND_ARTIFACT_S3_ACCESS_KEY_ID=...
# ROUND_ARTIFACT_S3_SECRET_ACCESS_KEY=...
# ROUND_ARTIFACT_S3_ADDRESSING_STYLE=auto
# ROUND_ARTIFACT_CACHE_DIR=/tmp/quizzicalbeats-artifacts

# For MySQL/MariaDB:
# SQLALCHEMY_DATABASE_URI=mysql+pymysql://username:password@localhost/musicround

# For PostgreSQL:
# SQLALCHEMY_DATABASE_URI=postgresql://username:password@localhost/musicround

# Or use split PostgreSQL variables for secretKeyRef-based deployments:
# DATABASE_REQUIRE_MANAGED=true
# PGHOST=postgres-rw.namespace.svc.cluster.local
# PGPORT=5432
# PGDATABASE=quizzicalbeats
# PGUSER=quizzicalbeats
# PGPASSWORD=change-me
```

When `SQLALCHEMY_DATABASE_URI` is omitted, the local SQLite fallback is created
as `song_data.db` inside `DATA_DIR`. Production deployments should configure
PostgreSQL instead and enable `DATABASE_REQUIRE_MANAGED=true`. If both
`SQLALCHEMY_DATABASE_URI` and `PG*` variables are set, the full URI wins; remove
or blank it before relying on split PostgreSQL variables. The database status,
preflight, and health diagnostics warn when a full URI is masking complete
split PostgreSQL configuration so the managed-database cutover does not silently
keep using the old `/data` SQLite target.

`ROUND_ARTIFACT_STORAGE_BACKEND=filesystem` is the only supported generated
round artifact backend today. It is valid for single-writer deployments and is
health-checked before MP3/PDF generation, scheduling, and email delivery. The
health payload also reports storage capabilities: filesystem storage supports
direct file paths but remains HA-blocking for multi-replica web deployments
until MP3/PDF artifacts move to shared or object storage.

### Response Compression

```bash
RESPONSE_COMPRESSION_ENABLED=True
RESPONSE_COMPRESSION_MIN_BYTES=1024
# Optional comma-separated override for text-like response types:
# RESPONSE_COMPRESSION_MIMETYPES=text/html,text/css,application/json
```

Quizzical Beats can gzip large text-like responses when the client advertises
`Accept-Encoding: gzip`. Binary round artifacts such as PDFs, MP3s, and ZIP
downloads are intentionally left untouched. Set
`RESPONSE_COMPRESSION_ENABLED=False` when compression is owned entirely by the
reverse proxy.

### Static Asset Caching

```bash
STATIC_ASSET_CACHE_ENABLED=True
STATIC_ASSET_CACHE_SECONDS=86400
```

When Flask serves static CSS, JavaScript, image, or default audio assets, QB adds
bounded public cache headers. Disable this when static files are served directly
by Nginx, a CDN, or another edge layer that owns cache policy.

### Deployment Smoke

```bash
QB_SMOKE_BASE_URL=https://qb.kaufdeinquiz.com
python run.py deployment smoke --json
```

The deployment smoke checks the public `/healthz` endpoint, security headers,
non-development server header, static asset cache headers, and gzip behavior on
a public text-like page. Override `--static-path` or `--compression-path` when a
deployment uses different public probe paths.

### OAuth Provider Configuration

```bash
# Spotify API configuration
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=http://localhost:5000/auth/spotify/callback

# Deezer API configuration
DEEZER_APP_ID=your-deezer-app-id
DEEZER_APP_SECRET=your-deezer-app-secret
DEEZER_REDIRECT_URI=http://localhost:5000/deezer-callback

# Google OAuth configuration
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Authentik OAuth configuration
AUTHENTIK_CLIENT_ID=your-authentik-client-id
AUTHENTIK_CLIENT_SECRET=your-authentik-client-secret
AUTHENTIK_METADATA_URL=https://authentik.example.com/.well-known/openid-configuration

# Dropbox OAuth configuration
DROPBOX_APP_KEY=your-dropbox-app-key
DROPBOX_APP_SECRET=your-dropbox-app-secret
DROPBOX_REDIRECT_URI=http://localhost:5000/users/dropbox/callback

# Optional admin-only OAuth URL diagnostics. Keep disabled in production unless
# actively troubleshooting redirect/proxy configuration.
ENABLE_OAUTH_DEBUG=False
```

### Email Configuration

```bash
# Email settings
MAIL_HOST=smtp.example.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USE_SSL=False
MAIL_USERNAME=your-email-username
MAIL_PASSWORD=your-email-password
MAIL_SENDER=quizzical-beats@example.com
MAIL_RECIPIENT=admin@example.com
IMPORT_JOB_EMAIL_NOTIFICATIONS=False
```

Set `IMPORT_JOB_EMAIL_NOTIFICATIONS=True` to notify the owning user when an
import job completes or exhausts automatic retries and needs manual review.
Users can still opt out of these status emails from their profile.

Preview OAuth connection warning emails without sending:

```bash
python run.py notifications oauth-tokens
```

Send pending Spotify/Dropbox expiry or reconnect warnings:

```bash
python run.py notifications oauth-tokens --send
```

The job respects each user's notification preferences and suppresses duplicate
warnings for the same service issue for 24 hours.

Preview SMTP configuration without sending a message:

```bash
python run.py notifications verify-email
```

Send a test email to `MAIL_RECIPIENT`, or override the target with
`--recipient`:

```bash
python run.py notifications verify-email --send
```

Preview an administrator digest of pending notification work:

```bash
python run.py notifications admin-summary
```

Send the digest to `MAIL_RECIPIENT`, or override the target with `--recipient`:

```bash
python run.py notifications admin-summary --send
```

The admin digest includes failed round email exports, dead-letter import jobs,
OAuth reconnect warnings, public service-health issues, and backup-readiness
findings such as managed SQL deployments that still need native database
snapshots or dumps.

When a round fails the package quality gate during email delivery or scheduling,
Quizzical Beats sends the owning quizmaster a repair email with the generated
quality report and repair hints. Users can disable these blocked-round emails
from their profile; duplicate notifications for the same round failure are
suppressed for 24 hours.

### Automation Settings

```bash
# Used for automated tasks and API access
AUTOMATION_TOKEN=your-secure-automation-token
```

## Configuration File (.env)

Create a `.env` file in the root directory with your configuration variables. You can copy the provided `.env.demo` file as a starting point:

```bash
cp .env.demo .env
```

Then edit the `.env` file with your actual configuration values:

```bash
# Example .env file (simplified)
SECRET_KEY=your-secure-secret-key
DEBUG=True
SQLALCHEMY_DATABASE_URI=sqlite:////data/song_data.db
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
# Add other variables as needed
```

## Configuration Priority

Quizzical Beats loads configuration in the following order of priority:

1. Environment variables set in the system
2. Variables in the `.env` file
3. Default values defined in the `config.py` file

## Docker Environment Variables

When using Docker, you can pass environment variables through the `docker-compose.yml` file:

```yaml
version: '3'
services:
  app:
    build: .
    environment:
      - SECRET_KEY=your-secure-secret-key
      - SQLALCHEMY_DATABASE_URI=postgresql://postgres:password@db/musicround
      - SPOTIFY_CLIENT_ID=your-spotify-client-id
      - SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
      # Add other variables as needed
    volumes:
      - ./data:/app/data
```

## Required Configuration

The following variables are required for core functionality:

- `SECRET_KEY`: Used for securing sessions and CSRF tokens
- `SQLALCHEMY_DATABASE_URI`: Database connection string

## Optional Configuration

These configurations enable additional features:

### Spotify Integration

Required for importing playlists and tracks from Spotify:
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REDIRECT_URI`

### Dropbox Integration

Required for exporting rounds to Dropbox:
- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REDIRECT_URI`

### OAuth Authentication

Required for sign-in with external providers:
- Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Authentik: `AUTHENTIK_CLIENT_ID`, `AUTHENTIK_CLIENT_SECRET`, `AUTHENTIK_METADATA_URL`

## Applying Configuration Changes

After changing configuration:

1. For a standard installation, restart the application:
   ```bash
   sudo systemctl restart quizzical-beats
   # Or if using Gunicorn directly:
   kill -HUP $(cat gunicorn.pid)
   ```

2. For Docker installations:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## Verifying Configuration

To verify your configuration:

1. Check the application logs after startup
2. Visit the Admin > System > Settings page in the web interface
3. Check the system health on the Admin > System > Health Dashboard page
