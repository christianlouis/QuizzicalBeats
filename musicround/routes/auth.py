"""
Authentication routes for the Music Round application
"""
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from flask_login import login_user, current_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from musicround.models import User, db
from datetime import datetime
import requests
import secrets
from musicround.helpers.auth_helpers import oauth, find_or_create_user, update_oauth_tokens, get_spotify_user_info, get_oauth_redirect_uri

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
    """Start Spotify OAuth flow for login using Authlib."""
    if current_user.is_authenticated:
        return redirect(url_for('core.index'))

    if not current_app.config.get('SPOTIFY_CLIENT_ID') or not current_app.config.get('SPOTIFY_CLIENT_SECRET'):
        flash('Spotify login is not configured.', 'danger')
        return redirect(url_for('users.login'))

    # The redirect URI should point to *this* blueprint's callback
    redirect_uri = get_oauth_redirect_uri('auth.callback')
    
    # Ensure 'show_dialog': 'true' is part of authorize_params in auth_helpers.py
    # when registering the Spotify client.
    return oauth.spotify.authorize_redirect(redirect_uri)

@auth_bp.route('/callback')
def callback():
    """Handle Spotify OAuth callback for login using Authlib."""
    try:
        token = oauth.spotify.authorize_access_token()
        current_app.logger.debug(f"Spotify token received for login: {token}")

        # Fetch user info using the token
        spotify_info = get_spotify_user_info(token)

        if not spotify_info or not spotify_info.get('id'):
            flash('Could not fetch Spotify user information. Please try again.', 'danger')
            current_app.logger.error(f"Failed to get Spotify user info for login. Response: {spotify_info}")
            return redirect(url_for('users.login'))

        # Find or create user based on Spotify profile
        # This function needs to handle new user creation if they don't exist
        # or link to an existing user if email matches, etc.
        user = find_or_create_user(spotify_info, 'spotify')

        if not user:
            flash('Could not sign in with Spotify. If you are a new user, registration might be disabled. Please try again or contact support.', 'danger')
            current_app.logger.error(f"Failed to find or create user for Spotify login: {spotify_info.get('email')}")
            return redirect(url_for('users.login'))
        
        # Update tokens in the User model
        if update_oauth_tokens(user, token, 'spotify'):
            login_user(user) # Log in the user
            user.last_login = datetime.now()
            db.session.commit()
            flash('Successfully logged in with Spotify!', 'success')
            current_app.logger.info(f"User {user.username} logged in via Spotify ({spotify_info.get('name')})")
            
            next_page = request.args.get('next') or session.pop('next_url', None)
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('core.index')
            return redirect(next_page)
        else:
            flash('Failed to store Spotify tokens. Please try again.', 'danger')
            current_app.logger.error(f"Failed to update Spotify tokens for user {user.username} during login.")
            return redirect(url_for('users.login'))

    except Exception as e:
        current_app.logger.error(f"Error in Spotify login callback: {str(e)}")
        flash(f'An error occurred during Spotify login: {str(e)}.', 'danger')
        return redirect(url_for('users.login'))