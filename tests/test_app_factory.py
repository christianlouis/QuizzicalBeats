"""Tests for Flask app factory configuration helpers."""
import os
import json
import importlib
import gzip
from datetime import datetime, timedelta

from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
os.environ.setdefault('AUTOMATION_TOKEN', 'test-automation-token-for-testing')

from musicround import (
    _configure_database_uri,
    _install_security_headers,
    _install_response_compression,
    _install_static_asset_cache,
    _import_workers_enabled,
    _spotify_authlib_token_from_user,
    _store_spotify_authlib_token,
)
from musicround.helpers.database_config import (
    database_uri_from_postgres_env,
    database_summary,
    database_uri_overrides_postgres_env,
    is_legacy_data_sqlite_uri,
    managed_database_requirement_error,
    postgres_env_readiness,
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


def test_configure_database_uri_builds_from_postgres_env(monkeypatch):
    """Managed deployments can avoid storing one full URI secret."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    monkeypatch.setenv('PGHOST', 'quizzicalbeats-db-rw.quizzicalbeats.svc.cluster.local')
    monkeypatch.setenv('PGPORT', '5432')
    monkeypatch.setenv('PGDATABASE', 'quizzicalbeats')
    monkeypatch.setenv('PGUSER', 'qb_user')
    monkeypatch.setenv('PGPASSWORD', 'super secret/pass')
    app = Flask(__name__)
    app.config['DATABASE_REQUIRE_MANAGED'] = True

    _configure_database_uri(app)

    assert app.config['DATABASE_BACKEND'] == 'postgresql'
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql+psycopg2://qb_user:')
    assert 'super secret/pass' not in app.config['SQLALCHEMY_DATABASE_URI']
    assert app.config['DATABASE_URI_REDACTED'] == (
        'postgresql+psycopg2://qb_user:***@'
        'quizzicalbeats-db-rw.quizzicalbeats.svc.cluster.local:5432/quizzicalbeats'
    )


def test_configure_database_uri_explicit_uri_wins_over_postgres_env(monkeypatch):
    """Existing SQLALCHEMY_DATABASE_URI deployments keep their current contract."""
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://explicit.example/qb')
    monkeypatch.setenv('PGHOST', 'ignored.example')
    monkeypatch.setenv('PGDATABASE', 'ignored')
    monkeypatch.setenv('PGUSER', 'ignored')
    monkeypatch.setenv('PGPASSWORD', 'ignored')
    app = Flask(__name__)

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'postgresql://explicit.example/qb'


def test_configure_database_uri_rejects_partial_postgres_env(monkeypatch):
    """Partial PG* configuration should fail before falling back to SQLite."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    monkeypatch.setenv('PGHOST', 'postgres.example')
    monkeypatch.setenv('PGDATABASE', 'quizzicalbeats')
    monkeypatch.delenv('PGUSER', raising=False)
    monkeypatch.delenv('PGPASSWORD', raising=False)
    app = Flask(__name__)

    import pytest
    with pytest.raises(RuntimeError, match='PostgreSQL environment is incomplete'):
        _configure_database_uri(app)


def test_postgres_env_readiness_reports_only_key_names():
    """PG readiness diagnostics should not expose configured values."""
    readiness = postgres_env_readiness({
        'PGHOST': 'postgres.example',
        'PGDATABASE': 'quizzicalbeats',
        'PGSSLMODE': 'require',
    })

    assert readiness['configured'] is True
    assert readiness['complete'] is False
    assert readiness['present_required'] == ['PGHOST', 'PGDATABASE']
    assert readiness['missing_required'] == ['PGUSER', 'PGPASSWORD']
    assert readiness['present_optional'] == ['PGSSLMODE']
    assert 'postgres.example' not in repr(readiness)


def test_database_uri_override_detects_complete_postgres_env():
    """Operators should see when SQLALCHEMY_DATABASE_URI masks split PG* config."""
    env = {
        'SQLALCHEMY_DATABASE_URI': 'sqlite:////data/song_data.db',
        'PGHOST': 'postgres.example',
        'PGDATABASE': 'quizzicalbeats',
        'PGUSER': 'qb_user',
        'PGPASSWORD': 'super-secret-password',
    }

    assert database_uri_overrides_postgres_env(env) is True
    assert database_uri_overrides_postgres_env({'PGHOST': 'postgres.example'}) is False
    assert database_uri_overrides_postgres_env({**env, 'PGPASSWORD': ''}) is False


def test_configure_database_uri_uses_sqlite_fallback(monkeypatch):
    """Test fallback SQLite path is only used when no URI is configured."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    monkeypatch.delenv('DATA_DIR', raising=False)
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


def test_configure_database_uri_uses_configured_data_dir(monkeypatch, tmp_path):
    """SQLite fallback should follow DATA_DIR when deployments override it."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    monkeypatch.delenv('DATA_DIR', raising=False)
    created_paths = []
    app = Flask(__name__)
    app.config['DATA_DIR'] = str(tmp_path)

    monkeypatch.setattr('musicround.os.path.exists', lambda path: False)
    monkeypatch.setattr(
        'musicround.os.makedirs',
        lambda path, exist_ok=False: created_paths.append((path, exist_ok)),
    )

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == f"sqlite:///{tmp_path}/song_data.db"
    assert app.config['DATABASE_BACKEND'] == 'sqlite'
    assert created_paths == [(str(tmp_path), True)]


def test_configure_database_uri_prefers_env_data_dir(monkeypatch, tmp_path):
    """SQLite fallback should follow DATA_DIR from the runtime environment."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    created_paths = []
    app = Flask(__name__)
    app.config['DATA_DIR'] = '/data'

    monkeypatch.setattr('musicround.os.path.exists', lambda path: False)
    monkeypatch.setattr(
        'musicround.os.makedirs',
        lambda path, exist_ok=False: created_paths.append((path, exist_ok)),
    )

    _configure_database_uri(app)

    assert app.config['SQLALCHEMY_DATABASE_URI'] == f"sqlite:///{tmp_path}/song_data.db"
    assert app.config['DATABASE_BACKEND'] == 'sqlite'
    assert created_paths == [(str(tmp_path), True)]


def test_configure_database_uri_requires_managed_database(monkeypatch):
    """Production guard fails fast when managed DB mode has no URI."""
    monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
    app = Flask(__name__)
    app.config['DATABASE_REQUIRE_MANAGED'] = True

    import pytest
    with pytest.raises(RuntimeError, match='complete PGHOST/PGDATABASE/PGUSER'):
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
    assert 'complete PG* database credentials' in sqlite_error
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


def test_database_uri_redaction_preserves_valid_escaped_username():
    """Redacted URIs should stay parseable when usernames need escaping."""
    uri = 'postgresql+psycopg2://qb%20user:super-secret@[2001:db8::1]:5432/quiz%20db'

    redacted = redact_database_uri(uri)

    assert redacted == 'postgresql+psycopg2://qb%20user:***@[2001:db8::1]:5432/quiz%20db'
    assert 'qb user' not in redacted
    assert 'super-secret' not in redacted


def test_database_uri_redaction_requotes_literal_percent_username():
    """Literal percent characters should stay percent-encoded after redaction."""
    uri = 'postgresql+psycopg2://user%25name:super-secret@postgres.example:5432/qb'

    redacted = redact_database_uri(uri)

    assert redacted == 'postgresql+psycopg2://user%25name:***@postgres.example:5432/qb'
    assert 'user%name' not in redacted
    assert 'super-secret' not in redacted


def test_database_uri_from_postgres_env_quotes_secret_components():
    """Generated URIs must be valid and never include raw secret text."""
    environ = {
        'PGHOST': 'postgres.example',
        'PGPORT': '5432',
        'PGDATABASE': 'quiz db',
        'PGUSER': 'qb user',
        'PGPASSWORD': 'pass/with spaces',
        'PGSSLMODE': 'require',
    }

    uri = database_uri_from_postgres_env(environ)

    assert uri == (
        'postgresql+psycopg2://qb%20user:pass%2Fwith%20spaces@'
        'postgres.example:5432/quiz%20db?sslmode=require'
    )
    assert 'pass/with spaces' not in uri


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


def test_security_headers_are_installed_on_responses():
    """Production security headers should be present by default."""
    app = Flask(__name__)
    app.config.update(
        SECURITY_HEADERS_ENABLED=True,
        USE_HTTPS=False,
        SECURITY_FRAME_OPTIONS='DENY',
        SECURITY_REFERRER_POLICY='strict-origin-when-cross-origin',
        SECURITY_PERMISSIONS_POLICY='camera=(), microphone=(), geolocation=()',
    )
    _install_security_headers(app)

    @app.route('/headers')
    def headers_route():
        return 'ok'

    response = app.test_client().get('/headers')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert response.headers['Permissions-Policy'] == 'camera=(), microphone=(), geolocation=()'
    assert 'Strict-Transport-Security' not in response.headers


def test_security_headers_add_hsts_only_when_https_is_forced():
    """HSTS should only be emitted when the app is configured for HTTPS."""
    app = Flask(__name__)
    app.config.update(
        SECURITY_HEADERS_ENABLED=True,
        USE_HTTPS=True,
        SECURITY_HSTS_ENABLED=True,
        SECURITY_HSTS_MAX_AGE=123,
        SECURITY_HSTS_INCLUDE_SUBDOMAINS=True,
    )
    _install_security_headers(app)

    @app.route('/headers')
    def headers_route():
        return 'ok'

    response = app.test_client().get('/headers')

    assert response.headers['Strict-Transport-Security'] == 'max-age=123; includeSubDomains'


def test_security_headers_can_be_disabled():
    """Operators can disable app-level headers if the edge already owns them."""
    app = Flask(__name__)
    app.config.update(SECURITY_HEADERS_ENABLED=False, USE_HTTPS=True)
    _install_security_headers(app)

    @app.route('/headers')
    def headers_route():
        return 'ok'

    response = app.test_client().get('/headers')

    assert 'X-Content-Type-Options' not in response.headers
    assert 'Strict-Transport-Security' not in response.headers


def test_response_compression_gzips_large_text_response():
    """Large text-like responses should be compressed when clients support gzip."""
    app = Flask(__name__)
    app.config.update(
        RESPONSE_COMPRESSION_ENABLED=True,
        RESPONSE_COMPRESSION_MIN_BYTES=64,
        RESPONSE_COMPRESSION_MIMETYPES='text/plain,application/json',
    )
    _install_response_compression(app)

    @app.route('/large')
    def large_route():
        return app.response_class('quiz-beats-' * 200, mimetype='text/plain')

    response = app.test_client().get('/large', headers={'Accept-Encoding': 'gzip'})

    assert response.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in response.headers['Vary']
    assert gzip.decompress(response.data) == b'quiz-beats-' * 200
    assert int(response.headers['Content-Length']) == len(response.data)


def test_response_compression_skips_clients_without_gzip():
    """Responses should stay uncompressed unless the client advertises gzip."""
    app = Flask(__name__)
    app.config.update(RESPONSE_COMPRESSION_ENABLED=True, RESPONSE_COMPRESSION_MIN_BYTES=64)
    _install_response_compression(app)

    @app.route('/large')
    def large_route():
        return app.response_class('quiz-beats-' * 200, mimetype='text/plain')

    response = app.test_client().get('/large')

    assert 'Content-Encoding' not in response.headers
    assert response.data == b'quiz-beats-' * 200


def test_response_compression_skips_binary_downloads():
    """Binary assets and generated artifacts must not be gzipped by the app."""
    app = Flask(__name__)
    app.config.update(RESPONSE_COMPRESSION_ENABLED=True, RESPONSE_COMPRESSION_MIN_BYTES=1)
    _install_response_compression(app)

    @app.route('/round.pdf')
    def pdf_route():
        return app.response_class(b'%PDF-' + (b'0' * 500), mimetype='application/pdf')

    response = app.test_client().get('/round.pdf', headers={'Accept-Encoding': 'gzip'})

    assert 'Content-Encoding' not in response.headers
    assert response.data.startswith(b'%PDF-')


def test_response_compression_can_be_disabled():
    """Operators can keep compression owned by the reverse proxy only."""
    app = Flask(__name__)
    app.config.update(RESPONSE_COMPRESSION_ENABLED=False, RESPONSE_COMPRESSION_MIN_BYTES=1)
    _install_response_compression(app)

    @app.route('/large')
    def large_route():
        return app.response_class('quiz-beats-' * 200, mimetype='text/plain')

    response = app.test_client().get('/large', headers={'Accept-Encoding': 'gzip'})

    assert 'Content-Encoding' not in response.headers
    assert response.data == b'quiz-beats-' * 200


def test_static_asset_cache_sets_public_max_age(tmp_path):
    """Flask-served static assets should get bounded browser cache headers."""
    static_dir = tmp_path / 'static'
    static_dir.mkdir()
    (static_dir / 'style.css').write_text('body { color: navy; }')
    app = Flask(__name__, static_folder=str(static_dir), static_url_path='/static')
    app.config.update(STATIC_ASSET_CACHE_ENABLED=True, STATIC_ASSET_CACHE_SECONDS=123)
    _install_static_asset_cache(app)

    response = app.test_client().get('/static/style.css')

    assert response.status_code == 200
    assert 'public' in response.headers['Cache-Control']
    assert 'max-age=123' in response.headers['Cache-Control']
    assert response.headers.get('Expires')


def test_static_asset_cache_can_be_disabled(tmp_path):
    """Operators can leave static caching entirely to the edge proxy."""
    static_dir = tmp_path / 'static'
    static_dir.mkdir()
    (static_dir / 'style.css').write_text('body { color: navy; }')
    app = Flask(__name__, static_folder=str(static_dir), static_url_path='/static')
    app.config.update(STATIC_ASSET_CACHE_ENABLED=False, STATIC_ASSET_CACHE_SECONDS=123)
    _install_static_asset_cache(app)

    response = app.test_client().get('/static/style.css')

    assert response.status_code == 200
    assert 'max-age=123' not in response.headers.get('Cache-Control', '')


def test_static_asset_cache_ignores_normal_routes():
    """Dynamic pages should not inherit static-asset cache policy."""
    app = Flask(__name__)
    app.config.update(STATIC_ASSET_CACHE_ENABLED=True, STATIC_ASSET_CACHE_SECONDS=123)
    _install_static_asset_cache(app)

    @app.route('/dynamic')
    def dynamic_route():
        return 'dynamic'

    response = app.test_client().get('/dynamic')

    assert response.status_code == 200
    assert 'max-age=123' not in response.headers.get('Cache-Control', '')


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
