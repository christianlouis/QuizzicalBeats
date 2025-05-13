"""
Authentication routes for the Music Round application
"""
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from flask_login import login_user, current_user, logout_user, login_required
from werkzeug.security import check_password_hash
from musicround.models import User, db
from datetime import datetime
import spotipy

# Create blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/')
def index():
    """Landing page"""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    return render_template('auth/index.html')

@auth_bp.route('/login')
def login():
    """Redirect to user login page"""
    return redirect(url_for('users.login'))

@auth_bp.route('/login-with-spotify')
def login_with_spotify():
    """Start Spotify OAuth flow for login"""
    # If user is already logged in, redirect to home
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))
    
    # Create a new OAuth object
    sp_oauth = current_app.config['sp_oauth']
    
    # Get the authorization URL
    auth_url = sp_oauth.get_authorize_url()
    
    # Store state in session for validation
    session['oauth_state'] = sp_oauth.state
    
    # Set flag that we're using OAuth for login, not just connection
    session['spotify_login_flow'] = True
    
    return redirect(auth_url)

@auth_bp.route('/callback')
def callback():
    """Handle Spotify OAuth callback for login"""
    try:
        # Verify the state parameter
        if request.args.get('state') != session.get('oauth_state'):
            flash("Authentication state mismatch. Please try logging in again.", "danger")
            return redirect(url_for('auth.index'))
        
        # Get the authorization code
        code = request.args.get('code')
        if not code:
            flash("No authorization code received from Spotify.", "danger")
            return redirect(url_for('auth.index'))
        
        # Exchange the code for an access token
        sp_oauth = current_app.config['sp_oauth']
        token_info = sp_oauth.get_access_token(code)
        
        if not token_info or 'access_token' not in token_info:
            flash("Failed to obtain access token from Spotify.", "danger")
            return redirect(url_for('auth.index'))
        
        # Store the token in the session
        session['access_token'] = token_info['access_token']
        session['refresh_token'] = token_info.get('refresh_token')
        session['token_expiration'] = token_info.get('expires_at')
        session['token_source'] = 'user'
        
        # Get user info from Spotify to find or create the user account
        sp = spotipy.Spotify(auth=token_info['access_token'])
        spotify_user_info = sp.current_user()
        
        if not spotify_user_info or 'id' not in spotify_user_info:
            flash("Could not fetch user information from Spotify.", "danger")
            return redirect(url_for('auth.index'))
        
        spotify_id = spotify_user_info['id']
        email = spotify_user_info.get('email')
        display_name = spotify_user_info.get('display_name', spotify_id)
        
        # Log the Spotify login attempt
        current_app.logger.info(f"Spotify login attempt: ID={spotify_id}, Email={email}, Name={display_name}")
        
        # Look for an existing user with this Spotify ID
        user = User.query.filter_by(oauth_id=spotify_id).first()
        
        # If no user found with this Spotify ID but we have an email, try to find by email
        if not user and email:
            user = User.query.filter_by(email=email).first()
            if user:
                # Update the user's Spotify ID if they have an account with the same email
                user.oauth_id = spotify_id
                current_app.logger.info(f"Linked Spotify ID {spotify_id} to existing account: {user.username}")
        
        # If we still don't have a user, create a new one
        if not user:
            if not email:
                # If Spotify didn't provide an email, we can't create a new user automatically
                flash("Your Spotify account does not have an email address. Please register manually.", "danger")
                return redirect(url_for('users.register'))
            
            # Generate a unique username based on Spotify display name
            base_username = ''.join(c for c in display_name if c.isalnum()).lower()
            if not base_username:
                base_username = "spotify_user"
            
            username = base_username
            count = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{count}"
                count += 1
            
            # Create a new user
            from werkzeug.security import generate_password_hash
            import secrets
            
            # Generate a random password - user can reset it later
            random_password = secrets.token_urlsafe(12)
            
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(random_password),
                first_name=display_name.split()[0] if ' ' in display_name else display_name,
                last_name=' '.join(display_name.split()[1:]) if ' ' in display_name else '',
                oauth_id=spotify_id,
                created_at=datetime.now(),
                last_login=datetime.now()
            )
            
            try:
                db.session.add(user)
                db.session.commit()
                current_app.logger.info(f"Created new user from Spotify: {username} (ID: {user.id})")
                flash(f"Welcome! A new account has been created for you as '{username}'.", "success")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating user from Spotify: {e}")
                flash("Error creating account. Please try again or register manually.", "danger")
                return redirect(url_for('users.register'))
        
        # Store the Spotify tokens in the user's account
        user.spotify_token = token_info['access_token']
        user.spotify_refresh_token = token_info.get('refresh_token')
        if 'expires_at' in token_info:
            user.spotify_token_expiry = datetime.fromtimestamp(token_info['expires_at'])
        
        # Update last login time
        user.last_login = datetime.now()
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating user with Spotify tokens: {e}")
            flash("Error updating your account with Spotify information.", "danger")
            return redirect(url_for('users.login'))
        
        # Log the user in
        login_user(user)
        
        # Update the Spotify client with the new token
        current_app.config['sp'].set_auth(token_info['access_token'])
        
        flash("Successfully logged in with Spotify!", "success")
        return redirect(url_for('core.index'))
    
    except Exception as e:
        current_app.logger.error(f"Error during Spotify callback: {e}")
        flash("Error during Spotify authentication. Please try again.", "danger")
        return redirect(url_for('auth.index'))