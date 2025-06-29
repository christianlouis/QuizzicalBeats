"""
User authentication and profile management routes
"""
import uuid  # Add missing import
import time  # Add missing import
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify
from flask_login import login_user, current_user, logout_user, login_required  # Ensure flask_login is imported
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

from musicround.models import db, User, Role, SystemSetting
from musicround.helpers.utils import get_available_voices
from musicround.helpers.auth_helpers import oauth, find_or_create_user, update_oauth_tokens, get_google_user_info, get_authentik_user_info, get_spotify_user_info, get_oauth_redirect_uri
from musicround.helpers.spotify_helper import get_spotify_token, get_current_user_spotify_token, get_spotify_user_info as spotify_helper_get_user_info

users_bp = Blueprint('users', __name__, url_prefix='/users')

# Helper function for processing Spotify account linking
def _process_spotify_link(user, token_payload, spotify_user_data):
    """Processes the linking of a Spotify account to a user."""
    spotify_id = spotify_user_data['id']

    # Check if this Spotify account is already linked to another user
    existing_user_with_spotify_id = User.query.filter(User.spotify_id == spotify_id, User.id != user.id).first()
    if existing_user_with_spotify_id:
        flash(f"This Spotify account is already linked to another user ({existing_user_with_spotify_id.username}). "
              "Please use a different Spotify account or log in with that user.", "danger")
        return False

    user.spotify_id = spotify_id
    update_oauth_tokens(user, token_payload, 'spotify') # Saves token, refresh_token, expiry to user model

    # Store comprehensive user info in session
    session['spotify_user_info'] = spotify_user_data

    db.session.commit()
    flash('Your Spotify account has been successfully linked!', 'success')
    current_app.logger.info(f"User {user.id} successfully linked Spotify account {spotify_id}.")
    return True

# Helper function for processing Spotify account disconnection
def _process_spotify_disconnect(user):
    """Processes the disconnection of a user's Spotify account."""
    current_app.logger.info(f"User {user.id} requested Spotify disconnect.")
    
    user.spotify_id = None
    user.spotify_token = None
    user.spotify_refresh_token = None
    user.spotify_token_expiry = None
    
    # Clear related session variables
    session.pop('spotify_display_name', None) 
    session.pop('spotify_user_info', None)
        
    db.session.commit()
    flash('Your Spotify account has been disconnected.', 'success')
    current_app.logger.info(f"User {user.id} successfully disconnected their Spotify account.")

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('users.profile'))
        return f(*args, **kwargs)
    return decorated_function

# OAuth login routes for Google
@users_bp.route('/login/google')
def google_login():
    """Initiate Google OAuth login flow"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))    # Google login is disabled if client ID is not set
    if not current_app.config.get('GOOGLE_CLIENT_ID'):
        flash('Google login is not configured.', 'danger')
        return redirect(url_for('users.login'))
    
    redirect_uri = get_oauth_redirect_uri('users.google_callback')
    return oauth.google.authorize_redirect(redirect_uri)

@users_bp.route('/login/google/callback')
def google_callback():
    """Handle Google OAuth callback"""
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.userinfo()
        
        # Debug the response
        current_app.logger.debug(f"Google user info response: {user_info}")
        
        # Check for required fields and adapt to Google's response format
        if 'sub' in user_info and 'id' not in user_info:
            user_info['id'] = user_info['sub']  # Google uses 'sub' for the user ID
        
        # Find or create user
        user = find_or_create_user(user_info, 'google')
        if not user:
            flash('Could not authenticate with Google. Please try again.', 'danger')
            return redirect(url_for('users.login'))
            
        # Update tokens and log in the user
        update_oauth_tokens(user, token, 'google')
        login_user(user)
        
        # Set last_login as a datetime object for consistency
        user.last_login = datetime.now()
        db.session.commit()
        
        # Redirect to next page or home
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('core.index')
            
        flash('You have been logged in via Google!', 'success')
        return redirect(next_page)
        
    except Exception as e:
        current_app.logger.error(f"Error in Google callback: {str(e)}")
        flash('An error occurred during Google authentication. Please try again.', 'danger')
        return redirect(url_for('users.login'))

# OAuth login routes for Authentik
@users_bp.route('/login/authentik')
def authentik_login():
    """Initiate Authentik OAuth login flow"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))    # Authentik login is disabled if client ID is not set
    if not current_app.config.get('AUTHENTIK_CLIENT_ID'):
        flash('Authentik login is not configured.', 'danger')
        return redirect(url_for('users.login'))
    
    redirect_uri = get_oauth_redirect_uri('users.authentik_callback')
    return oauth.authentik.authorize_redirect(redirect_uri)

@users_bp.route('/login/authentik/callback')
def authentik_callback():
    """Handle Authentik OAuth callback"""
    try:
        token = oauth.authentik.authorize_access_token()
        user_info = token.get('userinfo')
        
        # Debug the response
        current_app.logger.debug(f"Authentik user info response: {user_info}")
        
        if not user_info:
            # If userinfo not in token, fetch it separately
            user_info = get_authentik_user_info(token)
            
        # Check for required fields and adapt to Authentik's response format
        if user_info and 'sub' in user_info and 'id' not in user_info:
            user_info['id'] = user_info['sub']  # Authentik uses 'sub' for the user ID
            
        # Find or create user
        user = find_or_create_user(user_info, 'authentik')
        if not user:
            flash('Could not authenticate with Authentik. Please try again.', 'danger')
            return redirect(url_for('users.login'))
            
        # Update tokens and log in the user
        update_oauth_tokens(user, token, 'authentik')
        login_user(user)
        
        user.last_login = datetime.now()
        db.session.commit()
        
        # Redirect to next page or home
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('core.index')
            
        flash('You have been logged in via Authentik!', 'success')
        return redirect(next_page)
        
    except Exception as e:
        current_app.logger.error(f"Error in Authentik callback: {str(e)}")
        flash('An error occurred during Authentik authentication. Please try again.', 'danger')
        return redirect(url_for('users.login'))

# OAuth login routes for Dropbox
@users_bp.route('/dropbox/auth')
@login_required
def dropbox_auth():
    """Initiate Dropbox OAuth flow"""
    from musicround.helpers.dropbox_helper import get_dropbox_auth_url
    
    # Generate the authorization URL
    auth_url = get_dropbox_auth_url()
    
    if auth_url:
        # Store state in session to prevent CSRF
        return redirect(auth_url)
    else:
        flash('Error initiating Dropbox authorization', 'error')
        return redirect(url_for('users.profile'))

@users_bp.route('/dropbox/callback')
@login_required
def dropbox_callback():
    """Handle Dropbox OAuth callback"""
    from musicround.helpers.dropbox_helper import exchange_code_for_token, get_dropbox_account_info
    
    error = request.args.get('error')
    if error:
        flash(f'Dropbox authorization failed: {error}', 'error')
        return redirect(url_for('users.profile'))
    
    code = request.args.get('code')
    if not code:
        flash('No authorization code received from Dropbox', 'error')
        return redirect(url_for('users.profile'))
    
    # Exchange the code for a token
    result = exchange_code_for_token(code)
    
    if not result or not result.get('access_token'):
        flash('Failed to obtain Dropbox access token', 'error')
        return redirect(url_for('users.profile'))
    
    # Store the tokens in the user's account
    current_user.dropbox_token = result.get('access_token')
    current_user.dropbox_refresh_token = result.get('refresh_token')
    
    # Convert expires_in (seconds from now) to an actual datetime
    expires_in = result.get('expires_in', 14400)  # Default to 4 hours if not provided
    current_user.dropbox_token_expiry = datetime.now() + timedelta(seconds=expires_in)
    
    # Get account information to store the account ID
    account_info = get_dropbox_account_info(current_user.dropbox_token)
    
    if account_info and account_info.get('account_id'):
        current_user.dropbox_id = account_info.get('account_id')
        
        # Store additional info in session for display
        session['dropbox_user_info'] = {
            'name': account_info.get('name', {}).get('display_name', ''),
            'email': account_info.get('email', ''),
            'picture': account_info.get('profile_photo_url', '')
        }
        
        # If it's the first time setting up Dropbox, set a default export path
        if not current_user.dropbox_export_path:
            current_user.dropbox_export_path = '/QuizzicalBeats'
        
        db.session.commit()
        flash('Successfully connected to Dropbox!', 'success')
    else:
        flash('Connected to Dropbox, but failed to get account information', 'warning')
        db.session.commit()
    
    return redirect(url_for('users.profile'))

@users_bp.route('/dropbox/disconnect', methods=['POST'])
@login_required
def dropbox_disconnect():
    """Disconnect user's Dropbox account"""
    # Revoke token if present (optional but good practice)
    if current_user.dropbox_token:
        try:
            from musicround.helpers.dropbox_helper import revoke_token
            revoke_token(current_user.dropbox_token)
        except Exception as e:
            current_app.logger.error(f"Error revoking Dropbox token: {str(e)}")
    
    # Clear Dropbox credentials
    current_user.dropbox_token = None
    current_user.dropbox_refresh_token = None
    current_user.dropbox_token_expiry = None
    current_user.dropbox_id = None
    
    # Keep the export path in case they reconnect
    
    # Remove session info
    if 'dropbox_user_info' in session:
        session.pop('dropbox_user_info')
    
    db.session.commit()
    flash('Dropbox account disconnected successfully', 'success')
    
    return redirect(url_for('users.profile'))

@users_bp.route('/dropbox/export-path', methods=['POST'])
@login_required
def update_dropbox_export_path():
    """Update the user's Dropbox export path"""
    export_path = request.form.get('dropbox_export_path', '/QuizzicalBeats')
    
    # Simple validation
    if not export_path.startswith('/'):
        export_path = '/' + export_path
    
    # Remove any trailing slash
    if export_path.endswith('/') and len(export_path) > 1:
        export_path = export_path[:-1]
    
    # Save the path
    current_user.dropbox_export_path = export_path
    db.session.commit()
    
    flash('Dropbox export path updated successfully', 'success')
    return redirect(url_for('users.profile'))

@users_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Register a new user"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    
    # Check if new signups are allowed
    allow_signups = SystemSetting.get('allow_signups', 'true') == 'true'
    if not allow_signups:
        flash('New user registration is currently disabled.', 'danger')
        return redirect(url_for('users.login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        
        # Validate the form data
        if not username or not email or not password or not confirm_password:
            flash('All fields are required', 'danger')
            return render_template('users/register.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template('users/register.html')
        
        # Check if username or email already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return render_template('users/register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return render_template('users/register.html')
        
        # Create new user
        try:
            new_user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                first_name=first_name,
                last_name=last_name,
                created_at=datetime.now(),
                last_login=datetime.now()
            )
            db.session.add(new_user)
            db.session.commit()
            
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('users.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error registering user: {e}")
            flash('An error occurred during registration', 'danger')
            return render_template('users/register.html')
    
    return render_template('users/register.html')

@users_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Log in a user"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    
    # Check which OAuth providers are configured
    oauth_providers = {
        'google': bool(current_app.config.get('GOOGLE_CLIENT_ID')),
        'authentik': bool(current_app.config.get('AUTHENTIK_CLIENT_ID'))
    }
    
    if request.method == 'POST':
        username_or_email = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        # Find user by username or email
        user = User.query.filter_by(username=username_or_email).first()
        if not user:
            user = User.query.filter_by(email=username_or_email).first()
        
        # Check if user exists and password is correct
        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid username/email or password', 'danger')
            return render_template('users/login.html', oauth_providers=oauth_providers)
        
        # Log in the user
        login_user(user, remember=remember)
        user.last_login = datetime.now()
        db.session.commit()
        
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('core.index')
            
        flash('You have been logged in!', 'success')
        return redirect(next_page)
    
    return render_template('users/login.html', oauth_providers=oauth_providers)

@users_bp.route('/logout')
@login_required
def logout():
    """Log out a user"""
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('users.login'))

@users_bp.route('/profile')
@login_required
def profile():
    """Display user profile"""
    # Check which view functions exist to avoid using current_app in template
    available_routes = {
        'rounds_list': 'rounds.rounds_list' in current_app.view_functions,
        'view_songs': 'core.view_songs' in current_app.view_functions,
        'create_round': 'rounds.create' in current_app.view_functions
    }
    
    # Check if any admin users exist
    admin_role = Role.query.filter_by(name='admin').first()
    admin_exists = False
    if admin_role:
        admin_exists = admin_role.users.count() > 0
      # Get current time for token expiry checks
    now = datetime.now()
    
    # Get info about current tokens
    system_refresh_token = SystemSetting.get('fallback_spotify_refresh_token', '')
    session_bearer = session.get('access_token', '') # This is the manually entered token or system token
    token_source = session.get('token_source', '')
    client_token_expiry = session.get('client_token_expiry', 0) # For system client_credentials token
    
    # Use centralized token management to get the best available token
    spotify_token, spotify_token_source = get_spotify_token()
    
    # Fetch user info for the active token
    spotify_user_info = None # This is passed to the template
    active_username = None
    active_user_id = None
    active_user_image = None
    active_token_expiry = None

    # If we have a valid token from centralized management, use it
    if spotify_token and spotify_token_source in ['user', 'system']:
        try:
            spotify_user_info = spotify_helper_get_user_info(spotify_token)
            if spotify_user_info:
                token_source = spotify_token_source
                session['token_source'] = spotify_token_source
                active_user_id = spotify_user_info.get('id')
                active_username = spotify_user_info.get('display_name') or active_user_id
                images = spotify_user_info.get('images', [])
                if images: 
                    active_user_image = images[0].get('url')
                
                # Set token expiry based on source
                if spotify_token_source == 'user':
                    active_token_expiry = current_user.spotify_token_expiry
                else:  # system token
                    system_token_expiry_str = SystemSetting.get('system_spotify_token_expiry', '')
                    if system_token_expiry_str:
                        try:
                            active_token_expiry = datetime.fromisoformat(system_token_expiry_str)
                        except ValueError:
                            pass
                
                current_app.logger.debug(f"Fetched Spotify user info for {active_username} using {spotify_token_source} token.")
        except Exception as e:
            current_app.logger.error(f"Error fetching Spotify user info with {spotify_token_source} token: {str(e)}")
            if spotify_token_source == 'user':
                flash("Your Spotify connection may have expired. Please try re-linking.", "warning")
      
    # Priority 2: Manually entered bearer token from session (fallback)
    if not spotify_user_info and session_bearer: # if no valid token from centralized management, check manual token
        current_app.logger.debug(f"Attempting to use session_bearer token. Source: {token_source}")
            
        # If token_source indicates it's a user-like token or generic 'manual'
        if token_source in ['manual', 'user_manual', 'user']: # 'user' if somehow set without db token
            try:
                resp = oauth.spotify.get('https://api.spotify.com/v1/me', token={'access_token': session_bearer, 'token_type': 'Bearer'})
                if resp.ok:
                    spotify_user_info = resp.json()
                    if spotify_user_info and 'id' in spotify_user_info:
                        active_user_id = spotify_user_info.get('id')
                        active_username = spotify_user_info.get('display_name') or active_user_id
                        images = spotify_user_info.get('images', [])
                        if images: active_user_image = images[0].get('url')
                        current_app.logger.debug(f"Fetched Spotify user info for {active_username} using manual bearer token.")
                        # Determine expiry for manual token (typically 1 hour from when it was added)
                        token_added_time = session.get('bearer_token_added', now.timestamp())
                        active_token_expiry = datetime.fromtimestamp(token_added_time) + timedelta(hours=1)
                        session['token_source'] = 'user_manual' # Clarify token source
                        token_source = 'user_manual'
                    else: # Token worked but no user ID, or not OK
                         current_app.logger.warning(f"Manual bearer token ({token_source}) did not return valid user info. Status: {resp.status_code}")
                         spotify_user_info = None # Ensure it's None
                else:
                    current_app.logger.error(f"Error fetching Spotify user info with manual bearer token: {resp.status_code} {resp.text}")
                    spotify_user_info = None
                    if resp.status_code in [401, 403]: flash("Manually entered Spotify token is invalid or expired.", "warning")

            except Exception as user_info_error:
                current_app.logger.error(f"Exception fetching Spotify user info with manual bearer token: {str(user_info_error)}")
                spotify_user_info = None
        
        # If token_source indicates it's client_credentials or if user fetch failed, it might be client_credentials
        if not spotify_user_info and token_source in ['client_credentials', 'client_credentials_manual']:
            try:
                resp_cc = oauth.spotify.get('https://api.spotify.com/v1/browse/new-releases', params={'limit':1}, token={'access_token': session_bearer, 'token_type': 'Bearer'})
                if resp_cc.ok:
                    current_app.logger.info("Manual/Session token confirmed as working client credentials.")
                    if token_source == 'client_credentials_manual':
                        token_added_time = session.get('bearer_token_added', now.timestamp())
                        active_token_expiry = datetime.fromtimestamp(token_added_time) + timedelta(hours=1)
                    else: # system client_credentials
                        active_token_expiry = datetime.fromtimestamp(client_token_expiry) if client_token_expiry else None
                else:
                    current_app.logger.warning(f"Manual/Session client credentials token validation failed. Status: {resp_cc.status_code}")
                    if resp_cc.status_code in [401, 403]: flash("The client credentials token in session is invalid.", "warning")

            except Exception as cc_error:
                current_app.logger.error(f"Exception validating client credentials token from session: {str(cc_error)}")

    # Determine Spotify connection status based on the findings
    spotify_status = 'none'
    if spotify_token_source == 'user':
        spotify_status = 'user'
    elif spotify_token_source == 'system':
        spotify_status = 'system'
    elif token_source == 'user_manual' and spotify_user_info: # Successfully used manual token as user
        spotify_status = 'bearer' 
    elif token_source in ['client_credentials', 'client_credentials_manual'] and session_bearer:
        spotify_status = 'client_credentials'
    
    return render_template(
        'users/profile.html', 
        available_routes=available_routes, 
        admin_exists=admin_exists,
        spotify_status=spotify_status,
        system_refresh_token=system_refresh_token,
        session_bearer=session_bearer,
        token_source=token_source,
        client_token_expiry=client_token_expiry,
        now=now,
        spotify_user_info=spotify_user_info,
        active_username=active_username,
        active_user_id=active_user_id,
        active_user_image=active_user_image,
        active_token_expiry=active_token_expiry
    )

@users_bp.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit user profile"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        dropbox_export_path = request.form.get('dropbox_export_path', '/QuizzicalBeats').strip()
        
        # Check if username or email already exists and belongs to another user
        if username != current_user.username and User.query.filter_by(username=username).first():
            flash('That username is already taken', 'danger')
            return render_template('users/edit_profile.html')
        
        if email != current_user.email and User.query.filter_by(email=email).first():
            flash('That email is already registered', 'danger')
            return render_template('users/edit_profile.html')
        
        # Update user profile
        current_user.username = username
        current_user.email = email
        current_user.first_name = first_name
        current_user.last_name = last_name
        current_user.dropbox_export_path = dropbox_export_path
        
        try:
            db.session.commit()
            flash('Your profile has been updated', 'success')
            return redirect(url_for('users.profile'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile: {e}")
            flash('An error occurred while updating your profile', 'danger')
    
    return render_template('users/edit_profile.html')

@users_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change user password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Check if current password is correct
        if not check_password_hash(current_user.password_hash, current_password):
            flash('Current password is incorrect', 'danger')
            return render_template('users/change_password.html')
        
        # Check if new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match', 'danger')
            return render_template('users/change_password.html')
        
        # Update password
        current_user.password_hash = generate_password_hash(new_password)
        
        try:
            db.session.commit()
            flash('Your password has been changed', 'success')
            return redirect(url_for('users.profile'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error changing password: {e}")
            flash('An error occurred while changing your password', 'danger')
    
    return render_template('users/change_password.html')

@users_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Handle forgot password requests"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        
        # Find user by email
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate reset token
            token = str(uuid.uuid4())
            user.reset_token = token
            user.reset_token_expiry = datetime.now() + timedelta(hours=24)
            
            try:
                db.session.commit()
                
                # Build reset URL
                reset_url = url_for('users.reset_password', token=token, _external=True)
                
                # Email content
                subject = "Quizzical Beats Password Reset"
                body_text = f"""Hello {user.username},

You recently requested to reset your password for your Quizzical Beats account.
Please click the link below to reset your password:

{reset_url}

This link will expire in 24 hours.

If you did not request a password reset, please ignore this email or contact support if you have questions.

Best regards,
The Quizzical Beats Team
"""
                
                # Import and use the email helper
                from musicround.helpers.email_helper import send_email
                success, message = send_email(recipient=email, subject=subject, body_text=body_text)
                
                if success:
                    flash('Password reset instructions have been sent to your email address.', 'success')
                    current_app.logger.info(f"Password reset email sent to {email}")
                else:
                    # Log the failure but don't reveal to user that the email exists
                    current_app.logger.error(f"Failed to send password reset email: {message}")
                    flash('If your email is registered, you will receive a password reset link.', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error generating reset token: {e}")
                flash('An error occurred. Please try again.', 'danger')
        else:
            # Don't reveal that email doesn't exist
            # Add a small delay to prevent email enumeration
            time.sleep(1)
            flash('If your email is registered, you will receive a password reset link.', 'success')
            current_app.logger.info(f"Password reset attempted for non-existent email: {email}")
    
    return render_template('users/forgot_password.html')

@users_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password using token"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    
    # Find user by reset token
    user = User.query.filter_by(reset_token=token).first()
    
    # Check if token is valid and not expired
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.now():
        flash('The password reset link is invalid or has expired', 'danger')
        return redirect(url_for('users.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template('users/reset_password.html', token=token)
        
        # Update password and clear token
        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expiry = None
        
        try:
            db.session.commit()
            
            # Send confirmation email
            subject = "Your Quizzical Beats Password Has Been Reset"
            body_text = f"""Hello {user.username},

Your password has been successfully reset. You can now log in with your new password.

If you did not reset your password, please contact support immediately.

Best regards,
The Quizzical Beats Team
"""
            
            # Import and use email helper
            from musicround.helpers.email_helper import send_email
            send_email(recipient=user.email, subject=subject, body_text=body_text)
            
            flash('Your password has been reset. You can now log in.', 'success')
            current_app.logger.info(f"Password reset successful for user: {user.username}")
            return redirect(url_for('users.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error resetting password: {e}")
            flash('An error occurred while resetting your password', 'danger')
    
    return render_template('users/reset_password.html', token=token)

@users_bp.route('/spotify-link', methods=['GET', 'POST'])
@login_required
def spotify_link():
    """
    GET: Show management UI (manage_spotify.html) with current status and options.    POST: Trigger Spotify OAuth flow for linking/re-linking.
    """
    if request.method == 'POST':
        # Only POST triggers the OAuth flow
        if not current_app.config.get('SPOTIFY_CLIENT_ID'):
            flash('Spotify integration is not configured.', 'danger')
            return redirect(url_for('users.spotify_link')) # Redirect to spotify_link page
        redirect_uri = get_oauth_redirect_uri('users.spotify_link_callback')
        return oauth.spotify.authorize_redirect(redirect_uri, show_dialog='true')

    # GET: Show management UI
    spotify_user_details = None 
    if current_user.spotify_id:
        spotify_user_details = {
            "id": current_user.spotify_id,
            "display_name": session.get('spotify_display_name', current_user.spotify_id) 
        }
    
    now = datetime.now()
    spotify_user_info = session.get('spotify_user_info')
    return render_template('users/manage_spotify.html', 
                           spotify_user_details=spotify_user_details, 
                           now=now, 
                           spotify_user_info=spotify_user_info)

@users_bp.route('/spotify-link/callback')
@login_required
def spotify_link_callback():
    """Callback for linking Spotify to an existing user account."""
    try:
        token = oauth.spotify.authorize_access_token()
        user_info = get_spotify_user_info(token)
        
        if not user_info or 'id' not in user_info:
            flash('Failed to get user information from Spotify.', 'danger')
            current_app.logger.error(f"Spotify link callback: Missing ID in user_info for user {current_user.id}. Info: {user_info}")
            return redirect(url_for('users.spotify_link')) # Redirect to spotify_link page

        _process_spotify_link(current_user, token, user_info)

    except Exception as e:
        current_app.logger.error(f"Error in Spotify link callback for user {current_user.id}: {str(e)}")
        flash('An error occurred while linking your Spotify account. Please try again.', 'danger')
    
    return redirect(url_for('users.spotify_link')) # Redirect to spotify_link page

@users_bp.route('/spotify/disconnect', methods=['POST'])
@login_required
def spotify_disconnect():
    """Disconnect user's Spotify account."""
    _process_spotify_disconnect(current_user)
    return redirect(url_for('users.spotify_link')) # Redirect to spotify_link page

@users_bp.route('/update-bearer-token', methods=['POST'])
@login_required
def update_bearer_token():
    """Update the Spotify bearer token in the session"""
    # Check if clearing token was requested
    if request.form.get('clear_token'):
        session.pop('access_token', None)
        session.pop('token_source', None)
        session.pop('bearer_token_added', None)
        current_app.logger.info(f"User {current_user.id} cleared Spotify bearer token from session")
        flash('Spotify bearer token has been cleared', 'success')
        return redirect(url_for('users.profile'))
    
    # Get bearer token from form
    bearer_token = request.form.get('bearer_token', '').strip()
    if not bearer_token:
        flash('No bearer token provided', 'warning')
        return redirect(url_for('users.profile'))
    
    try:
        # Store the token in session with timestamp and mark as manual initially
        session['access_token'] = bearer_token
        session['token_source'] = 'manual' # Initial assumption
        session['bearer_token_added'] = datetime.now().timestamp()
        
        current_app.logger.info(f"User {current_user.id} added a manual bearer token to session. Validating: {bearer_token[:10]}...")
        
        try:
            resp_me = oauth.spotify.get('https://api.spotify.com/v1/me', token={'access_token': bearer_token, 'token_type': 'Bearer'})
            user_info = resp_me.json() if resp_me.ok else None

            if user_info and 'id' in user_info:
                # This is a user OAuth token
                username = user_info.get('display_name') or user_info.get('id')
                
                # Update token source to reflect it's a user token
                session['token_source'] = 'user_manual'
                current_app.logger.info(f"Token identified as user OAuth token for: {username} (ID: {user_info.get('id')})")
                flash(f'Successfully authenticated with Spotify as {username}', 'success')
                current_app.logger.info(f"Manual bearer token added for Spotify user: {username} (ID: {user_info.get('id')})")
            else:
                current_app.logger.warning(f"Manual token is not a valid user token. Response: {resp_me.status_code if not resp_me.ok else 'OK, but no ID or user_info was None'}")
                raise Exception("Not a user token or failed to fetch user info")

        except Exception as user_error:
            current_app.logger.warning(f"Validating as user token failed: {str(user_error)}. Checking if client credentials token...")
            try:
                resp_browse = oauth.spotify.get('https://api.spotify.com/v1/browse/new-releases', params={'limit':1}, token={'access_token': bearer_token, 'token_type': 'Bearer'})
                browse_results = resp_browse.json() if resp_browse.ok else None

                if browse_results and 'albums' in browse_results:
                    # This looks like a client credentials token
                    session['token_source'] = 'client_credentials_manual'
                    current_app.logger.info("Token identified as client credentials token (manual)")
                    flash('Token saved as client credentials token. This type of token cannot access user-specific data.', 'warning')
                else:
                    flash('Token saved but validation failed (cannot fetch new releases). The token may be invalid or expired.', 'warning')
                    current_app.logger.warning(f"Manual token validation as client_credentials failed. Response: {resp_browse.status_code if not resp_browse.ok else 'OK, but no albums or browse_results was None'}")
            except Exception as e_browse:
                current_app.logger.error(f"Error validating bearer token as client credentials: {e_browse}")
                flash(f'Token saved but error during client credentials validation: {str(e_browse)}', 'warning')
    except Exception as e_main:
        current_app.logger.error(f"Error processing bearer token: {e_main}")
        flash(f'Error processing token: {str(e_main)}', 'warning')
    
    return redirect(url_for('users.profile'))

@users_bp.route('/use-refresh-token', methods=['POST'])
@login_required
def use_refresh_token():
    # This will be reviewed and updated for authlib
    pass

@users_bp.route('/setup')
@login_required
def setup():
    """One-time setup route to promote the current user to admin"""
    if current_user.is_admin():
        flash('You are already an administrator.', 'info')
        return redirect(url_for('users.profile'))
    
    try:
        # Check if the admin role exists
        admin_role = Role.query.filter_by(name='admin').first()
        
        # Check if any admin users already exist
        admin_exists = False
        if admin_role:
            admin_exists = admin_role.users.count() > 0
            
        if admin_exists:
            flash('An administrator already exists in the system. Only the first user can be promoted to admin.', 'warning')
            return redirect(url_for('users.profile'))
        
        # Create the admin role if it doesn't exist
        if not admin_role:
            admin_role = Role(name='admin', description='Administrator role with full system access')
            db.session.add(admin_role)
            db.session.commit()
            current_app.logger.info(f"Created admin role with ID {admin_role.id}")
            
        # Assign the admin role to the current user
        if admin_role not in current_user.roles:
            current_user.roles.append(admin_role)
            db.session.commit()
            current_app.logger.info(f"User {current_user.username} promoted to admin")
            flash('You have been promoted to administrator!', 'success')
        else:
            flash('You already have the admin role, but it may not be working correctly.', 'warning')
        
        return redirect(url_for('users.profile'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error promoting user to admin: {str(e)}")
        flash(f'Error setting up admin privileges: {str(e)}', 'danger')
        return redirect(url_for('users.profile'))

@users_bp.route('/audio-settings', methods=['GET', 'POST'])
@login_required
def audio_settings():
    """Manage custom audio settings including intro, outro, and replay MP3s"""
    from musicround.helpers.utils import save_user_mp3, generate_tts_mp3, get_available_voices
    
    if request.method == 'POST':
        action = request.form.get('action')
        mp3_type = request.form.get('mp3_type')
        
        if not mp3_type or mp3_type not in ['intro', 'outro', 'replay']:
            flash('Invalid audio type specified', 'danger')
            return redirect(url_for('users.audio_settings'))
        
        if action == 'upload':
            # Handle file upload
            if 'audio_file' not in request.files:
                flash('No file provided', 'danger')
                return redirect(request.url)
                
            file = request.files['audio_file']
            if file.filename == '':
                flash('No file selected', 'danger')
                return redirect(request.url)
                
            # Save the user's uploaded MP3
            file_path = save_user_mp3(file, current_user.username, mp3_type)
            if file_path:
                # Update user's MP3 setting
                setattr(current_user, f'{mp3_type}_mp3', file_path)
                db.session.commit()
                flash(f'Your {mp3_type} audio has been updated', 'success')
            else:
                flash('Invalid file format. Please upload an MP3 file.', 'danger')
                
        elif action == 'generate':
            # Handle text-to-speech generation
            text = request.form.get('tts_text')
            service = request.form.get('tts_service', 'polly')
            voice = request.form.get('tts_voice')
            
            # Process advanced options for each service
            model = None
            stability = None
            similarity = None
            
            if service == 'openai':
                model = request.form.get('openai_model', 'tts-1')
            elif service == 'elevenlabs':
                model = request.form.get('elevenlabs_model', 'eleven_monolingual_v1')
                # Convert string values to float
                try:
                    stability = float(request.form.get('stability', 0.5))
                    similarity = float(request.form.get('similarity_boost', 0.75))
                except (ValueError, TypeError):
                    stability = 0.5
                    similarity = 0.75
            
            if not text:
                flash('No text provided for speech generation', 'danger')
                return redirect(request.url)
                
            # Generate MP3 with the selected service and options
            file_path = generate_tts_mp3(
                text=text, 
                username=current_user.username, 
                mp3_type=mp3_type, 
                service=service,
                voice=voice,
                model=model,
                stability=stability,
                similarity=similarity
            )
            
            if file_path:
                # Update user's MP3 setting
                setattr(current_user, f'{mp3_type}_mp3', file_path)
                db.session.commit()
                flash(f'Your {mp3_type} audio has been generated', 'success')
            else:
                flash('Error generating audio. Please check your settings and try again.', 'danger')
                
        elif action == 'reset':
            # Reset to default MP3
            setattr(current_user, f'{mp3_type}_mp3', None)
            db.session.commit()
            flash(f'Your {mp3_type} audio has been reset to default', 'success')
            
        return redirect(url_for('users.audio_settings'))
    
    # Define default text templates for each type
    default_texts = {
        'intro': 'Welcome to the music quiz! Get ready to test your knowledge of songs and artists.',
        'outro': 'That concludes our music round. How many songs did you recognize?',
        'replay': 'Now we will play all the songs again. Listen carefully!'
    }
    
    # Check which TTS services are available
    tts_services = []
    
    # Check for AWS credentials
    has_aws = all([
        current_app.config.get('AWS_ACCESS_KEY_ID'),
        current_app.config.get('AWS_SECRET_ACCESS_KEY')
    ])
    if has_aws:
        tts_services.append({
            'id': 'polly',
            'name': 'Amazon Polly',
            'description': 'High-quality natural-sounding voices',
            'voices': get_available_voices('polly')
        })
    
    # Check for OpenAI credentials
    has_openai = bool(current_app.config.get('OPENAI_API_KEY'))
    if has_openai:
        tts_services.append({
            'id': 'openai',
            'name': 'OpenAI TTS',
            'description': 'Realistic speech synthesis from OpenAI',
            'voices': get_available_voices('openai'),
            'models': [
                {'id': 'tts-1', 'name': 'TTS-1 (Standard)', 'description': 'Standard quality voice'},
                {'id': 'tts-1-hd', 'name': 'TTS-1-HD (High Definition)', 'description': 'Higher quality voice'}
            ]
        })
    
    # Check for ElevenLabs credentials
    has_elevenlabs = bool(current_app.config.get('ELEVENLABS_API_KEY'))
    if has_elevenlabs:
        tts_services.append({
            'id': 'elevenlabs',
            'name': 'ElevenLabs',
            'description': 'Ultra-realistic AI voices with emotion',
            'voices': get_available_voices('elevenlabs'),
            'models': [
                {'id': 'eleven_monolingual_v1', 'name': 'Monolingual V1', 'description': 'English only, faster generation'},
                {'id': 'eleven_multilingual_v2', 'name': 'Multilingual V2', 'description': 'Supports multiple languages'}
            ],
            'settings': True  # Flag to indicate this service has additional settings
        })
    
    # Handle TTS service selection for the form
    selected_service = request.args.get('tts_service')
    mp3_type = request.args.get('mp3_type') or 'intro'

    # Find the selected service dict
    selected_service_dict = None
    for svc in tts_services:
        if svc['id'] == selected_service:
            selected_service_dict = svc
            break
    if not selected_service_dict and tts_services:
        selected_service_dict = tts_services[0]

    return render_template(
        'users/audio_settings.html',
        default_texts=default_texts,
        tts_services=tts_services,
        has_tts_services=bool(tts_services),
        selected_service=selected_service_dict,
        mp3_type=mp3_type
    )

@users_bp.route('/system-settings', methods=['GET', 'POST'])
@login_required
@admin_required
def system_settings():
    """Admin view to edit global/system settings."""
    from musicround.helpers.utils import get_available_voices
    
    # Define editable system settings keys and their labels
    editable_settings = [
        ('default_tts_service', 'Default TTS Service'),
        ('default_tts_voice', 'Default TTS Voice'),
        ('default_tts_model', 'Default TTS Model'),
        ('fallback_spotify_refresh_token', 'Fallback Spotify Refresh Token'),
        ('spotify_region', 'Default Spotify Region'),
        ('max_songs_per_round', 'Maximum Songs Per Round'),
        ('enable_public_rounds', 'Enable Public Rounds'),
        ('allow_signups', 'Allow New User Registrations'),
        # Add more keys/labels as needed
    ]
    
    # Define which settings are checkboxes (boolean values)
    checkbox_settings = ['enable_public_rounds', 'allow_signups']

    if request.method == 'POST':
        # Process all settings from the form
        for key, _ in editable_settings:
            # Handle checkboxes differently - they're only in the form if checked
            if key in checkbox_settings:
                # Set 'true' if checkbox is in form data, otherwise 'false'
                value = 'true' if key in request.form else 'false'
                current_app.logger.debug(f"Setting {key} to {value}")
                SystemSetting.set(key, value)
            else:
                # Normal text/select fields
                value = request.form.get(key, '')
                current_app.logger.debug(f"Setting {key} to {value}")
                SystemSetting.set(key, value)
                
        # Add a database commit to ensure changes are saved
        db.session.commit()
        
        flash('System settings updated.', 'success')
        return redirect(url_for('users.system_settings'))

    # Get all current settings
    settings = SystemSetting.all_settings()
    
    # Check which TTS services are available
    tts_services = []
    
    # Check for AWS credentials
    has_aws = all([
        current_app.config.get('AWS_ACCESS_KEY_ID'),
        current_app.config.get('AWS_SECRET_ACCESS_KEY')
    ])
    if has_aws:
        tts_services.append({
            'id': 'polly',
            'name': 'Amazon Polly',
            'description': 'High-quality natural-sounding voices',
            'voices': get_available_voices('polly')
        })
    
    # Check for OpenAI credentials
    has_openai = bool(current_app.config.get('OPENAI_API_KEY'))
    if has_openai:
        tts_services.append({
            'id': 'openai',
            'name': 'OpenAI TTS',
            'description': 'Realistic speech synthesis from OpenAI',
            'voices': get_available_voices('openai'),
            'models': [
                {'id': 'tts-1', 'name': 'TTS-1 (Standard)', 'description': 'Standard quality voice'},
                {'id': 'tts-1-hd', 'name': 'TTS-1-HD (High Definition)', 'description': 'Higher quality voice'}
            ]
        })
    
    # Check for ElevenLabs credentials
    has_elevenlabs = bool(current_app.config.get('ELEVENLABS_API_KEY'))
    if has_elevenlabs:
        tts_services.append({
            'id': 'elevenlabs',
            'name': 'ElevenLabs',
            'description': 'Ultra-realistic AI voices with emotion',
            'voices': get_available_voices('elevenlabs'),
            'models': [
                {'id': 'eleven_monolingual_v1', 'name': 'Monolingual V1', 'description': 'English only, faster generation'},
                {'id': 'eleven_multilingual_v2', 'name': 'Multilingual V2', 'description': 'Supports multiple languages'}
            ]
        })
    
    # List of available regions for Spotify
    spotify_regions = [
        {'code': 'US', 'name': 'United States'},
        {'code': 'GB', 'name': 'United Kingdom'},
        {'code': 'DE', 'name': 'Germany'},
        {'code': 'FR', 'name': 'France'},
        {'code': 'ES', 'name': 'Spain'},
        {'code': 'IT', 'name': 'Italy'},
        {'code': 'JP', 'name': 'Japan'},
        {'code': 'AU', 'name': 'Australia'},
        {'code': 'BR', 'name': 'Brazil'},
        {'code': 'CA', 'name': 'Canada'},
    ]
    
    return render_template(
        'admin/system_settings.html',
        settings=settings,
        editable_settings=editable_settings,
        tts_services=tts_services,
        spotify_regions=spotify_regions
    )

@users_bp.route('/backup-manager')
@login_required
@admin_required
def backup_manager():
    """Backup Manager interface for administrators"""
    from musicround.helpers.backup_helper import list_backups, get_backup_summary, generate_backup_config_suggestion
    
    # Get list of existing backups
    backups = list_backups()
    
    # Get backup system status and summary
    backup_summary = get_backup_summary()
    
    # Extract key information from summary
    backup_count = backup_summary.get('backup_count', 0)
    latest_backup = backup_summary.get('latest_backup')
    schedule_enabled = backup_summary.get('schedule_enabled', False)
    schedule_time = backup_summary.get('schedule_time')
    schedule_frequency = backup_summary.get('schedule_frequency', 'daily')
    next_backup = backup_summary.get('next_backup')
    backup_location = backup_summary.get('backup_location')
    retention_days = backup_summary.get('retention_days', 30)
    
    # Generate configuration suggestion instead of Docker Compose labels
    config_suggestion = generate_backup_config_suggestion(retention_days=retention_days)
    
    # Check if we should show the schedule or create forms
    show_schedule_form = request.args.get('show_schedule') == 'true'
    show_create_form = request.args.get('show_create') == 'true'
    
    # Check for notifications from other backup operations
    notification = None
    if 'backup_notification' in session:
        notification = session.pop('backup_notification')
    
    return render_template(
        'admin/backup_manager.html',
        backups=backups,
        backup_count=backup_count,
        latest_backup=latest_backup,
        schedule_enabled=schedule_enabled,
        schedule_time=schedule_time,
        schedule_frequency=schedule_frequency,
        next_backup=next_backup,
        backup_location=backup_location,
        retention_days=retention_days,
        show_schedule_form=show_schedule_form,
        show_create_form=show_create_form,
        notification=notification,
        config_suggestion=config_suggestion
    )

@users_bp.route('/create-backup', methods=['POST'])
@login_required
@admin_required
def create_backup():
    """Create a new backup"""
    from musicround.helpers.backup_helper import create_backup as create_backup_helper
    
    # Check for automation token for scheduled backups
    automation_token = request.headers.get('X-Automation-Token') or request.args.get('token')
    if automation_token == current_app.config.get('AUTOMATION_TOKEN'):
        # Allow the request without authentication for automation
        pass
    elif not current_user.is_authenticated or not current_user.is_admin():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    # Get custom backup name if provided
    backup_name = request.form.get('backup_name', '').strip()
    
    # Get options for what to include
    include_mp3s = request.form.get('include_mp3s', 'true') == 'true'
    include_config = request.form.get('include_config', 'true') == 'true'
    
    # Create the backup
    result = create_backup_helper(
        backup_name=backup_name if backup_name else None,
        include_mp3s=include_mp3s,
        include_config=include_config
    )
    
    # If this is an API request, return JSON
    if request.headers.get('Accept') == 'application/json' or automation_token:
        return jsonify(result)
    
    # Otherwise, store the result for display in the UI and redirect
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/schedule-backup', methods=['POST'])
@login_required
@admin_required
def schedule_backup():
    """Schedule automatic backups"""
    from musicround.helpers.backup_helper import schedule_backup as schedule_backup_helper
    
    # Get schedule settings from form
    schedule_time = request.form.get('schedule_time', '03:00')
    frequency = request.form.get('frequency', 'daily')
    enabled = request.form.get('enabled') == 'true'
    
    # Get retention days from form
    retention_days = request.form.get('retention_days', '30')
    try:
        retention_days = int(retention_days)
    except ValueError:
        retention_days = 30  # Default to 30 days if invalid input
    
    # Save schedule settings
    result = schedule_backup_helper(schedule_time=schedule_time, frequency=frequency, retention_days=retention_days)
    
    # Update enabled status
    from musicround.models import SystemSetting
    SystemSetting.set('backup_schedule_enabled', 'true' if enabled else 'false')
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/verify-backup/<filename>', methods=['GET', 'POST'])
@login_required
@admin_required
def verify_backup(filename):
    """Verify the integrity of a backup file"""
    from musicround.helpers.backup_helper import verify_backup as verify_backup_helper
    
    # Verify the backup
    result = verify_backup_helper(filename)
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/restore-backup/<filename>', methods=['POST'])
@login_required
@admin_required
def restore_backup(filename):
    """Restore from a backup file"""
    from musicround.helpers.backup_helper import restore_backup as restore_backup_helper
    
    # Restore the backup
    result = restore_backup_helper(filename)
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/delete-backup/<filename>', methods=['POST'])
@login_required
@admin_required
def delete_backup(filename):
    """Delete a backup file"""
    from musicround.helpers.backup_helper import delete_backup as delete_backup_helper
    
    # Delete the backup
    result = delete_backup_helper(filename)
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/download-backup/<filename>', methods=['GET', 'POST'])
@login_required
@admin_required
def download_backup(filename):
    """Download a backup file"""
    import os
    from flask import send_file, abort
    
    # Security check: only allow .zip files
    if not filename.endswith('.zip'):
        abort(400, "Invalid file type")
    
    # Only allow downloading from the backup directory
    backup_dir = os.path.join('/data', 'backups')
    backup_path = os.path.join(backup_dir, filename)
    
    # Check if the file exists
    if not os.path.exists(backup_path):
        abort(404, "Backup file not found")
    
    # Send the file
    return send_file(
        backup_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )

@users_bp.route('/upload-backup', methods=['POST'])
@login_required
@admin_required
def upload_backup():
    """Upload a backup file to the system"""
    from musicround.helpers.backup_helper import upload_backup as upload_backup_helper
    
    # Check if a file was uploaded
    if 'backup_file' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('users.backup_manager'))
    
    file = request.files['backup_file']
    
    # Check if the file has a name
    if file.filename == '':
        flash('No file selected', 'danger')
        return redirect(url_for('users.backup_manager'))
    
    # Upload the file
    result = upload_backup_helper(file)
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message')
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/apply-retention-policy', methods=['POST'])
@login_required
@admin_required
def apply_retention_policy():
    """Apply retention policy to backups"""
    from musicround.helpers.backup_helper import apply_retention_policy as apply_retention_policy_helper
    from musicround.models import SystemSetting
    
    # Get retention days from form
    retention_days = request.form.get('retention_days', '30')
    try:
        retention_days = int(retention_days)
    except ValueError:
        retention_days = 30  # Default to 30 days if invalid input
    
    # Save the retention policy setting
    SystemSetting.set('backup_retention_days', str(retention_days))
    
    # Apply the retention policy
    result = apply_retention_policy_helper(retention_days)
    
    # Store the result for display
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message'),
        'details': {
            'deleted_count': result.get('deleted_count', 0),
            'deleted_backups': result.get('deleted_backups', [])
        }
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/update-scheduler', methods=['POST'])
@login_required
@admin_required
def update_scheduler():
    """Update the Ofelia scheduler configuration based on current system settings"""
    from musicround.helpers.backup_helper import update_ofelia_config
    
    # Get the current retention days setting
    from musicround.models import SystemSetting
    retention_days = int(SystemSetting.get('backup_retention_days', '30'))
    
    # Update the scheduler configuration
    result = update_ofelia_config(retention_days=retention_days)
    
    # Store result for display in the UI
    session['backup_notification'] = {
        'status': result.get('status'),
        'message': result.get('message'),
        'details': {
            'schedule': result.get('schedule'),
            'config_content': result.get('config_content'),
            'instructions': result.get('instructions')
        }
    }
    
    return redirect(url_for('users.backup_manager'))

@users_bp.route('/system-health')
@login_required
@admin_required
def system_health():
    """Display system health status"""
    import os
    import platform
    import sys
    import flask
    import sqlite3
    from datetime import datetime
    from musicround.models import Song, Round, User, db
    from musicround.version import VERSION_INFO
    
    # Check database status
    database_status = {"color": "green", "message": "Database is operational and accessible."}
    database_stats = {}
    
    try:
        # Count database records
        database_stats["song_count"] = Song.query.count()
        database_stats["round_count"] = Round.query.count()
        database_stats["user_count"] = User.query.count()
        
        # Get database file size
        db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            size_mb = size_bytes / (1024 * 1024)
            database_stats["file_size"] = f"{size_mb:.2f} MB"
        else:
            database_stats["file_size"] = "Unknown"
            database_status = {"color": "yellow", "message": "Database file not found at expected location."}
    except Exception as e:
        current_app.logger.error(f"Error checking database status: {str(e)}")
        database_status = {"color": "red", "message": f"Database error: {str(e)}"}
    
    # Check storage status
    storage_status = {"color": "green", "message": "All storage locations are accessible and writable."}
    storage_stats = []
    
    # Check important directories
    dirs_to_check = [
        {"path": '/data', "name": "Data Directory"},
        {"path": '/data/backups', "name": "Backups Directory"},
        {"path": os.path.join(os.path.dirname(current_app.root_path), 'mp3'), "name": "MP3 Directory"},
        {"path": os.path.join(current_app.root_path, 'static'), "name": "Static Files"}
    ]
    
    for dir_info in dirs_to_check:
        dir_path = dir_info["path"]
        dir_name = dir_info["name"]
        dir_stat = {"name": dir_name, "path": dir_path}
        
        # Create directory if it doesn't exist (for backups)
        if dir_name == "Backups Directory" and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except Exception:
                pass
        
        if os.path.exists(dir_path):
            # Check if directory is writable
            dir_stat["writable"] = os.access(dir_path, os.W_OK)
            
            # Count files and calculate size
            try:
                files = [f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]
                dir_stat["file_count"] = len(files)
                
                total_size = sum(os.path.getsize(os.path.join(dir_path, f)) for f in files)
                size_mb = total_size / (1024 * 1024)
                dir_stat["size"] = f"{size_mb:.2f} MB"
            except Exception:
                dir_stat["file_count"] = "Error"
                dir_stat["size"] = "Error"
        else:
            dir_stat["writable"] = False
            dir_stat["file_count"] = 0
            dir_stat["size"] = "0.00 MB"
            
            # Update overall status
            if storage_status["color"] != "red":
                storage_status = {"color": "yellow", "message": f"Directory not found: {dir_name}"}
        
        storage_stats.append(dir_stat)
    
    # Check API services status
    api_status = {"color": "green", "message": "All API services are available."}
    service_stats = []
    
    # Check Spotify API
    spotify_service = {
        "name": "Spotify API",
        "status": "ok",
        "message": "Connected and operational"
    }
    
    try:
        spotify_credentials = all([
            current_app.config.get('SPOTIFY_CLIENT_ID'),
            current_app.config.get('SPOTIFY_CLIENT_SECRET')
        ])
        
        if not spotify_credentials:
            spotify_service["status"] = "error"
            spotify_service["message"] = "Missing API credentials"
            if api_status["color"] == "green":
                api_status = {"color": "yellow", "message": "Some API services are unavailable."}
    except Exception as e:
        spotify_service["status"] = "error"
        spotify_service["message"] = f"Error: {str(e)}"
        api_status = {"color": "yellow", "message": "Some API services have errors."}
    
    service_stats.append(spotify_service)
    
    # Check Deezer API
    deezer_service = {
        "name": "Deezer API",
        "status": "ok",
        "message": "Connected and operational"
    }
    
    try:
        deezer_client = current_app.config.get('deezer')
        if not deezer_client:
            deezer_service["status"] = "warning"
            deezer_service["message"] = "Deezer client not initialized"
            if api_status["color"] == "green":
                api_status = {"color": "yellow", "message": "Some API services have warnings."}
    except Exception as e:
        deezer_service["status"] = "error"
        deezer_service["message"] = f"Error: {str(e)}"
        api_status = {"color": "yellow", "message": "Some API services have errors."}
    
    service_stats.append(deezer_service)
    
    # Check memory usage
    memory_status = {"color": "gray", "message": "Memory usage information not available."}
    
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        
        if memory_mb > 500:  # More than 500MB
            memory_status = {"color": "yellow", "message": f"High memory usage: {memory_mb:.2f} MB"}
        else:
            memory_status = {"color": "green", "message": f"Memory usage: {memory_mb:.2f} MB"}
    except ImportError:
        # psutil module not installed
        memory_status = {"color": "gray", "message": "Memory usage information not available (psutil not installed)."}
    except Exception as e:
        # Other errors
        memory_status = {"color": "gray", "message": f"Error checking memory: {str(e)}"}
        current_app.logger.error(f"Error checking memory: {str(e)}")
    
    # System information
    system_info = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
        "flask_version": flask.__version__
    }
    
    # Get last backup timestamp
    from musicround.helpers.backup_helper import list_backups
    backups = list_backups()
    if backups:
        latest_backup = backups[0]
        timestamp = latest_backup.get('timestamp')
        if timestamp:
            try:
                backup_time = datetime.fromisoformat(timestamp)
                database_stats["last_backup"] = backup_time.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                database_stats["last_backup"] = "Unknown format"
        else:
            database_stats["last_backup"] = "Unknown"
    else:
        database_stats["last_backup"] = "Never"
    
    return render_template(
        'admin/system_health.html',
        database_status=database_status,
        storage_status=storage_status,
        api_status=api_status,
        memory_status=memory_status,
        database_stats=database_stats,
        storage_stats=storage_stats,
        service_stats=service_stats,
        system_info=system_info,
        version_info=VERSION_INFO
    )