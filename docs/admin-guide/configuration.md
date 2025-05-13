# Configuration Guide

This guide explains how to configure Quizzical Beats for different environments and use cases.

## Environment Variables

Quizzical Beats uses environment variables for configuration. These can be set in the `.env` file or directly in your environment.

### Core Configuration

```bash
# Debug settings
DEBUG=True
DEBUG2=False
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
# SQLite (default)
SQLALCHEMY_DATABASE_URI=sqlite:///data/song_data.db
SQLALCHEMY_TRACK_MODIFICATIONS=False

# For MySQL/MariaDB:
# SQLALCHEMY_DATABASE_URI=mysql+pymysql://username:password@localhost/musicround

# For PostgreSQL:
# SQLALCHEMY_DATABASE_URI=postgresql://username:password@localhost/musicround
```

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
```

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
SQLALCHEMY_DATABASE_URI=sqlite:///data/song_data.db
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