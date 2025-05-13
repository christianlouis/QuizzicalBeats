# API Reference

This document provides a comprehensive reference for the Quizzical Beats API endpoints.

## Authentication

All API endpoints require authentication unless specified otherwise.

### Authentication Methods

The API supports two authentication methods:

1. **Session Cookie**: For browser-based applications
2. **API Key**: For programmatic access

#### API Key Authentication

To use API key authentication:

1. Generate an API key in your profile settings
2. Include the key in the `X-API-Key` header with each request:
   ```
   X-API-Key: your-api-key-here
   ```

### Rate Limiting

API requests are rate-limited to prevent abuse:

- 100 requests per hour for standard users
- 300 requests per hour for admin users

Rate limit headers are included in all responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1620567890
```

## Response Format

All API responses are in JSON format with a consistent structure:

```json
{
  "status": "success|error",
  "data": { ... },
  "message": "Optional message",
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 42,
    "pages": 3
  }
}
```

## Error Handling

When an error occurs, the response will have status code 4xx or 5xx and include an error message:

```json
{
  "status": "error",
  "message": "Descriptive error message",
  "code": "ERROR_CODE"
}
```

Common error codes:
- `UNAUTHORIZED`: Authentication failed
- `FORBIDDEN`: Permission denied
- `NOT_FOUND`: Resource not found
- `VALIDATION_ERROR`: Invalid input data
- `RATE_LIMITED`: Rate limit exceeded

## API Endpoints

### User Endpoints

#### Get Current User

```
GET /api/user
```

Returns information about the currently authenticated user.

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 123,
    "username": "john_doe",
    "email": "john@example.com",
    "is_admin": false,
    "created_at": "2025-01-15T12:34:56Z"
  }
}
```

#### Update User Profile

```
PUT /api/user
```

Update the current user's profile information.

**Request Body:**
```json
{
  "username": "new_username",
  "email": "new_email@example.com"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 123,
    "username": "new_username",
    "email": "new_email@example.com",
    "is_admin": false,
    "created_at": "2025-01-15T12:34:56Z"
  },
  "message": "Profile updated successfully"
}
```

### Song Endpoints

#### List Songs

```
GET /api/songs
```

Returns a paginated list of songs in the user's library.

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)
- `search`: Search term
- `sort`: Sort field (title, artist, album, year)
- `order`: Sort order (asc, desc)
- `genre`: Filter by genre
- `year`: Filter by year

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": 456,
      "title": "Song Title",
      "artist": "Artist Name",
      "album": "Album Name",
      "year": 2010,
      "genre": "Rock",
      "preview_url": "https://example.com/preview.mp3",
      "spotify_id": "spotify:track:abcdef123456",
      "duration_ms": 240000
    },
    // More songs...
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 42,
    "pages": 3
  }
}
```

#### Get Song

```
GET /api/songs/{id}
```

Returns detailed information about a specific song.

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 456,
    "title": "Song Title",
    "artist": "Artist Name",
    "album": "Album Name",
    "year": 2010,
    "genre": "Rock",
    "preview_url": "https://example.com/preview.mp3",
    "spotify_id": "spotify:track:abcdef123456",
    "duration_ms": 240000,
    "added_by": 123,
    "created_at": "2025-02-10T15:30:45Z",
    "popularity": 75,
    "tags": [
      {
        "id": 789,
        "name": "Summer Hits",
        "color": "#ff5500"
      }
    ]
  }
}
```

#### Create Song

```
POST /api/songs
```

Add a new song to the user's library.

**Request Body:**
```json
{
  "title": "New Song",
  "artist": "New Artist",
  "album": "New Album",
  "year": 2025,
  "genre": "Pop",
  "spotify_id": "spotify:track:xyz789",
  "preview_url": "https://example.com/preview.mp3"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 457,
    "title": "New Song",
    "artist": "New Artist",
    "album": "New Album",
    "year": 2025,
    "genre": "Pop",
    "preview_url": "https://example.com/preview.mp3",
    "spotify_id": "spotify:track:xyz789",
    "added_by": 123,
    "created_at": "2025-05-11T09:12:34Z"
  },
  "message": "Song added successfully"
}
```

#### Update Song

```
PUT /api/songs/{id}
```

Update an existing song.

**Request Body:**
```json
{
  "title": "Updated Title",
  "artist": "Updated Artist",
  "album": "Updated Album",
  "year": 2020,
  "genre": "Electronic"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 456,
    "title": "Updated Title",
    "artist": "Updated Artist",
    "album": "Updated Album",
    "year": 2020,
    "genre": "Electronic",
    "preview_url": "https://example.com/preview.mp3",
    "spotify_id": "spotify:track:abcdef123456"
  },
  "message": "Song updated successfully"
}
```

#### Delete Song

```
DELETE /api/songs/{id}
```

Remove a song from the user's library.

**Response:**
```json
{
  "status": "success",
  "message": "Song deleted successfully"
}
```

### Round Endpoints

#### List Rounds

```
GET /api/rounds
```

Returns a paginated list of the user's quiz rounds.

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)
- `search`: Search term
- `sort`: Sort field (name, created_at)
- `order`: Sort order (asc, desc)
- `tag`: Filter by tag ID

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": 789,
      "name": "80s Rock Classics",
      "description": "Classic rock hits from the 1980s",
      "created_at": "2025-03-20T14:25:36Z",
      "song_count": 10,
      "round_type": "decade",
      "tags": [
        {
          "id": 123,
          "name": "80s",
          "color": "#3366ff"
        },
        {
          "id": 456,
          "name": "Rock",
          "color": "#cc0000"
        }
      ]
    },
    // More rounds...
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 15,
    "pages": 1
  }
}
```

#### Get Round

```
GET /api/rounds/{id}
```

Returns detailed information about a specific round, including its songs.

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 789,
    "name": "80s Rock Classics",
    "description": "Classic rock hits from the 1980s",
    "created_at": "2025-03-20T14:25:36Z",
    "user_id": 123,
    "is_public": true,
    "round_type": "decade",
    "intro_file": "/mp3/intros/80s_intro.mp3",
    "outro_file": "/mp3/outros/rock_outro.mp3",
    "songs": [
      {
        "id": 101,
        "title": "Sweet Child O' Mine",
        "artist": "Guns N' Roses",
        "year": 1987,
        "position": 1,
        "question": "Name this iconic 80s rock song",
        "answer": "Sweet Child O' Mine by Guns N' Roses",
        "points": 10,
        "preview_url": "https://example.com/preview1.mp3"
      },
      // More songs...
    ],
    "tags": [
      {
        "id": 123,
        "name": "80s",
        "color": "#3366ff"
      },
      {
        "id": 456,
        "name": "Rock",
        "color": "#cc0000"
      }
    ]
  }
}
```

#### Create Round

```
POST /api/rounds
```

Create a new quiz round.

**Request Body:**
```json
{
  "name": "New Quiz Round",
  "description": "A fresh music quiz round",
  "round_type": "mixed",
  "is_public": true,
  "song_ids": [101, 102, 103, 104],
  "tag_ids": [123, 456]
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 790,
    "name": "New Quiz Round",
    "description": "A fresh music quiz round",
    "created_at": "2025-05-11T10:15:20Z",
    "user_id": 123,
    "is_public": true,
    "round_type": "mixed",
    "song_count": 4
  },
  "message": "Round created successfully"
}
```

#### Update Round

```
PUT /api/rounds/{id}
```

Update an existing round.

**Request Body:**
```json
{
  "name": "Updated Round Name",
  "description": "Updated description",
  "is_public": false,
  "song_ids": [101, 102, 105, 106],
  "tag_ids": [123, 789]
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": 789,
    "name": "Updated Round Name",
    "description": "Updated description",
    "is_public": false,
    "song_count": 4
  },
  "message": "Round updated successfully"
}
```

#### Delete Round

```
DELETE /api/rounds/{id}
```

Delete a quiz round.

**Response:**
```json
{
  "status": "success",
  "message": "Round deleted successfully"
}
```

### Export Endpoints

#### Export Round to Dropbox

```
POST /rounds/{round_id}/export-to-dropbox
```

Export a round to the user's connected Dropbox account.

**Request Body Parameters:**
```
include_mp3s: boolean (default: true) - Whether to include MP3 files in the export
include_pdf: boolean (default: true) - Whether to include PDF in the export
custom_folder: string (optional) - Additional subfolder path within the user's configured export path
```

**Response:**
```json
{
  "success": true,
  "message": "Round exported to Dropbox successfully",
  "shared_links": {
    "text": "https://www.dropbox.com/s/abc123/round_123_metadata.json?dl=0",
    "pdf": "https://www.dropbox.com/s/def456/round_123.pdf?dl=0",
    "mp3": "https://www.dropbox.com/s/ghi789/round_123.mp3?dl=0"
  }
}
```

**Error Response:**
```json
{
  "success": false,
  "message": "Error exporting to Dropbox: <error details>",
  "redirect": "URL for MP3 generation if needed"
}
```

#### List Dropbox Folders

```
GET /api/dropbox/folders
```

List folders from the user's Dropbox account.

**Query Parameters:**
```
path: string - The path to list folders from (default: root)
```

**Response:**
```json
{
  "success": true,
  "folders": [
    {
      "name": "Folder Name",
      "path": "/Folder Name",
      "is_dir": true
    },
    {
      "name": "Documents",
      "path": "/Documents",
      "is_dir": true
    }
  ]
}
```

#### Create Dropbox Folder

```
POST /api/dropbox/create-folder
```

Create a new folder in the user's Dropbox account.

**Request Body:**
```json
{
  "parent_path": "/path/to/parent",
  "folder_name": "New Folder"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Folder created successfully",
  "folder": {
    "name": "New Folder",
    "path": "/path/to/parent/New Folder",
    "is_dir": true
  }
}
```

### Dropbox OAuth Endpoints

#### Connect Dropbox Account

```
GET /users/dropbox/connect
```

Initiates the OAuth flow for connecting a Dropbox account.

**Response:**
Redirects to Dropbox OAuth authorization page

#### Dropbox OAuth Callback

```
GET /users/dropbox/callback
```

Handles the OAuth callback from Dropbox.

**Query Parameters:**
```
code: string - The authorization code from Dropbox
error: string - Error message if authorization failed
```

**Response:**
Redirects back to user profile page with a success or error message

#### Disconnect Dropbox Account

```
POST /users/dropbox/disconnect
```

Disconnects the user's Dropbox account.

**Response:**
Redirects back to user profile page with a success message

### Spotify Integration Endpoints

#### Get User Playlists

```
GET /api/spotify/playlists
```

Get the current user's Spotify playlists.

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": "spotify:playlist:abcdef123456",
      "name": "My Awesome Playlist",
      "owner": "spotify_user123",
      "track_count": 42,
      "image_url": "https://example.com/playlist_cover.jpg"
    },
    // More playlists...
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 35,
    "pages": 2
  }
}
```

#### Import Playlist

```
POST /api/spotify/import/playlist
```

Import songs from a Spotify playlist.

**Request Body:**
```json
{
  "playlist_id": "spotify:playlist:abcdef123456",
  "limit": 20
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "import_id": "imp_789012",
    "playlist_name": "My Awesome Playlist",
    "status": "processing",
    "songs_found": 42,
    "songs_to_import": 20,
    "estimated_completion": "45 seconds"
  },
  "message": "Import started"
}
```

### Health Check Endpoint

```
GET /api/health
```

Get system health information (admin only).

**Response:**
```json
{
  "status": "success",
  "data": {
    "version": "1.0.0",
    "uptime": "5d 12h 37m",
    "database": {
      "status": "connected",
      "size": "42MB",
      "migrations": "up-to-date"
    },
    "storage": {
      "available": "1.2GB",
      "used": "345MB"
    },
    "services": {
      "spotify": "connected",
      "dropbox": "connected",
      "email": "connected"
    }
  }
}
```

## Webhook Notifications

Quizzical Beats can send webhook notifications for certain events.

### Configuring Webhooks

Webhooks are configured in the admin settings:

1. Go to Admin > System > Webhooks
2. Add a new webhook URL
3. Select which events to receive notifications for

### Webhook Events

- `round.created`: A new round was created
- `round.exported`: A round was exported
- `import.completed`: A Spotify import was completed
- `backup.completed`: A system backup was completed

### Webhook Payload

```json
{
  "event": "round.exported",
  "timestamp": "2025-05-11T10:30:45Z",
  "data": {
    "round_id": 789,
    "round_name": "80s Rock Classics",
    "user_id": 123,
    "username": "john_doe",
    "export_format": "zip",
    "destination": "dropbox"
  }
}
```

## API Versioning

The current API version is v1. The version is specified in the URL path:

```
/api/v1/resource
```

For backward compatibility, requests to `/api/resource` will be directed to the latest stable API version.