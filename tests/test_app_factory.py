"""Tests for Flask app factory configuration helpers."""
import os
import json
import importlib
from datetime import datetime, timedelta

from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

from musicround import (
    _configure_database_uri,
    _import_workers_enabled,
    _spotify_authlib_token_from_user,
    _store_spotify_authlib_token,
)
from musicround.helpers.database_config import (
    database_summary,
    is_legacy_data_sqlite_uri,
    managed_database_requirement_error,
    redact_database_uri,
)
from musicround.models import User, db


def test_configure_database_uri_preserves_explicit_env_uri(monkeypatch):
    """Test explicit SQLALCHEMY_DATABASE_URI is not overwritten."""
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    app = Flask(__name__)

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:'


def test_configure_database_uri_preserves_explicit_config_uri(monkeypatch):
    """Test explicit app config URI is not overwritten."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://db.example/qb'

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'postgresql://db.example/qb'
    assert app.config['DATABASE_BACKEND'] == 'postgresql'


def test_configure_database_uri_uses_sqlite_fallback(monkeypatch):
    """Test fallback SQLite path is only used when no URI is configured."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    created_paths = []
    app = Flask(__name__)

    monkeypatch.setattr('musicround.os.path.exists', lambda path: False)
    monkeypatch.setattr(
        'musicround.os.makedirs',
        lambda path, exist_ok=False: created_paths.append((path, exist_ok)),
    )

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:////data/song_data.db'
    assert app.config['DATABASE_BACKEND'] == 'sqlite'
    assert created_paths == [('/data', True)]


def test_configure_database_uri_requires_managed_database(monkeypatch):
    """Production guard fails fast when managed DB mode has no URI."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    app = Flask(__name__)
    app.config['DATABASE_REQUIRE_MANAGED'] = True

    import pytest
    with pytest.raises(RuntimeError, match='SQLALCHEMY_DATABASE_URI is not configured'):
        _configure_database_uri(app)


def test_configure_database_uri_rejects_sqlite_when_managed_required(monkeypatch):
    """Production guard prevents accidentally keeping SQLite in managed DB mode."""
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:////data/song_data.db')
    app = Flask(__name__)
    app.config['DATABASE_REQUIRE_MANAGED'] = True

    import pytest
    with pytest.raises(RuntimeError, match='points at SQLite'):
        _configure_database_uri(app)


def test_configure_database_uri_accepts_lowercase_managed_flag(monkeypatch):
    """Managed DB guard should accept env-style lowercase booleans."""
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:////data/song_data.db')
    app = Flask(__name__)
    app.config['DATABASE_REQUIRE_MANAGED'] = 'true'

    import pytest
    with pytest.raises(RuntimeError, match='points at SQLite'):
        _configure_database_uri(app)


def test_config_bool_parses_common_managed_database_values(monkeypatch):
    """Config should parse the same DATABASE_REQUIRE_MANAGED values as runtime."""
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-testing-only')
    monkeypatch.setenv('DATABASE_REQUIRE_MANAGED', 'yes')

    import musicround.config as config_module

    reloaded = importlib.reload(config_module)

    assert reloaded.Config.DATABASE_REQUIRE_MANAGED is True
    monkeypatch.setenv('DATABASE_REQUIRE_MANAGED', 'False')
    importlib.reload(config_module)


def test_managed_database_requirement_error_is_credential_safe():
    """Managed DB guard errors must not include raw database credentials."""
    uri = 'postgresql://qb_user:super-secret@postgres.example/qb'

    assert managed_database_requirement_error(uri, True) is None
    assert 'super-secret' not in managed_database_requirement_error(None, True)
    sqlite_error = managed_database_requirement_error('sqlite:////data/song_data.db', 'on')
    assert 'points at SQLite' in sqlite_error
    assert '/data/song_data.db' not in sqlite_error


def test_database_uri_redaction_hides_credentials():
    """Credential-safe summaries must never expose database passwords."""
    uri = 'postgresql://qb_user:super-secret@postgres.example:5432/quizzicalbeats'

    redacted = redact_database_uri(uri)
    summary = database_summary(uri)

    assert 'super-secret' not in redacted
    assert 'super-secret' not in summary['redacted_uri']
    assert summary['backend'] == 'postgresql'
    assert summary['host'] == 'postgres.example'
    assert summary['database'] == 'quizzicalbeats'


def test_legacy_sqlite_uri_detection_is_specific_to_data_file():
    """Only the old production SQLite file should trigger managed-DB warnings."""
    assert is_legacy_data_sqlite_uri('sqlite:////data/song_data.db') is True
    assert is_legacy_data_sqlite_uri('sqlite:///:memory:') is False
    assert is_legacy_data_sqlite_uri('sqlite:////tmp/test.db') is False
    assert is_legacy_data_sqlite_uri('postgresql://db.example/qb') is False


def test_create_app_honors_env_database_uri(monkeypatch):
    """Test create_app keeps SQLALCHEMY_DATABASE_URI from the environment."""
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-testing-only')
    monkeypatch.setenv('AUTOMATION_TOKEN', 'test-automation-token-for-testing')
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    monkeypatch.setenv('IMPORT_WORKERS_ENABLED', 'false')

    from musicround import create_app, db

    app = create_app()

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:'
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_import_workers_disabled_by_default(monkeypatch):
    """Import workers must be an explicit opt-in app-factory side effect."""
    monkeypatch.delenv('IMPORT_WORKERS_ENABLED', raising=False)
    app = Flask(__name__)

    assert _import_workers_enabled(app) is False


def test_import_workers_can_be_enabled_by_env(monkeypatch):
    """Operators can still opt into in-process import workers explicitly."""
    monkeypatch.setenv('IMPORT_WORKERS_ENABLED', 'true')
    app = Flask(__name__)

    assert _import_workers_enabled(app) is True


def test_create_app_does_not_start_import_workers_by_default(monkeypatch):
    """Creating a web app must not spawn import worker threads by default."""
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-testing-only')
    monkeypatch.setenv('AUTOMATION_TOKEN', 'test-automation-token-for-testing')
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    monkeypatch.delenv('IMPORT_WORKERS_ENABLED', raising=False)

    from musicround import create_app, db

    app = create_app()

    assert app.config['import_workers'] == []
    assert app.config['IMPORT_WORKERS_ENABLED_RESOLVED'] is False
    assert app.config['IMPORT_WORKER_COUNT_RESOLVED'] >= 1
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_spotify_authlib_token_from_legacy_json_user_token(app):
    """The token bridge must keep old JSON token rows readable."""
    expires_at = int((datetime.now() + timedelta(hours=1)).timestamp())
    with app.app_context():
        user = User(username='legacy_bridge', email='legacy-bridge@example.com')
        user.spotify_token = json.dumps({
            'access_token': 'legacy-access',
            'refresh_token': 'legacy-refresh',
            'expires_at': expires_at,
        })

        token = _spotify_authlib_token_from_user(user)

    assert token == {
        'access_token': 'legacy-access',
        'token_type': 'Bearer',
        'refresh_token': 'legacy-refresh',
        'expires_at': expires_at,
    }


def test_store_spotify_authlib_token_uses_raw_columns(app):
    """Authlib updates should not write JSON token objects back into spotify_token."""
    expires_at = int((datetime.now() + timedelta(hours=1)).timestamp())
    with app.app_context():
        user = User(username='raw_bridge', email='raw-bridge@example.com')

        _store_spotify_authlib_token(
            user,
            {
                'access_token': 'new-access',
                'refresh_token': 'new-refresh',
                'expires_at': expires_at,
            },
        )

    assert user.spotify_token == 'new-access'
    assert user.spotify_refresh_token == 'new-refresh'
    assert user.spotify_token_expiry == datetime.fromtimestamp(expires_at)
