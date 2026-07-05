"""Tests for Flask app factory configuration helpers."""
import os

from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

from musicround import _configure_database_uri, _import_workers_enabled


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
    assert created_paths == [('/data', True)]


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
    with app.app_context():
        db.session.remove()
        db.drop_all()
