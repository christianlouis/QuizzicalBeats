import os
import openai
from dotenv import load_dotenv
import tempfile
from datetime import timedelta

# Load environment variables from .env file
load_dotenv()

# Set up OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Get the base directory of the application
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Debug settings
    DEBUG = os.getenv("DEBUG", "True") == "True"
    DEBUG2 = os.getenv("DEBUG2", "False") == "True"
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-please-change')
    
    # API Keys
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
    MEANINGCLOUD_API_KEY = os.getenv("MEANINGCLOUD_API_KEY")
    LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
    ACRCLOUD_TOKEN = os.getenv("ACRCLOUD_TOKEN")
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
    OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_SEARCH_MODEL = os.getenv("OPENAI_SEARCH_MODEL", "gpt-4o-mini-search")
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    
    # Spotify API credentials    
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
    SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative user-library-read user-top-read user-read-private user-read-email user-read-recently-played user-follow-read playlist-modify-public playlist-modify-private"
    
    # Deezer API credentials
    DEEZER_APP_ID = os.getenv("DEEZER_APP_ID", "")
    DEEZER_APP_SECRET = os.getenv("DEEZER_APP_SECRET", "")
    DEEZER_REDIRECT_URI = os.getenv("DEEZER_REDIRECT_URI", "http://localhost:5000/deezer-callback")
    
    # Google OAuth credentials
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    
    # Authentik OAuth credentials
    AUTHENTIK_CLIENT_ID = os.getenv("AUTHENTIK_CLIENT_ID", "")
    AUTHENTIK_CLIENT_SECRET = os.getenv("AUTHENTIK_CLIENT_SECRET", "")
    AUTHENTIK_METADATA_URL = os.getenv("AUTHENTIK_METADATA_URL", "")
    
    # Dropbox OAuth credentials
    DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
    DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
    DROPBOX_REDIRECT_URI = os.getenv("DROPBOX_REDIRECT_URI", "http://localhost:5000/users/dropbox/callback")
    
    MAIL_HOST = os.getenv("MAIL_HOST", "localhost")
    MAIL_PORT = os.getenv("MAIL_PORT", 25)
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "False") == "True"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False") == "True"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_SENDER = os.getenv("MAIL_SENDER", "quizzical-beats@example.com")
    MAIL_RECIPIENT = os.getenv("MAIL_RECIPIENT", "admin@example.com")
    
    # Automation settings
    AUTOMATION_TOKEN = os.getenv("AUTOMATION_TOKEN", "change-this-token-in-production")



