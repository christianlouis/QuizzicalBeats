# Architecture Overview

This document provides a comprehensive overview of the Quizzical Beats architecture, designed to help developers understand the system structure and components.

## Application Structure

Quizzical Beats follows a modular Flask application structure:

```
musicround/
├── __init__.py         # Application factory
├── config.py           # Configuration management
├── models.py           # Database models
├── version.py          # Version information
├── errors.py           # Error handling
├── deezer_client.py    # Deezer API integration
├── helpers/            # Utility modules
│   ├── __init__.py
│   ├── auth_helpers.py     # Authentication utilities
│   ├── backup_helper.py    # Backup management
│   ├── dropbox_helper.py   # Dropbox integration
│   ├── email_helper.py     # Email functionality
│   ├── import_helper.py    # Song import utilities
│   ├── metadata.py         # Song metadata processing
│   ├── spotify_direct.py   # Spotify API client
│   └── utils.py            # General utilities
├── mp3/                # Audio file storage
├── routes/             # Route definitions
│   ├── __init__.py
│   ├── api.py          # API endpoints
│   ├── auth.py         # Authentication routes
│   ├── core.py         # Core application routes
│   ├── db_admin.py     # Database administration
│   ├── deezer_routes.py # Deezer integration
│   ├── generate.py     # Content generation
│   ├── import.py       # Generic import functionality
│   ├── import_routes.py # Import interface routes
│   ├── import_songs.py # Song import functionality
│   ├── process.py      # Audio processing
│   ├── rounds.py       # Quiz round management
│   └── users.py        # User account management
├── static/             # Static files (CSS, JS, images)
└── templates/          # Jinja2 HTML templates
    ├── admin/          # Admin interface templates
    ├── auth/           # Authentication templates
    └── ... (other template categories)
```

## Key Components

### Application Factory

The application is initialized using a factory pattern in `__init__.py`. This allows for flexible configuration and testing:

```python
def create_app():
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    
    # Register blueprints
    from musicround.routes import core, auth, rounds, users, import_songs, import_routes, generate, process, api, deezer_routes, db_admin
    
    app.register_blueprint(core.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(rounds.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(import_songs.bp)
    app.register_blueprint(import_routes.bp)
    app.register_blueprint(generate.bp)
    app.register_blueprint(process.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(deezer_routes.bp)
    app.register_blueprint(db_admin.bp)
    
    return app
```

### Configuration Management

Configuration is handled in `config.py` using environment variables loaded from a `.env` file:

```python
class Config:
    # Core configuration
    DEBUG = os.getenv("DEBUG", "True") == "True"
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-please-change')
    
    # API keys for various services
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
    MEANINGCLOUD_API_KEY = os.getenv("MEANINGCLOUD_API_KEY")
    LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///data/song_data.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # OAuth provider configurations
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    # ... other configuration
```

### Database Models

The data model is defined in `models.py` using SQLAlchemy ORM:

```python
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    rounds = db.relationship('Round', backref='author', lazy=True)
    # OAuth tokens and preferences
    
class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    spotify_id = db.Column(db.String(50), nullable=True)
    preview_url = db.Column(db.String(255), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    # Audio features and metadata
    
class Round(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    songs = db.relationship('RoundSong', backref='round', lazy=True, cascade="all, delete-orphan")
    # Round configuration and settings
```

### Authentication System

The authentication system supports:

1. **Local Authentication**: Username/password authentication
2. **OAuth Providers**:
   - Spotify
   - Google
   - Authentik (OpenID Connect)
3. **Role-Based Access Control**: Admin vs. regular users

OAuth integration is handled through dedicated helper functions in `auth_helpers.py`:

```python
def get_spotify_oauth():
    # Configure OAuth for Spotify
    
def get_google_oauth():
    # Configure OAuth for Google
    
def get_authentik_oauth():
    # Configure OAuth for Authentik
```

### External Integrations

#### Spotify Integration

The `spotify_direct.py` module provides:
- Authentication with Spotify API
- Playlist import functionality
- Track search and metadata retrieval
- Audio feature access

#### Dropbox Integration

The `dropbox_helper.py` module enables:
- OAuth authentication with Dropbox
- File export to Dropbox
- Folder management in Dropbox
- Shared link generation

#### Deezer Integration

The `deezer_client.py` and related routes provide:
- Authentication with Deezer API
- Playlist import
- Track search and preview access

#### OpenAI Integration

AI-powered features use the OpenAI API for:
- Round generation suggestions
- Lyric analysis
- Song categorization

### Backup System

The backup system in `backup_helper.py` provides:

```python
def create_backup(include_mp3=True, include_config=True, backup_name=None):
    # Create ZIP archive with database and optional files
    
def restore_from_backup(backup_file, force=False):
    # Restore system from backup archive
    
def list_backups():
    # List available backups with metadata
    
def verify_backup(backup_path):
    # Check backup integrity
```

Features include:
- Database dumps using SQLite backup API
- MP3 file inclusion in backups
- Configuration file backup
- Scheduled backups
- Retention policy management

## Request Flow

1. Request arrives at the Flask application
2. Blueprint routes direct to the appropriate view function
3. Authentication middleware checks for required permissions
4. View function processes the request:
   - Database queries via SQLAlchemy models
   - External API calls where needed
   - Business logic processing
5. Response is rendered using Jinja2 templates
6. Rendered HTML is returned to the client

### Example Routes

```python
@bp.route('/rounds/<int:round_id>')
@login_required
def view_round(round_id):
    round = Round.query.get_or_404(round_id)
    # Check permissions
    # Process data
    return render_template('rounds/view.html', round=round)

@bp.route('/rounds/<int:round_id>/export-to-dropbox', methods=['POST'])
@login_required
def export_to_dropbox(round_id):
    round = Round.query.get_or_404(round_id)
    # Check permissions
    # Export to Dropbox
    return jsonify({'success': True, 'message': 'Export successful'})
```

## System Health Monitoring

The health monitoring system provides dashboards for:

1. **Database Health**: Connection status, table counts, size
2. **Storage Health**: Directory status, file counts, permissions
3. **External Service Status**: API connectivity checks
4. **Version Information**: Application version, dependencies

## Extension Points

To extend Quizzical Beats, consider these integration points:

1. **New OAuth Providers**: Add provider configuration in `auth_helpers.py`
2. **Additional Export Formats**: Implement in the rounds routes
3. **New Music Data Sources**: Create a new client module similar to `spotify_direct.py` or `deezer_client.py`
4. **Custom Audio Processing**: Extend the functionality in the `process.py` routes
5. **AI Features**: Enhance OpenAI integration for additional content generation

## Technology Stack

- **Backend**: Python 3.8+, Flask 2.x
- **Database**: SQLAlchemy 1.4+ with SQLite/PostgreSQL/MySQL
- **Frontend**: TailwindCSS, Alpine.js, vanilla JavaScript
- **Authentication**: Flask-Login, OAuth integrations
- **APIs**: Spotify, Deezer, Dropbox, OpenAI, DeepL
- **Media Processing**: FFmpeg, MP3 manipulation libraries
- **Testing**: Pytest for unit and integration tests