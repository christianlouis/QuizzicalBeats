import os
import logging
import importlib.util
import json
from flask import Flask, session, redirect, url_for, request
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from importlib import import_module
from musicround.config import Config
from musicround.version import VERSION_INFO, get_version_str
from datetime import datetime
from musicround.helpers.auth_helpers import oauth # Import the oauth object

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
    
    # Create custom HTTPS middleware (will be applied below if USE_HTTPS is True)
    class ForceHTTPSMiddleware:
        """Middleware to force HTTPS scheme regardless of request headers"""
        def __init__(self, app):
            self.app = app
            
        def __call__(self, environ, start_response):
            # Force the wsgi.url_scheme to be https
            environ['wsgi.url_scheme'] = 'https'
            # Also override X-Forwarded-Proto if present
            environ['HTTP_X_FORWARDED_PROTO'] = 'https'
            return self.app(environ, start_response)
    
    # Create data directory if it doesn't exist
    data_dir = '/data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
      # Set the database file path in the data directory
    db_path = os.path.join(data_dir, 'song_data.db')

    # Configure the app
    app.config.from_object(Config)
    
    # Set preferred URL scheme for reverse proxy support
    if app.config.get('USE_HTTPS'):
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        # Apply the HTTPS middleware when USE_HTTPS is True
        app.wsgi_app = ForceHTTPSMiddleware(app.wsgi_app)
        app.logger.info("Applying ForceHTTPSMiddleware - all URLs will use HTTPS scheme regardless of headers")
    
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
    
    # Define token handling functions within create_app
    def _app_fetch_token(name):
        app.logger.debug(f"_app_fetch_token: Called for service '{name}', user: {current_user.id if current_user.is_authenticated else 'Unauthenticated'}")
        if current_user.is_authenticated:
            if name == 'spotify':
                token_str = current_user.spotify_token
                app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Raw token string from DB: {token_str[:150] if token_str else 'None'}...")
                if token_str:
                    try:
                        token = json.loads(token_str)
                        app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Token after json.loads: {{'access_token': 'ACCESS_TOKEN_REDACTED', 'refresh_token': '{'REFRESH_TOKEN_REDACTED' if token.get('refresh_token') else 'None'}', 'expires_at': {token.get('expires_at')}, 'expires_in': {token.get('expires_in')}, 'scope': {token.get('scope')}, 'token_type': '{token.get('token_type')}'}}")

                        if 'refresh_token' not in token or not token.get('refresh_token'):
                            if hasattr(current_user, 'spotify_refresh_token') and current_user.spotify_refresh_token:
                                token['refresh_token'] = current_user.spotify_refresh_token
                                app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Added refresh_token from current_user.spotify_refresh_token.")
                            else:
                                app.logger.warning(f"_app_fetch_token for Spotify (user {current_user.id}): refresh_token missing in JSON and not found in current_user.spotify_refresh_token.")
                        
                        current_time = int(datetime.utcnow().timestamp())
                        if 'expires_at' in token:
                            if not isinstance(token['expires_at'], int):
                                try:
                                    token['expires_at'] = int(float(token['expires_at']))
                                    app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Converted existing expires_at to int: {token['expires_at']}")
                                except (ValueError, TypeError):
                                    app.logger.warning(f"_app_fetch_token for Spotify (user {current_user.id}): Could not convert existing expires_at '{token['expires_at']}' to int. Recalculating if possible.")
                                    if 'expires_in' in token and isinstance(token['expires_in'], (int, float)):
                                        token['expires_at'] = current_time + int(token['expires_in']) - 30
                                        app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Recalculated expires_at from expires_in: {token['expires_at']}")
                                    else:
                                        app.logger.error(f"_app_fetch_token for Spotify (user {current_user.id}): Cannot determine expires_at. Original problematic value: {token['expires_at']}")
                        elif 'expires_in' in token and isinstance(token['expires_in'], (int, float)):
                            token['expires_at'] = current_time + int(token['expires_in']) - 30
                            app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Calculated expires_at from expires_in: {token['expires_at']}")
                        elif hasattr(current_user, 'spotify_token_expires_at') and current_user.spotify_token_expires_at:
                            token['expires_at'] = int(current_user.spotify_token_expires_at.timestamp())
                            app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Used expires_at from current_user.spotify_token_expires_at: {token['expires_at']}")
                        else:
                            app.logger.warning(f"_app_fetch_token for Spotify (user {current_user.id}): expires_at missing and cannot be calculated.")

                        if 'token_type' not in token or not token.get('token_type'):
                            token['token_type'] = 'Bearer'
                            app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Set token_type to Bearer.")
                        
                        if 'expires_in' in token: 
                            del token['expires_in']

                        app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): Final token prepared for Authlib: {{'access_token': 'ACCESS_TOKEN_REDACTED', 'refresh_token': '{'REFRESH_TOKEN_REDACTED' if token.get('refresh_token') else 'None'}', 'expires_at': {token.get('expires_at')}, 'token_type': '{token.get('token_type')}', 'scope': {token.get('scope')}}}")
                        return token
                    except json.JSONDecodeError:
                        app.logger.error(f"_app_fetch_token for Spotify (user {current_user.id}): Failed to decode token JSON: {token_str[:100]}...")
                        return None
                    except Exception as e:
                        app.logger.error(f"_app_fetch_token for Spotify (user {current_user.id}): Error processing token: {str(e)}", exc_info=True)
                        return None
                else:
                    app.logger.debug(f"_app_fetch_token for Spotify (user {current_user.id}): No token string found in DB.")
                    return None
        app.logger.debug(f"_app_fetch_token: User not authenticated or service not matched for '{name}'.")
        return None

    def _app_update_token(name, token, refresh_token=None, access_token=None):
        app.logger.debug(f"_app_update_token: Called for service: {name}, user: {current_user.id if current_user.is_authenticated else 'Unauthenticated'}")
        if name == 'spotify':
            if current_user.is_authenticated:
                app.logger.info(f"_app_update_token for Spotify (user {current_user.id}): Received new token data to update. Keys: {list(token.keys()) if token else 'None'}")
                app.logger.debug(f"_app_update_token for Spotify (user {current_user.id}): Full new token: {{'access_token': 'ACCESS_TOKEN_REDACTED', 'refresh_token': '{'REFRESH_TOKEN_REDACTED' if token.get('refresh_token') else 'None'}', 'expires_at': {token.get('expires_at')}, 'token_type': '{token.get('token_type')}', 'scope': {token.get('scope')}}}")
                
                current_user.spotify_token = json.dumps(token)
                
                if 'expires_at' in token and token['expires_at'] is not None and hasattr(current_user, 'spotify_token_expires_at'):
                    try:
                        current_user.spotify_token_expires_at = datetime.fromtimestamp(int(token['expires_at']))
                        app.logger.debug(f"_app_update_token for Spotify (user {current_user.id}): Updated spotify_token_expires_at to {current_user.spotify_token_expires_at}")
                    except (TypeError, ValueError) as e:
                        app.logger.warning(f"_app_update_token for Spotify (user {current_user.id}): Could not update spotify_token_expires_at from token's expires_at ('{token['expires_at']}'): {str(e)}")

                if 'refresh_token' in token and token['refresh_token'] and hasattr(current_user, 'spotify_refresh_token'):
                    current_user.spotify_refresh_token = token['refresh_token']
                    app.logger.debug(f"_app_update_token for Spotify (user {current_user.id}): Updated spotify_refresh_token.")
                
                try:
                    db.session.commit()
                    app.logger.info(f"_app_update_token for Spotify (user {current_user.id}): Token successfully updated and committed to DB.")
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"_app_update_token for Spotify (user {current_user.id}): Error committing token to DB: {str(e)}", exc_info=True)
            else:
                app.logger.warning(f"_app_update_token for Spotify: Attempted to update token for unauthenticated user.")
        # Add similar blocks for other services if needed

    # Initialize OAuth providers (Google, Authentik, Spotify via Authlib)
    from musicround.helpers.auth_helpers import init_oauth
    init_oauth(app) # This will use the imported oauth object

    # Manually register token handling functions
    app.logger.info(f"Attempting to manually register token functions. oauth object id: {id(oauth)}")
    if hasattr(oauth, 'tokengetter') and callable(oauth.tokengetter):
        oauth.tokengetter(_app_fetch_token)
        app.logger.info("SUCCESS: Manually registered _app_fetch_token using oauth.tokengetter().")
    else:
        app.logger.error("FAILURE: oauth.tokengetter method not found or not callable.")
        # Fallback for extreme cases - not recommended for production
        if isinstance(oauth, object) and hasattr(oauth, '_fetch_token_funcs') and isinstance(oauth._fetch_token_funcs, dict): # Basic check
             oauth._fetch_token_funcs['_app_fetch_token'] = _app_fetch_token
             app.logger.warning("MANUAL HACK: Injected _app_fetch_token into oauth._fetch_token_funcs.")
        else:
             app.logger.error("CRITICAL FAILURE: Cannot register fetch token function via method or hack.")


    if hasattr(oauth, 'tokenupdater') and callable(oauth.tokenupdater):
        oauth.tokenupdater(_app_update_token)
        app.logger.info("SUCCESS: Manually registered _app_update_token using oauth.tokenupdater().")
    else:
        app.logger.error("FAILURE: oauth.tokenupdater method not found or not callable.")
        if isinstance(oauth, object) and hasattr(oauth, '_update_token_funcs') and isinstance(oauth._update_token_funcs, dict): # Basic check
             oauth._update_token_funcs['_app_update_token'] = _app_update_token
             app.logger.warning("MANUAL HACK: Injected _app_update_token into oauth._update_token_funcs.")
        else:
            app.logger.error("CRITICAL FAILURE: Cannot register update token function via method or hack.")
            
    # Initialize Deezer client - import inside the function to avoid circular dependency
    from musicround.deezer_client import DeezerClient
    app.config['deezer'] = DeezerClient()
    
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
    from musicround.routes.oauth_debug import oauth_debug_bp
    
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
    app.register_blueprint(oauth_debug_bp)
    
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

