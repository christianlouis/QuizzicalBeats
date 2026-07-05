"""Tests for Flask app factory configuration helpers."""
from flask import Flask

from musicround import _configure_database_uri


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
    from musicround import create_app, db

    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    monkeypatch.setenv('IMPORT_WORKERS_ENABLED', 'false')

    app = create_app()

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:'
    with app.app_context():
        db.session.remove()
        db.drop_all()
