import os
import logging
import importlib.util
from flask import Flask, session, redirect, url_for, request
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from importlib import import_module
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from musicround.config import Config
from musicround.version import VERSION_INFO, get_version_str

# Initialize SQLAlchemy
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_migrations():
    """
    Run all migration scripts in the migrations directory
    """
    logger.info("Running database migrations...")
    
    # Path to migrations directory
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations')
    if not os.path.isdir(migrations_dir):
        logger.warning(f"Migrations directory not found at {migrations_dir}")
        return
    
    # Get all Python files in the migrations directory
    migration_files = [f for f in os.listdir(migrations_dir) 
                      if f.endswith('.py') and not f.startswith('__')]
    
    if not migration_files:
        logger.info("No migration scripts found")
        return
    
    # Run each migration script
    migration_errors = False
    
    for migration_file in sorted(migration_files):
        try:
            logger.info(f"Loading migration: {migration_file}")
            file_path = os.path.join(migrations_dir, migration_file)
            
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(
                f"migrations.{migration_file[:-3]}", file_path)
            if spec and spec.loader:
                migration_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration_module)
                
                # Check if the module has a run_migration function
                if hasattr(migration_module, "run_migration"):
                    logger.info(f"Executing migration: {migration_file}")
                    result = migration_module.run_migration()
                    
                    # Handle the three possible return values:
                    # True: changes were made successfully
                    # None: no changes needed (already up to date)
                    # False: errors occurred
                    if result is True:
                        logger.info(f"Migration {migration_file} completed successfully")
                    elif result is None:
                        logger.info(f"Migration {migration_file} reported no changes needed")
                    else:
                        logger.warning(f"Migration {migration_file} reported errors")
                        migration_errors = True
                else:
                    logger.warning(f"Migration {migration_file} doesn't have run_migration() function")
            else:
                logger.warning(f"Could not load migration module: {migration_file}")
        except Exception as e:
            logger.error(f"Error running migration {migration_file}: {str(e)}")
            migration_errors = True
    
    if migration_errors:
        logger.warning("Some migrations encountered errors, but the application will continue to start")
    else:
        logger.info("All migrations completed")

def create_app(config=None):
    """
    Factory pattern for creating the Flask app
    """
    # Load environment variables
    load_dotenv()

    # Create Flask app
    app = Flask(__name__, instance_relative_config=True)
    
    # Configure ProxyFix for reverse proxy (e.g., Nginx)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    
    # Create data directory if it doesn't exist
    data_dir = '/data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
    
    # Set the database file path in the data directory
    db_path = os.path.join(data_dir, 'song_data.db')

    # Configure the app
    app.config.from_object(Config)
    
    # Explicitly set the database URI to ensure correct path
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    
    # Initialize extensions with app
    db.init_app(app)
    csrf.init_app(app)
    
    # Register custom Jinja filters
    @app.template_filter('timestamp_to_datetime')
    def timestamp_to_datetime(timestamp):
        """Convert a Unix timestamp or ISO datetime string to a datetime object"""
        from datetime import datetime
        
        if isinstance(timestamp, str):
            try:
                # Try to parse as ISO format string
                return datetime.fromisoformat(timestamp)
            except (ValueError, TypeError):
                try:
                    # Try to convert to float first then use as timestamp
                    return datetime.fromtimestamp(float(timestamp))
                except (ValueError, TypeError):
                    return None
        elif timestamp is None:
            return None
        else:
            # Assume it's a numeric timestamp
            try:
                return datetime.fromtimestamp(timestamp)
            except (ValueError, TypeError):
                return None
    
    @app.template_filter('format_datetime')
    def format_datetime(dt, format='%Y-%m-%d %H:%M:%S'):
        """Format a datetime object to a string"""
        if not dt:
            return "Unknown"
        return dt.strftime(format)
    
    # Set up the Flask-Login extension
    login_manager.login_view = 'users.login'
    login_manager.login_message_category = 'info'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.init_app(app)
    
    # Add version info to template context
    @app.context_processor
    def inject_version():
        from musicround.version import get_version_str, VERSION_INFO
        return {
            'get_version_str': get_version_str,
            'version_info': VERSION_INFO
        }
    
    # Import User model here to avoid circular imports
    from musicround.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass
    
    # Initialize OAuth providers (Google, Authentik)
    from musicround.helpers.auth_helpers import init_oauth
    init_oauth(app)
    
    # Initialize Spotify client for common API access
    # This will be available for any authenticated route
    if app.config['SPOTIFY_CLIENT_ID'] and app.config['SPOTIFY_CLIENT_SECRET']:
        app.config['sp_oauth'] = SpotifyOAuth(
            client_id=app.config['SPOTIFY_CLIENT_ID'],
            client_secret=app.config['SPOTIFY_CLIENT_SECRET'],
            redirect_uri=app.config['SPOTIFY_REDIRECT_URI'],
            scope=app.config['SPOTIFY_SCOPE']
        )
        # Create a Spotify client that will be used throughout the app
        app.config['sp'] = spotipy.Spotify(auth_manager=app.config['sp_oauth'])
    
# Initialize Deezer client - import inside the function to avoid circular dependency
    from musicround.deezer_client import DeezerClient
    app.config['deezer'] = DeezerClient()
    
    # Add before_request handler to ensure Spotify token is available
    @app.before_request
    def ensure_spotify_token():
        """
        Ensure a valid Spotify token is available in the session.
        Priority:
        1. Use existing manual bearer token if present in session
        2. Try to refresh user's token if they have a refresh token
        3. Use client credentials flow as fallback (no user login required)
        """
        # Skip for static files and certain paths
        if request.path.startswith('/static') or request.path.startswith('/favicon.ico'):
            return
            
        # If we already have a manual token in session, don't do anything
        # Manual tokens take priority over everything else
        if 'access_token' in session and session.get('token_source') != 'user' and session.get('token_source') != 'client_credentials':
            app.logger.debug("Using existing manual bearer token")
            return

        from datetime import datetime
        from spotipy.oauth2 import SpotifyOAuth
        from .models import SystemSetting
        import base64
        import requests
            
        try:
            # Only check user token if user is logged in
            if current_user.is_authenticated:
                # Step 1: Try to use user's refresh token
                if current_user.spotify_refresh_token:
                    app.logger.debug(f"Attempting to refresh token for user {current_user.username}")
                    
                    # Create OAuth manager for token refresh
                    sp_oauth = SpotifyOAuth(
                        client_id=app.config['SPOTIFY_CLIENT_ID'],
                        client_secret=app.config['SPOTIFY_CLIENT_SECRET'],
                        redirect_uri=url_for('users.spotify_callback', _external=True),
                        scope=app.config['SPOTIFY_SCOPE']
                    )
                    
                    try:
                        # Refresh user's token
                        token_info = sp_oauth.refresh_access_token(current_user.spotify_refresh_token)
                        
                        if token_info and 'access_token' in token_info:
                            # Update user's tokens in database
                            current_user.spotify_token = token_info['access_token']
                            current_user.spotify_token_expiry = datetime.fromtimestamp(token_info['expires_at'])
                            
                            # If we got a new refresh token (rare but possible), update it
                            if 'refresh_token' in token_info:
                                current_user.spotify_refresh_token = token_info['refresh_token']
                            
                            # Save to database
                            db.session.commit()
                            
                            # Store token in session
                            session['access_token'] = token_info['access_token']
                            session['token_source'] = 'user'
                            
                            app.logger.debug(f"Generated new token for user {current_user.username}")
                            return
                    except Exception as e:
                        app.logger.warning(f"Failed to refresh user token: {str(e)}")
            
            # Step 2: If no user token or user not logged in, use client credentials flow
            # Check if we already have a valid client credentials token
            client_token_expiry = session.get('client_token_expiry', 0)
            
            if 'access_token' in session and session.get('token_source') == 'client_credentials' and client_token_expiry > datetime.now().timestamp():
                app.logger.debug("Using existing client credentials token")
                return
                
            # Get client credentials from config
            client_id = app.config['SPOTIFY_CLIENT_ID']
            client_secret = app.config['SPOTIFY_CLIENT_SECRET']
            
            if client_id and client_secret:
                app.logger.debug("Getting new token via client credentials flow")
                
                # Encode client credentials
                auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
                
                # Prepare headers and payload
                headers = {
                    'Authorization': f'Basic {auth_header}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                data = {
                    'grant_type': 'client_credentials'
                }
                
                try:
                    # Make the POST request
                    response = requests.post('https://accounts.spotify.com/api/token', headers=headers, data=data)
                    response.raise_for_status()
                    
                    token_data = response.json()
                    
                    if 'access_token' in token_data:
                        # Store the token in session
                        session['access_token'] = token_data['access_token']
                        session['token_source'] = 'client_credentials'
                        
                        # Calculate and store expiry time (typically 1 hour from now)
                        expires_in = token_data.get('expires_in', 3600)  # Default to 1 hour
                        expiry_timestamp = datetime.now().timestamp() + expires_in
                        session['client_token_expiry'] = expiry_timestamp
                        
                        app.logger.debug("Successfully obtained client credentials token")
                        return
                    else:
                        app.logger.warning("No access token in client credentials response")
                        
                except Exception as e:
                    app.logger.error(f"Error getting client credentials token: {str(e)}")
        
        except Exception as e:
            app.logger.error(f"Error in ensure_spotify_token: {str(e)}")
            pass  # Continue without a token if all methods fail

    # Register blueprints
    from musicround.routes.core import core_bp
    from musicround.routes.users import users_bp
    from musicround.routes.import_songs import import_songs_bp
    from musicround.routes.rounds import rounds_bp
    from musicround.routes.generate import generate_bp
    from musicround.routes.api import api_bp
    from musicround.routes.import_routes import import_bp
    from musicround.routes.process import process_bp
    from musicround.routes.deezer_routes import deezer_bp
    from musicround.routes.db_admin import db_admin_bp, init_admin
    from musicround.routes.auth import auth_bp
    
    app.register_blueprint(core_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(import_songs_bp)
    app.register_blueprint(rounds_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(process_bp)
    app.register_blueprint(deezer_bp)
    app.register_blueprint(db_admin_bp)
    app.register_blueprint(auth_bp)
    
    # Initialize the admin interface
    init_admin(app)
    
    # Register error handlers
    from musicround.errors import register_error_handlers
    register_error_handlers(app)
    
    # Try to create database tables if they don't exist
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created successfully during app initialization")
            
            # Run migrations after tables are created
            run_migrations()
        except Exception as e:
            logger.error(f"Error creating database tables during app initialization: {e}")
    
    # Return the app
    return app

