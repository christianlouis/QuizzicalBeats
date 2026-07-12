from datetime import datetime
from musicround import db
from flask_login import UserMixin
from sqlalchemy.orm import validates
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
    default_language = db.Column(db.String(16), default='de')
    tone = db.Column(db.String(200), default='warm, concise, lightly humorous')
    tts_voice = db.Column(db.String(120), nullable=True)
    email_recipient = db.Column(db.String(120), nullable=True)
    preferred_genres = db.Column(db.Text, nullable=True)
    preferred_decades = db.Column(db.Text, nullable=True)
    banned_artists = db.Column(db.Text, nullable=True)
    banned_songs = db.Column(db.Text, nullable=True)
    repeat_cooldown_weeks = db.Column(db.Integer, default=12, nullable=False)
    timezone = db.Column(db.String(64), default='Europe/Berlin', nullable=False)
    enable_intro = db.Column(db.Boolean, default=True)
    theme = db.Column(db.String(16), default='light')
    import_job_email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    oauth_token_email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    round_blocked_email_notifications = db.Column(db.Boolean, default=True, nullable=False)
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
    email_verification_token = db.Column(db.String(100), index=True, unique=True)
    email_verification_expiry = db.Column(db.DateTime)
    email_verified_at = db.Column(db.DateTime)
    
    # Authentication provider info
    auth_provider = db.Column(db.String(20), default='local')  # 'local', 'google', 'authentik'
    
    # OAuth provider info - Spotify
    spotify_id = db.Column(db.String(100), index=True, unique=True, nullable=True) # Spotify user ID
    spotify_token = db.Column(db.Text)         # Store Spotify access token 
    spotify_refresh_token = db.Column(db.Text)  # Store Spotify refresh token
    spotify_token_expiry = db.Column(db.DateTime)
    
    # OAuth provider info - Google
    google_id = db.Column(db.String(100), unique=True, nullable=True)      # Google user ID
    google_token = db.Column(db.Text)          # Store Google access token
    google_refresh_token = db.Column(db.Text)   # Store Google refresh token
    
    # OAuth provider info - Authentik
    authentik_id = db.Column(db.String(100), unique=True, nullable=True)    # Authentik user ID
    authentik_token = db.Column(db.Text)        # Store Authentik access token
    authentik_refresh_token = db.Column(db.Text) # Store Authentik refresh token
    
    # OAuth provider info - Dropbox
    dropbox_id = db.Column(db.String(100), unique=True, nullable=True)      # Dropbox user ID
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
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
        
    def set_token(self):
        """Generate a unique token for the user"""
        self.reset_token = str(uuid.uuid4())
        return self.reset_token
        
    def has_role(self, role_name):
        """Check if user has a specific role"""
        return any(role.name == role_name for role in self.roles)

    def is_admin_by_role(self):
        """Check if user is an admin via role assignment"""
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
    deezer_id = db.Column(db.BigInteger, unique=True, nullable=True)
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
    source = db.Column(db.String(50), default='spotify')  # e.g. spotify, deezer, acrcloud, curated seed names
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

    __table_args__ = (
        db.Index('idx_song_artist_title', 'artist', 'title'),
        db.Index('idx_song_genre_year', 'genre', 'year'),
        db.Index('idx_song_usage', 'used_count', 'last_used'),
    )
    
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
    songs = db.Column(db.Text, nullable=False)  # Comma-separated song IDs in saved order
    genre = db.Column(db.String(100))
    decade = db.Column(db.String(10))
    tag = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    visibility = db.Column(db.String(20), default='private', nullable=False)
    public_token = db.Column(db.String(64), nullable=True)
    public_token_created_at = db.Column(db.DateTime, nullable=True)
    public_token_expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    mp3_generated = db.Column(db.Boolean, default=False)  # Track if MP3 has been generated
    pdf_generated = db.Column(db.Boolean, default=False)  # Track if PDF has been generated
    last_generated_at = db.Column(db.DateTime, nullable=True)  # When files were last generated
    review_status = db.Column(db.String(20), default='draft', nullable=False)
    review_notes = db.Column(db.Text, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    __table_args__ = (
        db.Index('idx_round_created_at', 'created_at'),
        db.Index('idx_round_generation_status', 'mp3_generated', 'pdf_generated'),
        db.Index('idx_round_owner_created', 'user_id', 'created_at'),
        db.Index('idx_round_public_token', 'public_token', unique=True),
        db.Index('idx_round_review_status', 'review_status', 'approved_at'),
    )

    owner = db.relationship('User', backref=db.backref('rounds', lazy='dynamic'), foreign_keys=[user_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    def __repr__(self):
        return (
            f"Round('{self.name or self.id}', '{self.round_type}', '{self.round_criteria_used}', "
            f"'{self.songs}', '{self.created_at}')"
        )

    @validates('review_status')
    def _validate_review_status(self, key, value):
        allowed_statuses = {'draft', 'reviewed', 'approved', 'blocked', 'rejected', 'sent'}
        if value not in allowed_statuses:
            raise ValueError(f"Invalid review_status: {value!r}")
        return value

    @property
    def song_id_list(self):
        """
        Returns the round's stored song IDs in their saved order.
        """
        song_ids = []
        for token in (self.songs or '').split(','):
            token = token.strip()
            if not token:
                continue
            try:
                song_ids.append(int(token))
            except ValueError:
                continue
        return song_ids

    @property
    def song_list(self):
        """
        Returns a list of Song objects associated with this round
        """
        song_ids = self.song_id_list
        if not song_ids:
            return []
        songs_by_id = {
            song.id: song
            for song in Song.query.filter(Song.id.in_(song_ids)).all()
        }
        return [songs_by_id[song_id] for song_id in song_ids if song_id in songs_by_id]
        
    def reset_generated_status(self):
        """
        Reset the MP3 and PDF generated flags when a round is modified
        """
        self.mp3_generated = False
        self.pdf_generated = False


class RoundShare(db.Model):
    """
    Share grants for quiz rounds between quizmasters.
    """
    __tablename__ = 'round_share'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(20), default='viewer', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('round_id', 'user_id', name='uq_round_share_round_user'),
        db.Index('idx_round_share_user', 'user_id', 'role'),
    )

    round = db.relationship('Round', backref=db.backref('shares', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('shared_rounds', lazy='dynamic'))

    def __repr__(self):
        return f"RoundShare(round_id={self.round_id}, user_id={self.user_id}, role='{self.role}')"


class RoundAccessEvent(db.Model):
    """Audit events for round ownership and sharing changes."""
    __tablename__ = 'round_access_event'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id', ondelete='CASCADE'), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(40), nullable=False)
    role = db.Column(db.String(20), nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index('idx_round_access_event_round_created', 'round_id', 'created_at'),
        db.Index('idx_round_access_event_actor', 'actor_user_id', 'created_at'),
        db.Index('idx_round_access_event_target', 'target_user_id', 'created_at'),
    )

    round = db.relationship('Round', backref=db.backref('access_events', lazy='dynamic'))
    actor = db.relationship('User', foreign_keys=[actor_user_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])

    def __repr__(self) -> str:
        """Return a compact debug representation."""
        return f"RoundAccessEvent(round_id={self.round_id}, action='{self.action}')"


class RoundAudioScript(db.Model):
    """
    Reviewable intro/replay/outro script drafts for a round before TTS generation.
    """
    __tablename__ = 'round_audio_script'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    script_type = db.Column(db.String(20), nullable=False)
    text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='draft', nullable=False)
    tone = db.Column(db.String(200), nullable=True)
    theme = db.Column(db.String(200), nullable=True)
    cue_position = db.Column(db.Integer, nullable=True)
    quiz_date = db.Column(db.DateTime, nullable=True)
    selected = db.Column(db.Boolean, default=False, nullable=False)
    generated_mp3_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_round_audio_script_round_status', 'round_id', 'status', 'script_type'),
        db.Index('idx_round_audio_script_cue', 'round_id', 'script_type', 'cue_position', 'selected'),
        db.Index('idx_round_audio_script_user', 'user_id', 'created_at'),
    )

    round = db.relationship('Round', backref=db.backref('audio_scripts', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('round_audio_scripts', lazy='dynamic'))

    def __repr__(self):
        return (
            f"RoundAudioScript(round_id={self.round_id}, "
            f"type='{self.script_type}', status='{self.status}')"
        )


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
    scheduled_for = db.Column(db.DateTime, nullable=True)
    processed_at = db.Column(db.DateTime, nullable=True)
    subject = db.Column(db.String(500), nullable=True)
    body_text = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index('idx_round_export_schedule', 'status', 'scheduled_for', 'export_type'),
        db.Index('idx_round_export_round_timestamp', 'round_id', 'timestamp'),
    )
    
    # Relationships
    round = db.relationship('Round', backref=db.backref('exports', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('exports', lazy='dynamic'))
    
    def __repr__(self):
        return f"RoundExport(id={self.id}, round_id={self.round_id}, type='{self.export_type}', timestamp='{self.timestamp}')"


class PlannedQuizRound(db.Model):
    """
    Planned quiz dates before a concrete round/export exists.
    """
    __tablename__ = 'planned_quiz_round'

    id = db.Column(db.Integer, primary_key=True)
    quiz_date = db.Column(db.DateTime, nullable=False)
    quizmaster_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    theme = db.Column(db.String(200), nullable=True)
    brief = db.Column(db.Text, nullable=True)
    source_playlist_url = db.Column(db.String(500), nullable=True)
    due_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='planned', nullable=False)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id', ondelete='SET NULL'), nullable=True)
    export_id = db.Column(db.Integer, db.ForeignKey('round_export.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_planned_quiz_round_status_due', 'status', 'due_at', 'quiz_date'),
        db.Index('idx_planned_quiz_round_quizmaster_date', 'quizmaster_id', 'quiz_date'),
    )

    quizmaster = db.relationship('User', backref=db.backref('planned_quiz_rounds', lazy='dynamic'))
    round = db.relationship('Round', backref=db.backref('planned_entries', lazy='dynamic'))
    export = db.relationship('RoundExport', backref=db.backref('planned_entries', lazy='dynamic'))

    @validates('status')
    def _validate_status(self, key, value):
        allowed_statuses = {'planned', 'drafted', 'blocked', 'approved', 'scheduled', 'sent'}
        if value not in allowed_statuses:
            raise ValueError(f"Invalid planned quiz status: {value!r}")
        return value

    def __repr__(self):
        return (
            f"PlannedQuizRound(id={self.id}, quiz_date='{self.quiz_date}', "
            f"status='{self.status}')"
        )


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


class SeedSource(db.Model):
    """
    Curated chart, festival, and editorial sources used to seed the song catalog.
    """
    __tablename__ = 'seed_source'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    source_type = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(100), nullable=True)
    url = db.Column(db.String(500), nullable=True)
    cadence = db.Column(db.String(50), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    priority = db.Column(db.Integer, default=100, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('name', 'provider', name='uq_seed_source_name_provider'),
        db.Index('idx_seed_source_type_active', 'source_type', 'active', 'priority'),
    )

    runs = db.relationship('SeedSourceRun', back_populates='seed_source', lazy='dynamic', cascade='all, delete-orphan')
    candidates = db.relationship(
        'SeedSourceCandidate',
        back_populates='seed_source',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return (
            f"SeedSource(id={self.id}, name='{self.name}', "
            f"type='{self.source_type}', provider='{self.provider}')"
        )


class SeedSourceRun(db.Model):
    """
    Import/read status for a configured seed source.
    """
    __tablename__ = 'seed_source_run'

    id = db.Column(db.Integer, primary_key=True)
    seed_source_id = db.Column(db.Integer, db.ForeignKey('seed_source.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(30), default='planned', nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    songs_seen = db.Column(db.Integer, default=0, nullable=False)
    songs_imported = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index('idx_seed_source_run_source_status', 'seed_source_id', 'status', 'started_at'),
    )

    seed_source = db.relationship('SeedSource', back_populates='runs')
    candidates = db.relationship('SeedSourceCandidate', back_populates='seed_source_run', lazy='dynamic')

    def __repr__(self):
        return (
            f"SeedSourceRun(seed_source_id={self.seed_source_id}, "
            f"status='{self.status}', imported={self.songs_imported})"
        )


class SeedSourceCandidate(db.Model):
    """A review-only track candidate discovered from an external catalog source."""

    __tablename__ = 'seed_source_candidate'

    id = db.Column(db.Integer, primary_key=True)
    seed_source_id = db.Column(
        db.Integer, db.ForeignKey('seed_source.id', ondelete='CASCADE'), nullable=False
    )
    seed_source_run_id = db.Column(
        db.Integer, db.ForeignKey('seed_source_run.id', ondelete='SET NULL'), nullable=True
    )
    external_key = db.Column(db.String(128), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    artist = db.Column(db.String(300), nullable=True)
    album_name = db.Column(db.String(300), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    spotify_id = db.Column(db.String(64), nullable=True)
    deezer_id = db.Column(db.String(64), nullable=True)
    isrc = db.Column(db.String(20), nullable=True)
    recording_mbid = db.Column(db.String(36), nullable=True)
    source_rank = db.Column(db.Integer, nullable=True)
    source_score = db.Column(db.BigInteger, nullable=True)
    popularity = db.Column(db.Integer, nullable=True)
    needs_review = db.Column(db.Boolean, default=True, nullable=False)
    review_status = db.Column(db.String(20), default='pending', nullable=False)
    review_notes = db.Column(db.Text, nullable=True)
    raw_metadata = db.Column(db.Text, nullable=True)
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('seed_source_id', 'external_key', name='uq_seed_source_candidate_key'),
        db.Index('idx_seed_source_candidate_review', 'seed_source_id', 'review_status', 'last_seen_at'),
        db.Index(
            'idx_seed_source_candidate_identifiers',
            'isrc', 'spotify_id', 'deezer_id', 'recording_mbid',
        ),
    )

    seed_source = db.relationship('SeedSource', back_populates='candidates')
    seed_source_run = db.relationship('SeedSourceRun', back_populates='candidates')

    def __repr__(self):
        return (
            f"SeedSourceCandidate(seed_source_id={self.seed_source_id}, "
            f"external_key='{self.external_key}', status='{self.review_status}')"
        )


class ImportJobRecord(db.Model):
    """
    Database model for tracking import jobs
    """
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(50), nullable=False)
    item_type = db.Column(db.String(20), nullable=False)
    item_id = db.Column(db.String(255), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=10)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed, dead_letter
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    imported_count = db.Column(db.Integer, default=0)
    skipped_count = db.Column(db.Integer, default=0)
    attempt_count = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=3)
    result_metadata = db.Column(db.Text)

    __table_args__ = (
        db.Index('idx_import_job_claim', 'status', 'priority', 'created_at'),
        db.Index('idx_import_job_user_status', 'user_id', 'status', 'created_at'),
    )
    
    # Relationships
    user = db.relationship('User', backref=db.backref('import_jobs', lazy=True))
    
    def __repr__(self):
        return f"ImportJobRecord(id={self.id}, service={self.service_name}, type={self.item_type}, item_id={self.item_id}, status={self.status})"
    
    @property
    def duration(self):
        """Calculate the job duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def item_url(self):
        """Generate a URL to the imported item based on service and type."""
        if self.service_name == 'spotify':
            if self.item_type == 'playlist':
                return f"https://open.spotify.com/playlist/{self.item_id}"
            elif self.item_type == 'album':
                return f"https://open.spotify.com/album/{self.item_id}"
            elif self.item_type == 'track':
                return f"https://open.spotify.com/track/{self.item_id}"
        elif self.service_name == 'deezer':
            if self.item_type == 'playlist':
                return f"https://www.deezer.com/playlist/{self.item_id}"
            elif self.item_type == 'album':
                return f"https://www.deezer.com/album/{self.item_id}"
            elif self.item_type == 'track':
                return f"https://www.deezer.com/track/{self.item_id}"
        return None
