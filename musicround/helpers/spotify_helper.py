"""
Spotify token management helper functions
Provides centralized token refresh functionality similar to Dropbox helper
"""
import requests
import time
from datetime import datetime, timedelta
from flask import current_app
from flask_login import current_user
from musicround.models import db, SystemSetting


def refresh_spotify_token(refresh_token):
    """Refresh an expired Spotify access token"""
    client_id = current_app.config.get('SPOTIFY_CLIENT_ID')
    client_secret = current_app.config.get('SPOTIFY_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        current_app.logger.error("Spotify client credentials not configured")
        return None
    
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret
    }
    
    response = requests.post('https://accounts.spotify.com/api/token', data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        current_app.logger.error(f"Error refreshing Spotify token: {response.text}")
        return None


def get_current_user_spotify_token():
    """Get a valid Spotify access token for the current user, refreshing if needed"""
    if not current_user or not current_user.is_authenticated:
        current_app.logger.error("No authenticated user")
        return None
    
    # Check if token exists and is valid
    if (current_user.spotify_token and 
        current_user.spotify_token_expiry and 
        current_user.spotify_token_expiry > datetime.now() + timedelta(minutes=5)):
        # Token is valid and not about to expire
        current_app.logger.debug(f"Using valid Spotify token for user {current_user.id}")
        return current_user.spotify_token
    
    # Token is missing or about to expire - try to refresh
    if current_user.spotify_refresh_token:
        current_app.logger.info(f"Refreshing Spotify token for user {current_user.id}")
        
        # Try to refresh the token
        token_info = refresh_spotify_token(current_user.spotify_refresh_token)
        
        if token_info and 'access_token' in token_info:
            # Update token in database
            current_user.spotify_token = token_info['access_token']
            expires_in = token_info.get('expires_in', 3600)  # Default to 1 hour if not specified
            current_user.spotify_token_expiry = datetime.now() + timedelta(seconds=expires_in)
            
            # Update refresh token if a new one was provided
            if 'refresh_token' in token_info:
                current_user.spotify_refresh_token = token_info['refresh_token']
            
            db.session.commit()
            current_app.logger.info(f"Successfully refreshed Spotify token for user {current_user.id}")
            
            return current_user.spotify_token
    
    # If we get here, we couldn't refresh the user's token
    current_app.logger.error(f"Failed to get valid Spotify token for user {current_user.id}")
    return None


def get_system_spotify_token():
    """Get a valid Spotify access token from system refresh token, refreshing if needed"""
    system_refresh_token = SystemSetting.get('fallback_spotify_refresh_token', '')
    
    if not system_refresh_token:
        current_app.logger.debug("No system Spotify refresh token available")
        return None
    
    # Check if we have a cached system token that's still valid
    system_token = SystemSetting.get('system_spotify_token', '')
    system_token_expiry_str = SystemSetting.get('system_spotify_token_expiry', '')
    
    if system_token and system_token_expiry_str:
        try:
            system_token_expiry = datetime.fromisoformat(system_token_expiry_str)
            if system_token_expiry > datetime.now() + timedelta(minutes=5):
                current_app.logger.debug("Using valid cached system Spotify token")
                return system_token
        except ValueError:
            current_app.logger.warning("Invalid system token expiry format")
    
    # Token is missing or about to expire - try to refresh
    current_app.logger.info("Refreshing system Spotify token")
    
    token_info = refresh_spotify_token(system_refresh_token)
    
    if token_info and 'access_token' in token_info:
        # Cache the new token
        new_token = token_info['access_token']
        expires_in = token_info.get('expires_in', 3600)  # Default to 1 hour if not specified
        expiry = datetime.now() + timedelta(seconds=expires_in)
        
        SystemSetting.set('system_spotify_token', new_token)
        SystemSetting.set('system_spotify_token_expiry', expiry.isoformat())
        
        # Update refresh token if a new one was provided
        if 'refresh_token' in token_info:
            SystemSetting.set('fallback_spotify_refresh_token', token_info['refresh_token'])
        
        current_app.logger.info("Successfully refreshed system Spotify token")
        return new_token
    
    # If we get here, we couldn't refresh the system token
    current_app.logger.error("Failed to get valid system Spotify token")
    return None


def get_spotify_token():
    """
    Get the best available Spotify token with automatic refresh
    Priority: User token -> System token -> None
    """
    # Try user token first
    user_token = get_current_user_spotify_token()
    if user_token:
        return user_token, 'user'
    
    # Fall back to system token
    system_token = get_system_spotify_token()
    if system_token:
        return system_token, 'system'
    
    # No valid tokens available
    current_app.logger.warning("No valid Spotify tokens available")
    return None, 'none'


def refresh_spotify_token_if_needed(token, refresh_token, token_expiry):
    """
    Check if a token needs refresh and refresh it if necessary
    Returns: (new_token, new_refresh_token, new_expiry) or (None, None, None) if failed
    """
    # Check if token is still valid
    if token and token_expiry and token_expiry > datetime.now() + timedelta(minutes=5):
        return token, refresh_token, token_expiry
    
    # Token needs refresh
    if not refresh_token:
        current_app.logger.error("Token expired but no refresh token available")
        return None, None, None
    
    token_info = refresh_spotify_token(refresh_token)
    
    if token_info and 'access_token' in token_info:
        new_token = token_info['access_token']
        expires_in = token_info.get('expires_in', 3600)
        new_expiry = datetime.now() + timedelta(seconds=expires_in)
        new_refresh_token = token_info.get('refresh_token', refresh_token)
        
        return new_token, new_refresh_token, new_expiry
    
    return None, None, None


def get_spotify_user_info(access_token):
    """Get Spotify user info using an access token"""
    if not access_token:
        return None
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.get('https://api.spotify.com/v1/me', headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Error getting Spotify user info: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        current_app.logger.error(f"Exception getting Spotify user info: {str(e)}")
        return None
