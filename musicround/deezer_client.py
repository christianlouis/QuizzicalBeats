import os
import requests
import logging
import random
import time
from flask import current_app
from musicround.models import Song, db

logger = logging.getLogger(__name__)

class DeezerClient:
    """
    Client for interacting with the Deezer API
    Handles searching and importing songs, albums, and playlists
    """
    
    def __init__(self):
        self.base_url = "https://api.deezer.com"
        self.logger = logging.getLogger(__name__)
    
    def _make_request(self, endpoint, params=None):
        """Make a GET request to the Deezer API"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"Deezer API request error: {e}")
            return None
    
    def search_tracks(self, query, limit=50):
        """Search for tracks on Deezer"""
        params = {
            'q': query,
            'limit': limit
        }
        result = self._make_request('search/track', params=params)
        if result and 'data' in result:
            return result['data']
        return []
    
    def search_albums(self, query, limit=25):
        """Search for albums on Deezer"""
        params = {
            'q': query,
            'limit': limit
        }
        result = self._make_request('search/album', params=params)
        if result and 'data' in result:
            return result['data']
        return []
    
    def search_playlists(self, query, limit=25):
        """Search for playlists on Deezer"""
        params = {
            'q': query,
            'limit': limit
        }
        result = self._make_request('search/playlist', params=params)
        if result and 'data' in result:
            return result['data']
        return []
    
    def get_track(self, track_id):
        """Get details for a specific track"""
        return self._make_request(f'track/{track_id}')
    
    def get_album(self, album_id):
        """Get details for a specific album"""
        return self._make_request(f'album/{album_id}')
    
    def get_album_tracks(self, album_id):
        """Get tracks from a specific album"""
        result = self._make_request(f'album/{album_id}/tracks')
        if result and 'data' in result:
            return result['data']
        return []
    
    def get_playlist(self, playlist_id):
        """Get details for a specific playlist"""
        return self._make_request(f'playlist/{playlist_id}')
    
    def get_playlist_tracks(self, playlist_id):
        """Get tracks from a specific playlist"""
        result = self._make_request(f'playlist/{playlist_id}/tracks')
        if result and 'data' in result:
            return result['data']
        return []
    
    def get_popular_playlists(self, limit=30):
        """
        Get popular playlists from Deezer
        This uses a set of predetermined searches to find popular playlists
        """
        playlists = []
        search_terms = ['hits', 'top', 'chart', 'popular', 'best', 'essential']
        
        # Search for each term and combine results
        for term in search_terms:
            results = self.search_playlists(term, limit=10)
            playlists.extend(results)
            
            # Avoid rate limiting
            time.sleep(0.1)
        
        # Filter for playlists with reasonable track counts (avoid tiny playlists)
        playlists = [p for p in playlists if p.get('nb_tracks', 0) >= 10]
        
        # Sort by popularity or track count
        playlists.sort(key=lambda x: x.get('nb_tracks', 0), reverse=True)
        
        # Shuffle and limit results
        random.shuffle(playlists)
        return playlists[:limit]
    
    def get_genre_from_lastfm(self, artist_name, track_name, lastfm_api_key):
        """
        Fetch genre from Last.fm API
        Returns the genre string, or empty string if not found
        """
        if not lastfm_api_key:
            return ""
            
        url = 'http://ws.audioscrobbler.com/2.0/'
        params = {
            'method': 'track.getInfo',
            'api_key': lastfm_api_key,
            'artist': artist_name,
            'track': track_name,
            'format': 'json'
        }
        
        try:
            response = requests.get(url=url, params=params).json()
            
            # If present, use the first top-level tag as "genre"
            if ('track' in response and 
                'toptags' in response['track'] and 
                'tag' in response['track']['toptags'] and 
                response['track']['toptags']['tag']):
                return response['track']['toptags']['tag'][0]['name']
            return ""
        except Exception as e:
            self.logger.error(f"Last.fm API error: {e}")
            return ""
    
    def import_track(self, track_id, lastfm_api_key=None):
        """
        Import a track from Deezer into the database
        Returns the Song object if successful, None otherwise
        """
        track_info = self.get_track(track_id)
        
        if not track_info:
            self.logger.error(f"Could not fetch track with ID {track_id}")
            return None
            
        # Check if the track has a preview URL (required for our application)
        preview_url = track_info.get('preview')
        if not preview_url:
            self.logger.warning(f"Track {track_info.get('title')} has no preview URL")
            return None
            
        # Check if this track is already in our database
        existing_song = Song.query.filter_by(deezer_id=str(track_info['id'])).first()
        if existing_song:
            self.logger.info(f"Track {track_info.get('title')} already exists in database")
            return existing_song
            
        # Get additional artist details if needed
        artist_name = track_info.get('artist', {}).get('name', '')
        
        # Get album release year
        album_id = track_info.get('album', {}).get('id')
        release_year = ''
        cover_url = ''
        
        if album_id:
            album_info = self.get_album(album_id)
            if album_info:
                release_date = album_info.get('release_date', '')
                release_year = release_date[:4] if release_date else ''
                # Get highest quality cover image
                cover_url = album_info.get('cover_xl') or album_info.get('cover_big') or album_info.get('cover_medium', '')
        
        # Get genre from Last.fm
        genre = self.get_genre_from_lastfm(artist_name, track_info.get('title', ''), lastfm_api_key)
        
        # Create new Song object
        new_song = Song(
            deezer_id=str(track_info['id']),
            spotify_id=None,  # We don't have Spotify ID for Deezer tracks
            title=track_info.get('title', ''),
            artist=artist_name,
            genre=genre,
            year=release_year,
            preview_url=preview_url,
            cover_url=cover_url,
            popularity=track_info.get('rank', 0),
            used_count=0
        )
        
        try:
            db.session.add(new_song)
            db.session.commit()
            self.logger.info(f"Imported track '{new_song.title}' by {new_song.artist}")
            return new_song
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error saving track to database: {e}")
            return None
    
    def import_album(self, album_id, lastfm_api_key=None):
        """
        Import all tracks from an album
        Returns a list of successfully imported Song objects
        """
        tracks = self.get_album_tracks(album_id)
        imported_songs = []
        
        for track in tracks:
            track_id = track.get('id')
            if track_id:
                song = self.import_track(track_id, lastfm_api_key)
                if song:
                    imported_songs.append(song)
                    
                # Add a small delay to avoid overwhelming the API
                time.sleep(0.2)
        
        return imported_songs
    
    def import_playlist(self, playlist_id, lastfm_api_key=None):
        """
        Import all tracks from a playlist
        Returns a list of successfully imported Song objects
        """
        tracks = self.get_playlist_tracks(playlist_id)
        imported_songs = []
        
        for track in tracks:
            track_id = track.get('id')
            if track_id:
                song = self.import_track(track_id, lastfm_api_key)
                if song:
                    imported_songs.append(song)
                    
                # Add a small delay to avoid overwhelming the API
                time.sleep(0.2)
        
        return imported_songs