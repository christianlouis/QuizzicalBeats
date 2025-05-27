"""
Updated core.py with improved Spotify OAuth handling
"""
import logging
import datetime
from flask import current_app, redirect, url_for, flash, session
from flask_login import current_user
from musicround.helpers.spotify_debug import DebugSpotifyClient
from musicround.models import db

logger = logging.getLogger("spotify.token")

def ensure_valid_spotify_token(session, current_user):
    """
    Ensure a valid Spotify token is available and return a Spotify client
    
    Args:
        session: The Flask session object
        current_user: The current user object
    
    Returns:
        DebugSpotifyClient or None if no valid token
    """
    # Get token from session
    token = session.get('access_token')
    
    # If no token in session but user is logged in with a token
    if not token and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        if hasattr(current_user, 'spotify_token') and current_user.spotify_token:
            token = current_user.spotify_token
            session['access_token'] = token
    
    if not token:
        logger.warning("No Spotify token available")
        return None
    
    # Create Spotify client
    sp = DebugSpotifyClient(auth=token)
    
    # Verify token is valid
    try:
        # Try a simple API call
        sp.current_user()
        return sp
    except Exception as e:
        logger.warning(f"Spotify token validation failed: {str(e)}")
        
        # Try to refresh the token
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'spotify_refresh_token') and current_user.spotify_refresh_token:
            try:
                from spotipy.oauth2 import SpotifyOAuth
                from musicround.config import Config
                
                # Create OAuth object to refresh token
                sp_oauth = SpotifyOAuth(
                    client_id=Config.SPOTIFY_CLIENT_ID,
                    client_secret=Config.SPOTIFY_CLIENT_SECRET,
                    redirect_uri=Config.SPOTIFY_REDIRECT_URI,
                    scope=Config.SPOTIFY_SCOPE
                )
                
                # Get new token
                token_info = sp_oauth.refresh_access_token(current_user.spotify_refresh_token)
                
                # Update session and user
                session['access_token'] = token_info['access_token']
                current_user.spotify_token = token_info['access_token']
                if 'refresh_token' in token_info:
                    current_user.spotify_refresh_token = token_info['refresh_token']
                
                # Update token expiry
                current_user.spotify_token_expiry = datetime.datetime.now() + datetime.timedelta(seconds=token_info['expires_in'])
                
                # Save changes
                db.session.commit()
                
                # Create new Spotify client with updated token
                sp = DebugSpotifyClient(auth=token_info['access_token'])
                return sp
            except Exception as refresh_error:
                logger.error(f"Error refreshing token: {str(refresh_error)}")
    
    return None
