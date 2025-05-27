import os
import requests
import logging
import random
import time
from flask import current_app
from musicround.models import Song, db
from musicround.helpers.metadata import get_song_metadata_by_isrc

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
        Returns a tuple (Song object, was_new) where was_new indicates if this was a new import
        """
        track_info = self.get_track(track_id)
        
        if not track_info:
            self.logger.error(f"Could not fetch track with ID {track_id}")
            return None, False
            
        # Check if the track has a preview URL (required for our application)
        preview_url = track_info.get('preview')
        if not preview_url:
            self.logger.warning(f"Track {track_info.get('title')} has no preview URL")
            return None, False

        # Extract ISRC
        isrc = track_info.get('isrc')
            
        # Check if this track is already in our database by Deezer ID or ISRC
        existing_song = None
        if isrc:
            existing_song = Song.query.filter_by(isrc=isrc).first()
        if not existing_song:
            existing_song = Song.query.filter_by(deezer_id=str(track_info['id'])).first()
        
        if existing_song:
            self.logger.info(f"Track {track_info.get('title')} (Deezer ID: {track_info['id']}, ISRC: {isrc}) already exists in database with ID {existing_song.id}")
            # If ISRC was missing and we found it now, update the existing record
            if isrc and not existing_song.isrc:
                existing_song.isrc = isrc
                if existing_song.deezer_id is None: # If it was matched by ISRC but didn't have deezer_id
                    existing_song.deezer_id = str(track_info['id'])
                try:
                    db.session.commit()
                    self.logger.info(f"Updated ISRC for existing song {existing_song.id} to {isrc}")
                except Exception as e:
                    db.session.rollback()
                    self.logger.error(f"Error updating ISRC for existing song {existing_song.id}: {e}")
            
            # Optionally, trigger metadata refresh if ISRC is now available or if desired
            if existing_song.isrc:
                try:
                    app_context = current_app._get_current_object()
                    updated_metadata = get_song_metadata_by_isrc(existing_song.isrc, app=app_context)
                    if updated_metadata:
                        # Update song fields from aggregated metadata
                        existing_song.title = updated_metadata.get('title', existing_song.title)
                        existing_song.artist = updated_metadata.get('artist_name', existing_song.artist)
                        existing_song.year = updated_metadata.get('year', existing_song.year)
                        existing_song.genre = updated_metadata.get('genre', existing_song.genre)
                        # ... update other relevant fields ...
                        if updated_metadata.get('spotify_id') and not existing_song.spotify_id:
                            existing_song.spotify_id = updated_metadata.get('spotify_id')
                        if updated_metadata.get('cover_url') and not existing_song.cover_url: # Prioritize existing cover if any
                             existing_song.cover_url = updated_metadata.get('cover_url')
                        if updated_metadata.get('preview_url') and not existing_song.preview_url: # Prioritize existing preview if any
                             existing_song.preview_url = updated_metadata.get('preview_url')

                        db.session.commit()
                        self.logger.info(f"Refreshed metadata for existing song {existing_song.id} using ISRC {existing_song.isrc}")
                except Exception as e:
                    db.session.rollback()
                    self.logger.error(f"Error refreshing metadata for existing song {existing_song.id}: {e}")
            return existing_song, False  # Return existing song with was_new=False
            
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
        
        # Get genre from Last.fm (can be removed if metadata aggregation handles it)
        # genre = self.get_genre_from_lastfm(artist_name, track_info.get('title', ''), lastfm_api_key)
        genre = None # Will be populated by metadata aggregation if ISRC is present
        
        # Create new Song object
        new_song = Song(
            deezer_id=str(track_info['id']),
            spotify_id=None,  # Will be populated by metadata aggregation if ISRC is present
            title=track_info.get('title', ''),
            artist=artist_name,
            genre=genre,
            year=release_year,
            preview_url=preview_url,
            cover_url=cover_url,
            popularity=track_info.get('rank', 0), # Deezer 'rank' can be used as popularity
            isrc=isrc, # Save the ISRC
            used_count=0
        )
        
        try:
            db.session.add(new_song)
            db.session.commit()
            self.logger.info(f"Imported track '{new_song.title}' by {new_song.artist} with Deezer ID {new_song.deezer_id} and ISRC {new_song.isrc}")

            # If ISRC is present, fetch and update with aggregated metadata
            if new_song.isrc:
                try:
                    app_context = current_app._get_current_object()
                    aggregated_metadata = get_song_metadata_by_isrc(new_song.isrc, app=app_context)
                    if aggregated_metadata:
                        new_song.title = aggregated_metadata.get('title', new_song.title)
                        new_song.artist = aggregated_metadata.get('artist_name', new_song.artist)
                        new_song.year = aggregated_metadata.get('year', new_song.year)
                        new_song.genre = aggregated_metadata.get('genre', new_song.genre)
                        new_song.spotify_id = aggregated_metadata.get('spotify_id', new_song.spotify_id)
                        # Update cover and preview URLs if they are better or missing
                        if aggregated_metadata.get('cover_url'):
                             new_song.cover_url = aggregated_metadata.get('cover_url')
                        if aggregated_metadata.get('preview_url'):
                             new_song.preview_url = aggregated_metadata.get('preview_url')                        # Potentially update popularity if a more universal score is available
                        # new_song.popularity = aggregated_metadata.get('popularity', new_song.popularity)
                        db.session.commit()
                        self.logger.info(f"Updated new song {new_song.id} with aggregated metadata using ISRC {new_song.isrc}")
                except Exception as e:
                    db.session.rollback()
                    self.logger.error(f"Error updating new song {new_song.id} with aggregated metadata: {e}")
            return new_song, True  # Return new song with was_new=True
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error saving track to database: {e}")
            return None, False
      def import_album(self, album_id, lastfm_api_key=None):
        """
        Import all tracks from an album
        Returns a dictionary with import statistics
        """
        tracks = self.get_album_tracks(album_id)
        imported_songs = []
        skipped_songs = []
        
        for track in tracks:
            track_id = track.get('id')
            if track_id:
                song, was_new = self.import_track(track_id, lastfm_api_key)
                if song:
                    if was_new:
                        imported_songs.append(song)
                    else:
                        skipped_songs.append(song)
                    
                # Add a small delay to avoid overwhelming the API
                time.sleep(0.2)
        
        return {
            'imported_songs': imported_songs,
            'skipped_songs': skipped_songs,
            'imported_count': len(imported_songs),
            'skipped_count': len(skipped_songs)
        }
      def import_playlist(self, playlist_id, lastfm_api_key=None):
        """
        Import all tracks from a playlist
        Returns a dictionary with import statistics
        """
        tracks = self.get_playlist_tracks(playlist_id)
        imported_songs = []
        skipped_songs = []
        
        for track in tracks:
            track_id = track.get('id')
            if track_id:
                song, was_new = self.import_track(track_id, lastfm_api_key)
                if song:
                    if was_new:
                        imported_songs.append(song)
                    else:
                        skipped_songs.append(song)
                    
                # Add a small delay to avoid overwhelming the API
                time.sleep(0.2)
        
        return {
            'imported_songs': imported_songs,
            'skipped_songs': skipped_songs,
            'imported_count': len(imported_songs),
            'skipped_count': len(skipped_songs)
        }