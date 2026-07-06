"""
Spotify token management helper functions
Provides centralized token refresh functionality similar to Dropbox helper
"""
import requests
import time
import json
from datetime import datetime, timedelta
from flask import current_app, flash, session
from flask_login import current_user
from musicround.models import db, SystemSetting

# How long a manually-supplied bearer token (see update_bearer_token) is
# trusted for. These tokens aren't obtained through this app's OAuth client
# (e.g. they may be extracted directly from a Spotify web session) so there
# is no refresh_token and no way to renew them automatically; treat them as
# valid for a normal Spotify access-token lifetime and require the user to
# resupply a fresh one afterwards.
MANUAL_BEARER_TOKEN_TTL_SECONDS = 3600
MANUAL_BEARER_TOKEN_SESSION_KEYS = (
    'access_token',
    'bearer_token_added',
    'token_source',
    'client_token_expiry',
)


class SpotifyTokenRevokedError(Exception):
    """Raised when Spotify reports invalid_grant for a refresh token.

    Spotify refresh tokens expire after six months as of 2026-07-20. Once that
    happens the refresh token is permanently invalid: it must be discarded
    and the user must go through the sign-in flow again, not be retried.
    See https://developer.spotify.com/blog (Developer Blog, 2026-06-18).
    """


def refresh_spotify_token(refresh_token):
    """Refresh an expired Spotify access token.

    Returns the token response dict on success, or None on a transient
    failure (network error, timeout, 5xx) that is safe to retry later.

    Raises:
        SpotifyTokenRevokedError: Spotify responded with invalid_grant,
            meaning the refresh token itself is no longer valid and must be
            discarded rather than retried.
    """
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

    try:
        response = requests.post('https://accounts.spotify.com/api/token', data=data, timeout=10)
    except requests.RequestException as e:
        current_app.logger.error(f"Network error refreshing Spotify token: {e}")
        return None

    if response.status_code == 200:
        return response.json()

    if response.status_code == 400:
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
        if error_body.get('error') == 'invalid_grant':
            raise SpotifyTokenRevokedError(
                error_body.get('error_description', 'Spotify refresh token is invalid or has expired')
            )

    current_app.logger.error(f"Error refreshing Spotify token: {response.status_code} {response.text}")
    return None


def _clear_user_spotify_tokens(user):
    """Discard a user's Spotify tokens after Spotify reports invalid_grant.

    spotify_id is intentionally kept so the linked-account identity survives;
    the user only needs to reconnect, not re-link from scratch.
    """
    user.spotify_token = None
    user.spotify_refresh_token = None
    user.spotify_token_expiry = None
    db.session.commit()
    current_app.logger.warning(
        f"Discarded revoked Spotify refresh token for user {user.id}; user must reconnect Spotify."
    )


def _clear_system_spotify_tokens():
    """Discard the system fallback Spotify tokens after Spotify reports invalid_grant."""
    SystemSetting.set('fallback_spotify_refresh_token', '')
    SystemSetting.set('system_spotify_token', '')
    SystemSetting.set('system_spotify_token_expiry', '')
    current_app.logger.error(
        "Discarded revoked system Spotify fallback refresh token. "
        "Re-authorize the service account via the admin Spotify token wizard."
    )


def _normalize_legacy_user_spotify_token(user):
    """Migrate legacy JSON Spotify tokens into the raw-token user columns."""
    raw_token = getattr(user, 'spotify_token', None)
    if not raw_token or not isinstance(raw_token, str) or not raw_token.strip().startswith('{'):
        return False

    try:
        token_payload = json.loads(raw_token)
    except (TypeError, ValueError):
        current_app.logger.warning("User %s has an unreadable legacy Spotify token payload.", user.id)
        return False

    access_token = token_payload.get('access_token')
    if not access_token:
        current_app.logger.warning("User %s has a legacy Spotify token payload without access_token.", user.id)
        return False

    user.spotify_token = access_token
    if token_payload.get('refresh_token') and not user.spotify_refresh_token:
        user.spotify_refresh_token = token_payload['refresh_token']

    expires_at = token_payload.get('expires_at')
    if expires_at and not user.spotify_token_expiry:
        try:
            user.spotify_token_expiry = datetime.fromtimestamp(int(float(expires_at)))
        except (TypeError, ValueError, OSError):
            current_app.logger.warning("User %s has an invalid legacy Spotify expires_at value.", user.id)
    return True


def clear_manual_spotify_bearer_token():
    """Remove all browser-session state for a manually supplied Spotify token."""
    for key in MANUAL_BEARER_TOKEN_SESSION_KEYS:
        session.pop(key, None)


def get_current_user_spotify_token():
    """Get a valid Spotify access token for the current user, refreshing if needed"""
    if not current_user or not current_user.is_authenticated:
        current_app.logger.error("No authenticated user")
        return None

    normalized_legacy_token = _normalize_legacy_user_spotify_token(current_user)
    if normalized_legacy_token:
        db.session.commit()
        current_app.logger.info("Normalized legacy Spotify token payload for user %s.", current_user.id)
    
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
        try:
            token_info = refresh_spotify_token(current_user.spotify_refresh_token)
        except SpotifyTokenRevokedError:
            _clear_user_spotify_tokens(current_user)
            flash("Your Spotify connection has expired. Please reconnect your Spotify account.", "warning")
            return None

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

    try:
        token_info = refresh_spotify_token(system_refresh_token)
    except SpotifyTokenRevokedError:
        _clear_system_spotify_tokens()
        return None

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


def get_manual_spotify_bearer_token():
    """Return a user-supplied Spotify bearer token from the session, if present and not expired.

    This lets a user temporarily use a token they obtained themselves (e.g.
    extracted from a Spotify web session) instead of this app's own OAuth
    tokens - useful when that token carries scopes/permissions an app-issued
    token can't get. Set via users.update_bearer_token; there is no refresh
    token for these, so they simply expire after MANUAL_BEARER_TOKEN_TTL_SECONDS.
    """
    token = session.get('access_token')
    if not token:
        return None

    added = session.get('bearer_token_added')
    if added is None:
        current_app.logger.info(
            "Manually supplied Spotify bearer token has no timestamp; ignoring it."
        )
        clear_manual_spotify_bearer_token()
        return None

    try:
        age_seconds = datetime.now().timestamp() - float(added)
    except (TypeError, ValueError):
        current_app.logger.info(
            "Manually supplied Spotify bearer token has invalid timestamp; ignoring it."
        )
        clear_manual_spotify_bearer_token()
        return None

    if age_seconds > MANUAL_BEARER_TOKEN_TTL_SECONDS:
        current_app.logger.info(
            "Manually supplied Spotify bearer token has expired; ignoring it."
        )
        clear_manual_spotify_bearer_token()
        return None

    return token


def get_spotify_token():
    """
    Get the best available Spotify token with automatic refresh.
    Priority: manually-supplied session token -> logged-in user's token -> system fallback token -> None
    """
    # A manually supplied token always wins: the user explicitly asked to use it.
    manual_token = get_manual_spotify_bearer_token()
    if manual_token:
        return manual_token, 'manual'

    # Try user token next
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

    try:
        token_info = refresh_spotify_token(refresh_token)
    except SpotifyTokenRevokedError:
        current_app.logger.warning(
            "Spotify refresh token has been revoked/expired; caller must discard "
            "it and prompt the user to reconnect."
        )
        return None, None, None

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
        response = requests.get('https://api.spotify.com/v1/me', headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Error getting Spotify user info: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        current_app.logger.error(f"Exception getting Spotify user info: {str(e)}")
        return None
