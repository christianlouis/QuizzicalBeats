# Importing Songs

This guide explains the various methods for importing songs into Quizzical Beats to build your music quiz library.

## Music Service Integrations

Quizzical Beats supports importing songs from popular streaming services:

### Spotify Integration

#### Connecting Your Spotify Account

1. For full functionality, you'll need to connect your Spotify account
2. Login to Quizzical Beats and authorize the Spotify connection
3. Once connected, you can access and import songs from Spotify

#### Importing from Spotify

There are several ways to import songs from Spotify:

1. **Import Official Playlists**:
   - Navigate to Import > Official Playlists
   - Browse playlists from official Spotify accounts
   - Filter by keywords if needed
   - Click "Import" on the playlist you want to add

2. **Import Your Playlists**:
   - Navigate to Import > From Playlist
   - Enter a Spotify playlist URL or ID
   - Click "Import Playlist"
   - The songs will be added to your library

3. **Import Individual Albums or Tracks**:
   - Navigate to Import > Album or Import > Song
   - Enter the Spotify URL or ID of the album/track
   - Click "Import" to add the songs to your library

### Deezer Integration

Quizzical Beats also supports importing songs from Deezer:

1. **Import Deezer Playlists**:
   - Navigate to Import > From Playlist
   - Select "Deezer" as the platform
   - Enter a Deezer playlist URL or ID
   - Click "Import Playlist"

2. **Import Deezer Albums or Tracks**:
   - Navigate to Import > From Deezer
   - Choose to import an album or track
   - Enter the Deezer URL or ID
   - Click "Import" to add to your library

## Creating Rounds from Imported Songs

You can create rounds directly from imported playlists:

1. Navigate to Import > From Playlist
2. Enter the playlist URL and select the platform (Spotify or Deezer)
3. Optionally provide a name for your round
4. Click "Import Playlist"
5. Review the generated round
6. Click "Save This Quiz" to create the round

## Viewing Imported Songs

After importing songs:

1. Go to the Songs page to see your newly imported music
2. The songs will be displayed with available metadata including:
   - Title and artist
   - Album and year
   - Genre (when available)
   - Preview URLs

## Troubleshooting Import Issues

**Missing Audio Previews**: Some tracks may not have preview URLs available. In this case:
- Try importing from a different source (Spotify vs. Deezer)
- Look for an alternative version of the song
- Some songs may not have preview URLs available from any source

**Duplicate Songs**: The system will automatically detect duplicates based on:
- Spotify/Deezer IDs
- ISRC codes when available

**Limited Imports**: For performance reasons, when creating rounds from playlists:
- Only a limited number of songs (typically 8-10) will be included in a round
- All songs are saved to your library for future use