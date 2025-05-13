"""
Direct Spotify Web API client implementation.
This is an alternative to spotipy for testing and comparison purposes.
"""
import json
import os
import time
import requests
import logging
from flask import current_app

class SpotifyDirectClient:
    """
    A client for the Spotify Web API that directly uses the HTTP endpoints
    rather than using the spotipy library.
    """
    def __init__(self, client_id=None, client_secret=None, cache_path=None, bearer_token=None):
        self.client_id = client_id or current_app.config['SPOTIFY_CLIENT_ID']
        self.client_secret = client_secret or current_app.config['SPOTIFY_CLIENT_SECRET']
        self.cache_path = cache_path or os.path.join('/data', '.spotifycache')
        self.base_url = 'https://api.spotify.com/v1'
        self.token_url = 'https://accounts.spotify.com/api/token'
        self.access_token = bearer_token  # Use provided bearer token if available
        self.token_expiry = 0
        self.refresh_token = None
        self.logger = logging.getLogger(__name__)
        
        # Configure session with retry logic
        self.session = requests.Session()
        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry
        retries = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        
        # Only load tokens from cache if bearer token was not provided
        if not bearer_token:
            self._load_token_from_cache()
    
    def _load_token_from_cache(self):
        """Load access and refresh tokens from cache file"""
        if not os.path.exists(self.cache_path):
            self.logger.warning(f"Cache file not found at {self.cache_path}")
            return
            
        try:
            with open(self.cache_path, 'r') as f:
                token_info = json.load(f)
                self.access_token = token_info.get('access_token')
                self.refresh_token = token_info.get('refresh_token')
                self.token_expiry = token_info.get('expires_at', 0)
                self.logger.info("Loaded tokens from cache file")
        except Exception as e:
            self.logger.error(f"Error loading tokens from cache: {e}")
    
    def _save_token_to_cache(self, token_info):
        """Save token information to cache file"""
        try:
            with open(self.cache_path, 'w') as f:
                json.dump(token_info, f)
            self.logger.info("Saved tokens to cache file")
        except Exception as e:
            self.logger.error(f"Error saving tokens to cache: {e}")
    
    def _refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        if not self.refresh_token:
            self.logger.error("No refresh token available. User must log in again.")
            return False
            
        self.logger.info("Refreshing access token...")
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        try:
            response = self.session.post(self.token_url, data=data)
            response.raise_for_status()
            
            token_info = response.json()
            self.access_token = token_info['access_token']
            self.token_expiry = int(time.time()) + token_info['expires_in']
            
            # If new refresh token provided, update it
            if 'refresh_token' in token_info:
                self.refresh_token = token_info['refresh_token']
                
            # Update cache
            token_info['expires_at'] = self.token_expiry
            if 'refresh_token' not in token_info and self.refresh_token:
                token_info['refresh_token'] = self.refresh_token
                
            self._save_token_to_cache(token_info)
            return True
            
        except Exception as e:
            self.logger.error(f"Error refreshing access token: {e}")
            return False
    
    def _ensure_token_valid(self):
        """Check if token is valid and refresh if needed"""
        # If we're using a manually provided bearer token, assume it's valid
        if self.access_token and not self.refresh_token:
            return True
            
        # Otherwise use the normal refresh logic
        if not self.access_token or time.time() > self.token_expiry - 60:
            return self._refresh_access_token()
        return True
    
    def _make_api_request(self, endpoint, method='GET', params=None, data=None, retry_on_auth_error=True):
        """Make a request to the Spotify API with automatic token refresh"""
        if not self._ensure_token_valid():
            return None
            
        url = f"{self.base_url}/{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers, params=params)
            elif method == 'POST':
                response = self.session.post(url, headers=headers, json=data, params=params)
            elif method == 'PUT':
                response = self.session.put(url, headers=headers, json=data, params=params)
            elif method == 'DELETE':
                response = self.session.delete(url, headers=headers, params=params)
            else:
                self.logger.error(f"Unsupported HTTP method: {method}")
                return None
                
            # Handle 401 by refreshing token and retrying once
            if response.status_code == 401 and retry_on_auth_error:
                self.logger.info("Got 401, refreshing token and retrying...")
                if self._refresh_access_token():
                    return self._make_api_request(endpoint, method, params, data, retry_on_auth_error=False)
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error: {e}")
            # Log the response content for debugging
            if hasattr(e, 'response') and e.response:
                self.logger.error(f"Response status: {e.response.status_code}")
                self.logger.error(f"Response content: {e.response.text}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error making API request: {e}")
            return None
    
    def user_playlists(self, user_id, limit=50, offset=0):
        """
        Get a user's playlists. Mirrors the spotipy interface.
        
        Args:
            user_id: The Spotify user ID
            limit: Maximum number of playlists to return (max 50)
            offset: The index of the first playlist to return
            
        Returns:
            A dictionary containing the user's playlists or None if an error occurred
        """
        endpoint = f"users/{user_id}/playlists"
        params = {
            'limit': min(limit, 50),  # Spotify API has a max limit of 50
            'offset': offset
        }
        
        self.logger.info(f"Fetching {limit} playlists at offset {offset} for user {user_id}")
        result = self._make_api_request(endpoint, params=params)
        
        if result:
            self.logger.info(f"Got {len(result.get('items', []))} playlists, total {result.get('total', 0)}")
        else:
            self.logger.error("Failed to fetch playlists")
            
        return result
        
    def fetch_all_user_playlists(self, user_id, limit=50):
        """
        Fetch all playlists for a user with proper pagination.
        
        Args:
            user_id: The Spotify user ID
            limit: Maximum number of playlists per request (max 50)
            
        Returns:
            List of all playlists from the user
        """
        all_playlists = []
        offset = 0
        total = None
        max_loops = 50  # Safety limit
        loop_count = 0
        
        self.logger.info(f"Starting to fetch all playlists for user {user_id}")
        start_time = time.time()
        
        while loop_count < max_loops:
            loop_count += 1
            
            result = self.user_playlists(user_id, limit=limit, offset=offset)
            if not result:
                self.logger.error(f"Failed to fetch playlists for user {user_id} at offset {offset}")
                break
                
            # Get total on first request
            if total is None:
                total = result.get('total', 0)
                self.logger.info(f"User has {total} total playlists according to API")
                
            # Process items from this batch
            items = result.get('items', [])
            item_count = len(items)
            all_playlists.extend(items)
            
            self.logger.info(f"Fetched {item_count} playlists for user {user_id}, progress: {len(all_playlists)}/{total}")
            
            # Break if we got fewer items than requested (last page)
            if item_count < limit:
                self.logger.info(f"Received fewer items than requested, assuming end of list")
                break
                
            # Update offset for next batch
            offset += item_count
            
            # Break if we've fetched all playlists
            if offset >= total:
                self.logger.info(f"Reached total {total} playlists")
                break
                
            # Break if next URL is None (no more pages)
            if not result.get('next'):
                self.logger.info(f"No 'next' URL in response, end of pagination")
                # Check for inconsistency
                if offset < total:
                    self.logger.warning(f"API inconsistency: no more pages but only fetched {len(all_playlists)}/{total}")
                break
        
        duration_ms = int((time.time() - start_time) * 1000)
        self.logger.info(f"Completed fetching {len(all_playlists)}/{total} playlists in {duration_ms}ms")
        
        return all_playlists

    def get_track_audio_features(self, track_id):
        """
        Get audio features for a specific track
        
        Args:
            track_id: Spotify ID of the track
            
        Returns:
            dict: Audio features for the track or None if not found
        """
        self.logger.info(f"Getting audio features for track {track_id}")
        if not self._ensure_token_valid():
            return None
            
        endpoint = f"audio-features/{track_id}"
        return self._make_api_request(endpoint)
        
    def get_tracks_audio_features(self, track_ids):
        """
        Get audio features for multiple tracks in a single request
        
        Args:
            track_ids: List of Spotify track IDs (max 100)
            
        Returns:
            list: List of audio features for tracks
        """
        if not track_ids:
            return []
            
        self.logger.info(f"Getting audio features for {len(track_ids)} tracks")
        if not self._ensure_token_valid():
            return None
            
        # Spotify API only accepts up to 100 IDs per request
        if len(track_ids) > 100:
            self.logger.warning("More than 100 track IDs provided, only fetching the first 100")
            track_ids = track_ids[:100]
            
        # Convert list to comma-separated string
        ids_param = ",".join(track_ids)
        
        endpoint = "audio-features"
        result = self._make_api_request(endpoint, params={"ids": ids_param})
        
        if result and "audio_features" in result:
            return result["audio_features"]
        return []