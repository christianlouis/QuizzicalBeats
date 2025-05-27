from datetime import datetime
from musicround import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

# User-Role association table for many-to-many relationship
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), primary_key=True)
)

class Role(db.Model):
    """
    Role model for user permissions
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    
    def __repr__(self):
        return f"Role(id={self.id}, name='{self.name}')"


class UserPreferences(db.Model):
    """
    User preferences model for storing user-specific settings
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    default_tts_service = db.Column(db.String(32), default='polly')
    enable_intro = db.Column(db.Boolean, default=True)
    theme = db.Column(db.String(16), default='light')
    user = db.relationship('User', back_populates='preferences')


class User(db.Model, UserMixin):
    """
    User model for authentication and user management
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), index=True, unique=True, nullable=False)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # Now nullable for OAuth-only users
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Token for password reset, email verification, etc.
    reset_token = db.Column(db.String(100), index=True, unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    
    # Authentication provider info
    auth_provider = db.Column(db.String(20), default='local')  # 'local', 'google', 'authentik'
    
    # OAuth provider info - Spotify
    spotify_id = db.Column(db.String(100), index=True, unique=True, nullable=True) # Spotify user ID
    spotify_token = db.Column(db.Text)         # Store Spotify access token 
    spotify_refresh_token = db.Column(db.Text)  # Store Spotify refresh token
    spotify_token_expiry = db.Column(db.DateTime)
    
    # OAuth provider info - Google
    google_id = db.Column(db.String(100))      # Google user ID
    google_token = db.Column(db.Text)          # Store Google access token
    google_refresh_token = db.Column(db.Text)   # Store Google refresh token
    
    # OAuth provider info - Authentik
    authentik_id = db.Column(db.String(100))    # Authentik user ID
    authentik_token = db.Column(db.Text)        # Store Authentik access token
    authentik_refresh_token = db.Column(db.Text) # Store Authentik refresh token
    
    # OAuth provider info - Dropbox
    dropbox_id = db.Column(db.String(100))      # Dropbox user ID
    dropbox_token = db.Column(db.Text)          # Store Dropbox access token
    dropbox_refresh_token = db.Column(db.Text)  # Store Dropbox refresh token
    dropbox_token_expiry = db.Column(db.DateTime) # Dropbox token expiration
    dropbox_export_path = db.Column(db.String(255), default='/QuizzicalBeats')  # User's preferred Dropbox export folder
    
    # User preferences
    intro_mp3 = db.Column(db.String(255))      # Custom intro MP3 path
    outro_mp3 = db.Column(db.String(255))      # Custom outro MP3 path
    replay_mp3 = db.Column(db.String(255))     # Custom replay MP3 path
    
    # Relationships
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    preferences = db.relationship('UserPreferences', uselist=False, back_populates='user')
    
    @property
    def password(self):
        """Password getter should raise an error"""
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        """Hash and store the password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if provided password matches the hash"""
        return check_password_hash(self.password_hash, password)
        
    def set_token(self):
        """Generate a unique token for the user"""
        self.reset_token = str(uuid.uuid4())
        return self.reset_token
        
    def has_role(self, role_name):
        """Check if user has a specific role"""
        return any(role.name == role_name for role in self.roles)

    def is_admin(self):
        """Check if user is an admin"""
        return self.has_role('admin')
        
    def __repr__(self):
        return f"User(id={self.id}, username='{self.username}', email='{self.email}')"


class Tag(db.Model):
    """
    Tag model for storing song tags
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Define relationship to songs via SongTag
    songs = db.relationship('Song', secondary='song_tag', back_populates='tags')
    
    def __repr__(self):
        return f"Tag(id={self.id}, name='{self.name}')"


class SongTag(db.Model):
    """
    Association table for Song-Tag many-to-many relationship
    """
    __tablename__ = 'song_tag'
    
    song_id = db.Column(db.Integer, db.ForeignKey('song.id', ondelete='CASCADE'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"SongTag(song_id={self.song_id}, tag_id={self.tag_id})"


class Song(db.Model):
    """
    Song model for storing song details from Spotify and Deezer
    """
    id = db.Column(db.Integer, primary_key=True)
    spotify_id = db.Column(db.String(100), unique=True, nullable=True)
    deezer_id = db.Column(db.Integer, unique=True, nullable=True)
    isrc = db.Column(db.String(20), index=True, nullable=True)  # Add ISRC code
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    album_name = db.Column(db.String(200), nullable=True)  # Album name
    genre = db.Column(db.String(100))
    year = db.Column(db.Integer)
    preview_url = db.Column(db.String(500))  # Increased length for longer URLs - primary preview URL
    cover_url = db.Column(db.String(500))    # Increased length - primary cover URL
    spotify_preview_url = db.Column(db.String(500), nullable=True)  # Spotify-specific preview
    deezer_preview_url = db.Column(db.String(500), nullable=True)   # Deezer-specific preview
    apple_preview_url = db.Column(db.String(500), nullable=True)    # Apple Music preview
    youtube_preview_url = db.Column(db.String(500), nullable=True)  # YouTube preview
    spotify_cover_url = db.Column(db.String(500), nullable=True)    # Spotify cover
    deezer_cover_url = db.Column(db.String(500), nullable=True)     # Deezer cover
    apple_cover_url = db.Column(db.String(500), nullable=True)      # Apple Music cover
    popularity = db.Column(db.Integer)
    used_count = db.Column(db.Integer, default=0)
    source = db.Column(db.String(20), default='spotify')  # 'spotify', 'deezer', or 'acrcloud'
    import_date = db.Column(db.DateTime, default=datetime.utcnow)  # Add import date
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used = db.Column(db.DateTime)
    metadata_sources = db.Column(db.String(500), nullable=True)  # Comma-separated list of metadata sources
    
    # Spotify Audio Features
    acousticness = db.Column(db.Float, nullable=True)  # Confidence of track being acoustic (0.0 to 1.0)
    danceability = db.Column(db.Float, nullable=True)  # How suitable for dancing (0.0 to 1.0)
    energy = db.Column(db.Float, nullable=True)        # Intensity and activity measure (0.0 to 1.0)
    instrumentalness = db.Column(db.Float, nullable=True)  # Predicts if track has no vocals (0.0 to 1.0) 
    key = db.Column(db.Integer, nullable=True)         # Key of the track (standard Pitch Class notation, -1 = no key)
    liveness = db.Column(db.Float, nullable=True)      # Presence of audience in recording (0.0 to 1.0)
    loudness = db.Column(db.Float, nullable=True)      # Overall loudness in dB (-60 to 0 typically)
    mode = db.Column(db.Integer, nullable=True)        # Modality - major (1) or minor (0)
    speechiness = db.Column(db.Float, nullable=True)   # Presence of spoken words (0.0 to 1.0)
    tempo = db.Column(db.Float, nullable=True)         # Estimated tempo in BPM
    time_signature = db.Column(db.Integer, nullable=True)  # Estimated time signature (3 to 7 representing 3/4 to 7/4)
    valence = db.Column(db.Float, nullable=True)       # Musical positiveness (0.0 to 1.0)
    duration_ms = db.Column(db.Integer, nullable=True) # Duration of track in milliseconds
    analysis_url = db.Column(db.String(500), nullable=True)  # URL to access full audio analysis
    
    # Additional properties as JSON strings
    additional_data = db.Column(db.Text, nullable=True)  # Store additional data as JSON
    
    # Relationship with tags
    tags = db.relationship('Tag', secondary='song_tag', back_populates='songs')

    def __repr__(self):
        return (
            f"Song('{self.id}', '{self.title}', '{self.artist}', "
            f"'{self.genre}', '{self.year}', source='{self.source}', "
            f"isrc='{self.isrc}', spotify_id='{self.spotify_id}', deezer_id='{self.deezer_id}')"
        )
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'artist': self.artist,
            'album_name': self.album_name,
            'cover_url': self.cover_url,
            'preview_url': self.preview_url,
            'spotify_id': self.spotify_id,
            'deezer_id': self.deezer_id,
            'isrc': self.isrc,
            'year': self.year,
            'genre': self.genre,
            'popularity': self.popularity,
            'used_count': self.used_count,
            'last_used': self.last_used.strftime('%Y-%m-%d %H:%M:%S') if self.last_used else None,
            'metadata_sources': self.metadata_sources,
            'tags': [{'id': tag.id, 'name': tag.name} for tag in self.tags],
            # Include audio features in the dictionary
            'acousticness': self.acousticness,
            'danceability': self.danceability,
            'energy': self.energy,
            'instrumentalness': self.instrumentalness,
            'key': self.key,
            'liveness': self.liveness,
            'loudness': self.loudness,
            'mode': self.mode,
            'speechiness': self.speechiness,
            'tempo': self.tempo,
            'time_signature': self.time_signature,
            'valence': self.valence,
            'duration_ms': self.duration_ms
        }


class Round(db.Model):
    """
    Round model for storing quiz rounds and their associated songs
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=True)  # Optional name for the round
    round_type = db.Column(db.String(50), nullable=False)
    round_criteria_used = db.Column(db.String(500), nullable=False)
    songs = db.Column(db.Text, nullable=False)  # JSON string of song IDs in order
    genre = db.Column(db.String(100))
    decade = db.Column(db.String(10))
    tag = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    mp3_generated = db.Column(db.Boolean, default=False)  # Track if MP3 has been generated
    pdf_generated = db.Column(db.Boolean, default=False)  # Track if PDF has been generated
    last_generated_at = db.Column(db.DateTime, nullable=True)  # When files were last generated

    def __repr__(self):
        return (
            f"Round('{self.name or self.id}', '{self.round_type}', '{self.round_criteria_used}', "
            f"'{self.songs}', '{self.created_at}')"
        )

    @property
    def song_list(self):
        """
        Returns a list of Song objects associated with this round
        """
        song_ids = self.songs.split(',')
        return Song.query.filter(Song.id.in_(song_ids)).all()
        
    def reset_generated_status(self):
        """
        Reset the MP3 and PDF generated flags when a round is modified
        """
        self.mp3_generated = False
        self.pdf_generated = False


class RoundExport(db.Model):
    """
    Model to track round exports to various destinations (Dropbox, email, etc.)
    """
    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    export_type = db.Column(db.String(20), nullable=False)  # 'dropbox', 'email', etc.
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    destination = db.Column(db.String(500), nullable=True)  # Path, email address, etc.
    include_mp3s = db.Column(db.Boolean, default=False)  # Whether MP3s were included
    status = db.Column(db.String(20), default='success')  # 'success', 'failed'
    error_message = db.Column(db.Text, nullable=True)  # Error details if failed
    
    # Relationships
    round = db.relationship('Round', backref=db.backref('exports', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('exports', lazy='dynamic'))
    
    def __repr__(self):
        return f"RoundExport(id={self.id}, round_id={self.round_id}, type='{self.export_type}', timestamp='{self.timestamp}')"


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            setting = SystemSetting(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value
        db.session.commit()

    @staticmethod
    def all_settings():
        return {s.key: s.value for s in SystemSetting.query.all()}

