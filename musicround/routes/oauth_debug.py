"""
Debug route for OAuth URL generation
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, abort, render_template, jsonify, current_app, request, url_for
from flask_login import current_user, login_required
from musicround.helpers.auth_helpers import get_oauth_redirect_uri

# Create blueprint
oauth_debug_bp = Blueprint('oauth_debug', __name__)
REDACTED_VALUE = '[redacted]'
SENSITIVE_QUERY_PARTS = (
    'password',
    'passwd',
    'token',
    'secret',
    'api_key',
    'apikey',
    'access_key',
)


def _is_sensitive_name(name):
    normalized = str(name).lower().replace('-', '_')
    return any(part in normalized for part in SENSITIVE_QUERY_PARTS)


def _redact_url(value):
    if not value:
        return value
    parsed = urlsplit(value)
    if not parsed.query:
        return value
    redacted_query = urlencode(
        [
            (key, REDACTED_VALUE if _is_sensitive_name(key) else val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment))


def _redact_header_value(key, value):
    if _is_sensitive_name(key):
        return REDACTED_VALUE
    if str(key).lower() in {'referer', 'origin'}:
        return _redact_url(value)
    return value

@oauth_debug_bp.route('/debug/oauth-urls')
@login_required
def debug_oauth_urls():
    """
    Debug endpoint to show OAuth URL generation with current configuration
    This is useful for verifying proper HTTPS handling when behind a reverse proxy
    
    Formats:
    - HTML: Default view with pretty UI
    - JSON: Add ?format=json or use Accept: application/json header
    """
    if not current_app.config.get('ENABLE_OAUTH_DEBUG'):
        abort(404)
    if not current_user.is_admin:
        abort(403)

    # Get config settings
    use_https = current_app.config.get('USE_HTTPS', False)
    preferred_scheme = current_app.config.get('PREFERRED_URL_SCHEME', 'http')
    static_oauth_urls = current_app.config.get('STATIC_OAUTH_URLS', False)
    
    # Get all static URL configurations
    static_urls = {
        'OAUTH_SPOTIFY_AUTH_URL': current_app.config.get('OAUTH_SPOTIFY_AUTH_URL'),
        'OAUTH_SPOTIFY_LINK_URL': current_app.config.get('OAUTH_SPOTIFY_LINK_URL'),
        'OAUTH_GOOGLE_URL': current_app.config.get('OAUTH_GOOGLE_URL'),
        'OAUTH_AUTHENTIK_URL': current_app.config.get('OAUTH_AUTHENTIK_URL'),
        'OAUTH_DROPBOX_URL': current_app.config.get('OAUTH_DROPBOX_URL')
    }
    
    # Generate all OAuth callback URLs using the helper function
    oauth_urls = {
        'spotify_auth': get_oauth_redirect_uri('auth.callback'),
        'spotify_link': get_oauth_redirect_uri('users.spotify_link_callback'),
        'google_login': get_oauth_redirect_uri('users.google_callback'),
        'authentik_login': get_oauth_redirect_uri('users.authentik_callback'),
        'dropbox_link': get_oauth_redirect_uri('users.dropbox_callback')
    }
    
    # Generate the same URLs directly with url_for for comparison
    direct_urls = {
        'spotify_auth': url_for('auth.callback', _external=True),
        'spotify_link': url_for('users.spotify_link_callback', _external=True),
        'google_login': url_for('users.google_callback', _external=True),
        'authentik_login': url_for('users.authentik_callback', _external=True),
        'dropbox_link': url_for('users.dropbox_callback', _external=True)
    }
    
    # Get request info
    request_info = {
        'url': _redact_url(request.url),
        'host': request.host,
        'scheme': request.scheme,
        'headers': {
            key: _redact_header_value(key, value) for key, value in request.headers.items()
            if key.lower() in ('x-forwarded-for', 'x-forwarded-proto', 
                              'x-forwarded-host', 'host', 'origin', 'referer')
        }
    }
    
    # Compile data for both JSON and HTML response
    result = {
        'config': {
            'USE_HTTPS': use_https,
            'PREFERRED_URL_SCHEME': preferred_scheme,
            'STATIC_OAUTH_URLS': static_oauth_urls,
        },
        'helper_generated_urls': oauth_urls,
        'direct_url_for_urls': direct_urls,
        'request_info': request_info
    }
    
    current_app.logger.info(f"OAuth Debug URLs generated")
    
    # Check if JSON format is requested
    wants_json = (request.args.get('format', '').lower() == 'json' or
                 request.headers.get('Accept', '').lower().find('application/json') >= 0)
                 
    if wants_json:
        return jsonify(result)
    else:
        # Return HTML view
        return render_template('oauth_debug.html', 
                              config=result['config'],
                              helper_generated_urls=result['helper_generated_urls'],
                              direct_url_for_urls=result['direct_url_for_urls'],
                              request_info=result['request_info'])
