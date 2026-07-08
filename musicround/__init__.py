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
from musicround.helpers.database_config import (
    bool_from_config,
    database_backend,
    database_uri_from_postgres_env,
    database_summary,
    managed_database_requirement_error,
)
from musicround.version import VERSION_INFO, get_version_str
from datetime import datetime
from musicround.helpers.auth_helpers import oauth # Import the oauth object
from musicround.helpers.logging_utils import oauth_token_log_summary

# Initialize SQLAlchemy
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
DEFAULT_DATABASE_DIR = '/data'


def _default_database_dir(app):
    return os.environ.get('DATA_DIR') or app.config.get('DATA_DIR') or DEFAULT_DATABASE_DIR


def _default_database_path(app):
    return os.path.join(_default_database_dir(app), 'song_data.db')


def _configure_database_uri(app):
    """Use an explicit database URI when configured, otherwise fall back to SQLite."""
    require_managed = bool_from_config(app.config.get('DATABASE_REQUIRE_MANAGED'))
    configured_uri = os.environ.get('SQLALCHEMY_DATABASE_URI') or app.config.get(
        'SQLALCHEMY_DATABASE_URI'
    )
    if not configured_uri:
        try:
            configured_uri = database_uri_from_postgres_env(os.environ)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    if configured_uri:
        managed_error = managed_database_requirement_error(configured_uri, require_managed)
        if managed_error:
            raise RuntimeError(managed_error)
        app.config['SQLALCHEMY_DATABASE_URI'] = configured_uri
        app.config['DATABASE_BACKEND'] = database_backend(configured_uri)
        app.config['DATABASE_URI_REDACTED'] = database_summary(configured_uri)['redacted_uri']
        return

    managed_error = managed_database_requirement_error(configured_uri, require_managed)
    if managed_error:
        raise RuntimeError(managed_error)

    fallback_database_dir = _default_database_dir(app)
    fallback_database_path = _default_database_path(app)
    if not os.path.exists(fallback_database_dir):
        os.makedirs(fallback_database_dir, exist_ok=True)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{fallback_database_path}'
    app.config['DATABASE_BACKEND'] = 'sqlite'
    app.config['DATABASE_URI_REDACTED'] = 'sqlite:///[local-file]'
    app.logger.warning(
        "SQLALCHEMY_DATABASE_URI is not configured; using local SQLite fallback at %s",
        fallback_database_path,
    )


def _import_workers_enabled(app):
    """Return whether in-process import workers should start for this app."""
    configured = app.config.get('IMPORT_WORKERS_ENABLED')
    if configured is None:
        configured = os.environ.get('IMPORT_WORKERS_ENABLED', 'false')
    if isinstance(configured, bool):
        return configured
    return str(configured).lower() not in ('0', 'false', 'no', 'off', '')


def _spotify_authlib_token_from_user(user):
    """Build Authlib's token dict from the raw Spotify columns on User."""
    access_token = user.spotify_token
    legacy_token = None
    if access_token:
        try:
            parsed = json.loads(access_token)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            legacy_token = parsed
            access_token = parsed.get('access_token')

    if not access_token:
        return None

    token = {
        'access_token': access_token,
        'token_type': 'Bearer',
    }
    refresh_token = user.spotify_refresh_token or (legacy_token or {}).get('refresh_token')
    if refresh_token:
        token['refresh_token'] = refresh_token

    expiry = user.spotify_token_expiry
    legacy_expires_at = (legacy_token or {}).get('expires_at')
    if expiry:
        token['expires_at'] = int(expiry.timestamp())
    elif legacy_expires_at:
        try:
            token['expires_at'] = int(float(legacy_expires_at))
        except (TypeError, ValueError):
            pass

    return token


def _store_spotify_authlib_token(user, token):
    """Persist an Authlib Spotify token using the User model's raw-token contract."""
    if not token:
        return

    access_token = token.get('access_token')
    if access_token:
        user.spotify_token = access_token

    refresh_token = token.get('refresh_token')
    if refresh_token:
        user.spotify_refresh_token = refresh_token

    expires_at = token.get('expires_at')
    if expires_at is not None:
        try:
            user.spotify_token_expiry = datetime.fromtimestamp(int(float(expires_at)))
        except (TypeError, ValueError):
            pass
    elif token.get('expires_in') is not None:
        try:
            user.spotify_token_expiry = datetime.fromtimestamp(
                int(datetime.utcnow().timestamp()) + int(float(token['expires_in']))
            )
        except (TypeError, ValueError):
            pass


def _install_security_headers(app):
    """Install conservative response headers for production deployments."""
    if not app.config.get('SECURITY_HEADERS_ENABLED', True):
        return

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        frame_options = app.config.get('SECURITY_FRAME_OPTIONS')
        if frame_options:
            response.headers.setdefault('X-Frame-Options', str(frame_options))
        referrer_policy = app.config.get('SECURITY_REFERRER_POLICY')
        if referrer_policy:
            response.headers.setdefault('Referrer-Policy', str(referrer_policy))
        permissions_policy = app.config.get('SECURITY_PERMISSIONS_POLICY')
        if permissions_policy:
            response.headers.setdefault('Permissions-Policy', str(permissions_policy))
        if app.config.get('USE_HTTPS') and app.config.get('SECURITY_HSTS_ENABLED', True):
            max_age = int(app.config.get('SECURITY_HSTS_MAX_AGE') or 31536000)
            hsts_value = f'max-age={max(0, max_age)}'
            if app.config.get('SECURITY_HSTS_INCLUDE_SUBDOMAINS'):
                hsts_value += '; includeSubDomains'
            response.headers.setdefault('Strict-Transport-Security', hsts_value)
        return response


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
    
    # Configure the app
    app.config.from_object(Config)
    
    # Set preferred URL scheme for reverse proxy support
    if app.config.get('USE_HTTPS'):
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        # Apply the HTTPS middleware when USE_HTTPS is True
        app.wsgi_app = ForceHTTPSMiddleware(app.wsgi_app)
        app.logger.info("Applying ForceHTTPSMiddleware - all URLs will use HTTPS scheme regardless of headers")

    _install_security_headers(app)
    
    _configure_database_uri(app)
    
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
                token = _spotify_authlib_token_from_user(current_user)
                app.logger.debug(
                    "_app_fetch_token for Spotify (user %s): Token metadata: %s",
                    current_user.id,
                    oauth_token_log_summary(token),
                )
                return token
        app.logger.debug(f"_app_fetch_token: User not authenticated or service not matched for '{name}'.")
        return None

    def _app_update_token(name, token, refresh_token=None, access_token=None):
        app.logger.debug(f"_app_update_token: Called for service: {name}, user: {current_user.id if current_user.is_authenticated else 'Unauthenticated'}")
        if name == 'spotify':
            if current_user.is_authenticated:
                app.logger.info(f"_app_update_token for Spotify (user {current_user.id}): Received new token data to update. Keys: {list(token.keys()) if token else 'None'}")
                app.logger.debug(
                    "_app_update_token for Spotify (user %s): New token metadata: %s",
                    current_user.id,
                    oauth_token_log_summary(token),
                )
                _store_spotify_authlib_token(current_user, token)
                
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

    # Initialize import queue and background workers after tables/migrations exist.
    from musicround.helpers.import_queue import ImportQueue, ImportWorker
    try:
        worker_count = max(1, int(os.environ.get('IMPORT_WORKER_COUNT', '2')))
    except ValueError:
        logger.warning("Invalid IMPORT_WORKER_COUNT value; defaulting to 2")
        worker_count = 2

    import_queue = ImportQueue()
    app.config['import_queue'] = import_queue

    workers_enabled = _import_workers_enabled(app)
    app.config['IMPORT_WORKERS_ENABLED_RESOLVED'] = workers_enabled
    app.config['IMPORT_WORKER_COUNT_RESOLVED'] = worker_count

    workers = []
    if workers_enabled:
        with app.app_context():
            try:
                abandoned_count = import_queue.mark_abandoned_processing_records()
                if abandoned_count:
                    logger.warning(
                        "Marked %s abandoned import job(s) as failed after restart",
                        abandoned_count,
                    )
                pending_count = import_queue.enqueue_pending_records()
                if pending_count:
                    logger.info("Queued %s pending import job(s) from the database", pending_count)
            except Exception as e:
                logger.error(f"Error loading pending import jobs: {e}")

        workers = [
            ImportWorker(app, import_queue, worker_id=f"import-worker-{index + 1}")
            for index in range(worker_count)
        ]
        for worker in workers:
            worker.start()
    app.config['import_workers'] = workers
    if workers_enabled:
        logger.info("Started %s import worker(s)", len(workers))
    else:
        logger.info("Import workers disabled; set IMPORT_WORKERS_ENABLED=true to start them")
    
    # Return the app
    return app
