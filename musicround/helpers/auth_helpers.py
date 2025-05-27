"""
Authentication helper functions for OAuth providers
"""
import os
from flask import current_app, url_for, session, flash, redirect, request
from authlib.integrations.flask_client import OAuth
from functools import wraps
from datetime import datetime, timedelta
import requests

# Initialize OAuth object
oauth = OAuth()

def init_oauth(app):
    """
    Initialize OAuth with the Flask app and register providers
    """
    oauth.init_app(app)
    
    # Register Google OAuth client
    if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
        oauth.register(
            name='google',
            client_id=app.config.get('GOOGLE_CLIENT_ID'),
            client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        app.logger.info("Google OAuth client registered")
    else:
        app.logger.warning("Google OAuth client not registered - missing client ID or secret")

    # Register Authentik OAuth client
    if app.config.get('AUTHENTIK_CLIENT_ID') and app.config.get('AUTHENTIK_CLIENT_SECRET'):
        oauth.register(
            name='authentik',
            client_id=app.config.get('AUTHENTIK_CLIENT_ID'),
            client_secret=app.config.get('AUTHENTIK_CLIENT_SECRET'),
            server_metadata_url=app.config.get('AUTHENTIK_METADATA_URL'),
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        app.logger.info("Authentik OAuth client registered")
    else:
        app.logger.warning("Authentik OAuth client not registered - missing client ID or secret")
        
    # Register Dropbox OAuth client
    if app.config.get('DROPBOX_APP_KEY') and app.config.get('DROPBOX_APP_SECRET'):
        oauth.register(
            name='dropbox',
            client_id=app.config.get('DROPBOX_APP_KEY'),
            client_secret=app.config.get('DROPBOX_APP_SECRET'),
            authorize_url='https://www.dropbox.com/oauth2/authorize',
            authorize_params=None,
            access_token_url='https://api.dropboxapi.com/oauth2/token',
            access_token_params=None,
            refresh_token_url='https://api.dropboxapi.com/oauth2/token',
            client_kwargs={
                'scope': 'files.content.write account_info.read'
            }
        )
        app.logger.info("Dropbox OAuth client registered")
    else:
        app.logger.warning("Dropbox OAuth client not registered - missing app key or secret")
      # Register Spotify OAuth client
    if app.config.get('SPOTIFY_CLIENT_ID') and app.config.get('SPOTIFY_CLIENT_SECRET'):
        oauth.register(
            name='spotify',
            client_id=app.config.get('SPOTIFY_CLIENT_ID'),
            client_secret=app.config.get('SPOTIFY_CLIENT_SECRET'),
            api_base_url='https://api.spotify.com/v1/',
            authorize_url='https://accounts.spotify.com/authorize',
            authorize_params={'show_dialog': 'true'}, # Force re-approval
            access_token_url='https://accounts.spotify.com/api/token',
            access_token_params=None,
            refresh_token_url='https://accounts.spotify.com/api/token',
            client_kwargs={
                'scope': app.config.get('SPOTIFY_SCOPE')
            },
            userinfo_endpoint='https://api.spotify.com/v1/me' # Added for fetching user info
        )
        app.logger.info("Spotify OAuth client registered")
    else:
        app.logger.warning("Spotify OAuth client not registered - missing client ID or secret")
    
    return oauth

def get_google_user_info(token):
    """
    Get Google user info from the token
    """
    try:
        resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        profile = resp.json()
        
        # Create a standardized user info dictionary
        user_info = {
            'id': profile.get('sub'),  # Google uses 'sub' as the unique identifier
            'email': profile.get('email'),
            'name': profile.get('name'),
            'given_name': profile.get('given_name'),
            'family_name': profile.get('family_name'),
            'picture': profile.get('picture')
        }
        
        # Add 'sub' field explicitly for backwards compatibility
        if profile.get('sub'):
            user_info['sub'] = profile.get('sub')
            
        return user_info
    except Exception as e:
        current_app.logger.error(f"Error getting Google user info: {str(e)}")
        return None

def get_authentik_user_info(token):
    """
    Get Authentik user info from the token
    """
    try:
        resp = oauth.authentik.get('userinfo')
        profile = resp.json()
        return {
            'id': profile.get('sub'),
            'email': profile.get('email'),
            'name': profile.get('name'),
            'given_name': profile.get('given_name', ''),
            'family_name': profile.get('family_name', ''),
            'picture': profile.get('picture', '')
        }
    except Exception as e:
        current_app.logger.error(f"Error getting Authentik user info: {str(e)}")
        return None

def get_dropbox_user_info(token):
    """
    Get Dropbox user info from the token
    """
    try:
        # Add debug logging for token
        current_app.logger.debug(f"Retrieving Dropbox user info with token: {token}")
        
        # Make sure we have an access token
        access_token = token.get("access_token")
        if not access_token:
            # Try direct token string if token is not a dict
            if isinstance(token, str):
                access_token = token
            else:
                current_app.logger.error("No access token found in token object")
                return None
                
        # Set proper headers for Dropbox API - no Content-Type for null body
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        # The Dropbox API for get_current_account actually expects a null body with no Content-Type header
        response = requests.post(
            'https://api.dropboxapi.com/2/users/get_current_account',
            headers=headers,
            data=None  # Send null body
        )
        
        # Check for successful response
        if response.status_code != 200:
            current_app.logger.error(f"Dropbox API error: {response.status_code} - {response.text}")
            return None
            
        # Parse response
        profile = response.json()
        current_app.logger.debug(f"Dropbox user info response: {profile}")
        
        # Create a standardized user info dictionary
        user_info = {
            'id': profile.get('account_id', ''),
            'email': profile.get('email', ''),
            'name': profile.get('name', {}).get('display_name', ''),
            'given_name': profile.get('name', {}).get('given_name', ''),
            'family_name': profile.get('name', {}).get('surname', ''),
            'picture': profile.get('profile_photo_url', '')
        }
        
        return user_info
    except Exception as e:
        current_app.logger.error(f"Error getting Dropbox user info: {str(e)}")
        return None

def get_spotify_user_info(token):
    """
    Get Spotify user info from the token
    """
    try:
        # Authlib should handle token refresh automatically if configured correctly
        # and if the token object is managed by Authlib's token session or similar mechanism.
        
        # Use the registered Authlib client to fetch user info
        # The 'userinfo_endpoint' configured during registration will be used.
        # We pass the token explicitly to ensure it's used for this request.
        # Authlib's `oauth.spotify.get()` will prepend the base URL if 'userinfo_endpoint' is relative,
        # but since we provided an absolute one, it should use that.
        # The error "Invalid URL 'me'" suggests that 'me' alone was passed somewhere.
        # Let's ensure we are calling the fully qualified endpoint via the client.
        resp = oauth.spotify.get('https://api.spotify.com/v1/me', token=token)
        resp.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        profile = resp.json()
        current_app.logger.debug(f"Spotify user info response: {profile}")

        user_info = {
            'id': profile.get('id'),
            'email': profile.get('email'), # Note: Spotify email might be private
            'name': profile.get('display_name'),
            'picture': profile.get('images')[0]['url'] if profile.get('images') else None,
            # Spotify doesn't provide given_name and family_name directly
            'given_name': profile.get('display_name', '').split(' ')[0] if profile.get('display_name') else '',
            'family_name': ' '.join(profile.get('display_name', '').split(' ')[1:]) if profile.get('display_name') and ' ' in profile.get('display_name') else ''
        }
        return user_info
    except requests.exceptions.HTTPError as http_err:
        current_app.logger.error(f"HTTP error getting Spotify user info: {http_err} - Response: {http_err.response.text}")
        return None
    except Exception as e:
        current_app.logger.error(f"Error getting Spotify user info: {str(e)}")
        return None

def find_or_create_user(user_info, auth_provider):
    """
    Find existing user or create a new one based on OAuth user info
    """
    from musicround.models import db, User
    if not user_info:
        return None
        
    # First try to find user by provider-specific ID
    if auth_provider == 'google':
        user = User.query.filter_by(google_id=user_info['id']).first()
    elif auth_provider == 'authentik':
        user = User.query.filter_by(authentik_id=user_info['id']).first()
    elif auth_provider == 'dropbox':
        user = User.query.filter_by(dropbox_id=user_info['id']).first()
    elif auth_provider == 'spotify':
        user = User.query.filter_by(spotify_id=user_info['id']).first()
    else:
        return None
        
    # If not found by provider ID, try email
    if user is None and user_info.get('email'):
        user = User.query.filter_by(email=user_info['email']).first()
        
        # If user exists but doesn't have provider ID, update it
        if user:
            if auth_provider == 'google':
                user.google_id = user_info['id']
            elif auth_provider == 'authentik':
                user.authentik_id = user_info['id']
            elif auth_provider == 'dropbox':
                user.dropbox_id = user_info['id']
            elif auth_provider == 'spotify':
                user.spotify_id = user_info['id']
                
            db.session.commit()
            current_app.logger.info(f"Updated existing user {user.username} with {auth_provider} ID")
    
    # If user still not found, check if new signups are allowed before creating
    if user is None:
        # Check system setting if new signups are allowed
        from musicround.models import SystemSetting
        allow_signups = SystemSetting.get('allow_signups', 'true') == 'true'
        
        if not allow_signups:
            current_app.logger.warning(f"OAuth signup attempted for {auth_provider} but new signups are disabled")
            return None
            
        # Generate a username from email
        email = user_info.get('email', '')
        base_username = email.split('@')[0] if email else f"{auth_provider}_{user_info['id']}"
        
        # Ensure username is unique
        username = base_username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}_{counter}"
            counter += 1
            
        # Create new user
        user = User(
            username=username,
            email=user_info.get('email', ''),
            first_name=user_info.get('given_name', ''),
            last_name=user_info.get('family_name', ''),
            auth_provider=auth_provider,
            created_at=datetime.now(),
            last_login=datetime.now()
        )
        
        # Set provider-specific fields
        if auth_provider == 'google':
            user.google_id = user_info['id']
        elif auth_provider == 'authentik':
            user.authentik_id = user_info['id']
        elif auth_provider == 'dropbox':
            user.dropbox_id = user_info['id']
        elif auth_provider == 'spotify':
            user.spotify_id = user_info['id']
            
        db.session.add(user)
        try:
            db.session.commit()
            current_app.logger.info(f"Created new user {username} with {auth_provider} auth")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating user: {str(e)}")
            return None
    
    return user

def update_oauth_tokens(user, tokens, auth_provider):
    """
    Update user's OAuth tokens
    """
    from musicround.models import db
    if auth_provider == 'google':
        user.google_token = tokens.get('access_token')
        user.google_refresh_token = tokens.get('refresh_token')
    elif auth_provider == 'authentik':
        user.authentik_token = tokens.get('access_token')
        user.authentik_refresh_token = tokens.get('refresh_token')
    elif auth_provider == 'dropbox':
        user.dropbox_token = tokens.get('access_token')
        user.dropbox_refresh_token = tokens.get('refresh_token')
        if tokens.get('expires_in'):
            user.dropbox_token_expiry = datetime.now() + timedelta(seconds=int(tokens.get('expires_in')))
    elif auth_provider == 'spotify':
        user.spotify_token = tokens.get('access_token')
        user.spotify_refresh_token = tokens.get('refresh_token')
        if tokens.get('expires_in'):
            user.spotify_token_expiry = datetime.now() + timedelta(seconds=int(tokens.get('expires_in')))
    user.last_login = datetime.now()
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating {auth_provider} tokens: {str(e)}")
        return False