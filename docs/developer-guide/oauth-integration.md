# OAuth Integration

This document details how Quizzical Beats integrates with OAuth providers, including Spotify, Deezer, and Dropbox.

## Overview

Quizzical Beats uses OAuth 2.0 to authenticate with third-party services. The current OAuth implementation provides:

- API access to third-party services (Spotify API, Dropbox files)
- Token storage and refresh mechanisms
- Fallback strategies when tokens expire

## OAuth Provider Configuration

### Spotify OAuth

Spotify OAuth is used for API access:

```python
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', 'http://localhost:5000/auth/spotify/callback')
```

### Dropbox OAuth

Dropbox OAuth enables file export functionality:

```python
DROPBOX_APP_KEY = os.environ.get('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.environ.get('DROPBOX_APP_SECRET')
DROPBOX_REDIRECT_URI = os.environ.get('DROPBOX_REDIRECT_URI', 'http://localhost:5000/users/dropbox/callback')
```

### Deezer OAuth (linked playlist export)

Deezer linking is an authenticated, user-bound flow used only when exporting a
round to a personal Deezer playlist. Configure `DEEZER_APP_ID`,
`DEEZER_APP_SECRET`, and the exact `DEEZER_REDIRECT_URI` callback in the Deezer
developer console (for example `https://your-domain.example/deezer-callback`).

The authorization request asks only for `manage_library`. OAuth state is
single-use, bound to the logged-in user session, expires after ten minutes,
and may carry a round ID for returning to the round after linking. The callback
verifies the Deezer `/user/me` identity before storing the account. Access
tokens are encrypted server-side and are never placed in browser state or logs.
Set `DEEZER_TOKEN_ENCRYPTION_KEY` to a Fernet key for key rotation/isolation;
if omitted, the application derives a key from `SECRET_KEY`.

The profile page provides Connect, reconnect, and disconnect controls. The
link form is `POST /deezer-link` (endpoint `deezer.link_deezer`) and accepts an
optional `round_id` form field. Disconnect is `POST /deezer-disconnect`.

## Dropbox Integration Implementation

The Dropbox OAuth integration is implemented directly in the User model:

```python
class User(db.Model):
    # Other user fields...
    
    # Dropbox OAuth fields
    dropbox_id = db.Column(db.String(100), nullable=True)
    dropbox_token = db.Column(db.Text(), nullable=True)
    dropbox_refresh_token = db.Column(db.Text(), nullable=True)
    dropbox_token_expiry = db.Column(db.DateTime(), nullable=True)
    dropbox_export_path = db.Column(db.String(255), nullable=True)
```

### Dropbox Authentication Flow

1. User initiates Dropbox connection from their profile page
2. Application redirects to Dropbox's authorization page
3. User grants permission to the application
4. Dropbox redirects back to our callback URL with an authorization code
5. Application exchanges the code for access and refresh tokens
6. Tokens and basic user info are stored in the user's record

Example of the callback handler:

```python
@users_bp.route('/dropbox/callback')
@login_required
def dropbox_callback():
    # Handle errors
    if 'error' in request.args:
        flash(f'Dropbox authorization failed: {error}', 'error')
        return redirect(url_for('users.profile'))
    
    # Exchange authorization code for tokens
    code = request.args.get('code')
    token_info = exchange_code_for_token(code)
    
    # Store tokens in the user model
    current_user.dropbox_token = token_info.get('access_token')
    current_user.dropbox_refresh_token = token_info.get('refresh_token')
    
    # Store expiration time
    expires_in = token_info.get('expires_in', 14400)  # Default to 4 hours
    current_user.dropbox_token_expiry = datetime.now() + timedelta(seconds=expires_in)
    
    # Get and store account info
    account_info = get_dropbox_account_info(current_user.dropbox_token)
    if account_info:
        current_user.dropbox_id = account_info.get('account_id')
        
    db.session.commit()
    
    return redirect(url_for('users.profile'))
```

## Token Management

### Token Refresh

Tokens are refreshed when they expire. The Dropbox implementation uses:

```python
def get_current_user_dropbox_token():
    """Get a valid Dropbox access token for the current user, refreshing if needed"""
    if not current_user or not current_user.is_authenticated:
        return None
    
    # Check if token exists and is valid
    if (current_user.dropbox_token and 
        current_user.dropbox_token_expiry and 
        current_user.dropbox_token_expiry > datetime.now() + timedelta(minutes=5)):
        return current_user.dropbox_token
    
    # Token is missing or about to expire - try to refresh
    if current_user.dropbox_refresh_token:
        # Refresh the token
        token_info = refresh_dropbox_token(current_user.dropbox_refresh_token)
        
        if token_info and 'access_token' in token_info:
            # Update token in database
            current_user.dropbox_token = token_info['access_token']
            expires_in = token_info.get('expires_in', 14400)
            current_user.dropbox_token_expiry = datetime.now() + timedelta(seconds=expires_in)
            
            db.session.commit()
            
            return current_user.dropbox_token
    
    return None
```

### Token Revocation

Users can disconnect their Dropbox accounts:

```python
@users_bp.route('/dropbox/disconnect', methods=['POST'])
@login_required
def dropbox_disconnect():
    """Disconnect user's Dropbox account"""
    # Revoke token if present
    if current_user.dropbox_token:
        try:
            revoke_token(current_user.dropbox_token)
        except Exception as e:
            # Log the error but continue
            pass
    
    # Clear Dropbox credentials
    current_user.dropbox_token = None
    current_user.dropbox_refresh_token = None
    current_user.dropbox_token_expiry = None
    current_user.dropbox_id = None
    
    db.session.commit()
    
    return redirect(url_for('users.profile'))
```

## Security Considerations

When working with OAuth:

- Always use HTTPS in production
- Store tokens securely
- Implement proper token refresh
- Handle token revocation when users disconnect accounts
- Request minimal scope access
- Validate all OAuth-related inputs
- Use the official provider documentation for the most up-to-date OAuth implementation details
