"""
Import routes for the Music Round application
"""
import json
import time
import random
from datetime import datetime  # Add datetime import
from urllib.parse import urlsplit
from flask import Blueprint, render_template, redirect, url_for, request, current_app, flash, session, jsonify
from flask_login import current_user, login_required
from musicround.models import Song, db
from musicround.routes.import_songs import import_pl
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.auth_helpers import oauth
from musicround.helpers.spotify_helper import get_spotify_token
from musicround.services import automation

import_bp = Blueprint('import', __name__, url_prefix='/import')
_DIRECT_SPOTIFY_SESSION_KEYS = (
    'direct_bearer_token',
    'direct_spotify_user',
    'direct_spotify_username',
)


def _clear_direct_spotify_session():
    """Remove temporary direct Spotify credentials from the browser session."""
    for key in _DIRECT_SPOTIFY_SESSION_KEYS:
        session.pop(key, None)


def _safe_return_url(value, fallback_endpoint='import.direct_official_playlists'):
    """Allow only local relative redirects from import forms."""
    fallback = url_for(fallback_endpoint)
    if not value:
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not value.startswith('/') or value.startswith('//') or '\n' in value or '\r' in value:
        return fallback
    return value


def _validate_direct_spotify_token(bearer_token):
    """Validate a manually supplied direct Spotify bearer token."""
    from musicround.helpers.spotify_direct import SpotifyDirectClient

    client = SpotifyDirectClient(bearer_token=bearer_token)
    result = client._make_api_request("me")
    if result and result.get('id'):
        return result
    return None


def _store_direct_spotify_session(bearer_token, user_info):
    """Persist direct Spotify token metadata after validation has succeeded."""
    session['direct_bearer_token'] = bearer_token
    session['direct_spotify_user'] = user_info['id']
    session['direct_spotify_username'] = user_info.get('display_name') or user_info['id']


def _require_import_diagnostics_admin():
    """Restrict raw Spotify diagnostic views to admins."""
    if current_user.is_admin:
        return None
    flash('Admin access required for Spotify diagnostics.', 'danger')
    return redirect(url_for('core.view_songs'))


def _safe_spotify_diagnostic_error(client_name='Spotify'):
    """Return a browser-safe diagnostic error message."""
    return f"{client_name} diagnostic check failed. Check the server logs."

def fetch_all_user_playlists(oauth_client, token, user_id, limit=50):
    """
    Fetch all playlists from a specific Spotify user account with pagination using Authlib.
    
    Args:
        oauth_client: The Authlib Spotify client (e.g., oauth.spotify).
        token: An Authlib token object for authentication.
        user_id: Spotify user ID to fetch playlists from.
        limit: Number of playlists to fetch per request (max 50).
        
    Returns:
        List of all playlists from the specified user.
    """
    all_playlists = []
    offset = 0
    total = None
    
    start_time = time.time()
    current_app.logger.info(f"Started fetching playlists for user '{user_id}' using Authlib")
    
    max_loops = 100  # Hard limit to prevent infinite loops
    loop_count = 0
    
    while loop_count < max_loops:
        loop_count += 1
        try:
            api_url = f'https://api.spotify.com/v1/users/{user_id}/playlists'
            params = {'limit': limit, 'offset': offset}
            
            current_app.logger.info(f"Fetching playlists for {user_id} with offset={offset}, limit={limit}, loop={loop_count}")
            # Use Authlib client to make the GET request
            resp = oauth_client.get(api_url, token=token, params=params)
            resp.raise_for_status()  # Raise an exception for HTTP errors
            results = resp.json()
            
            response_sample = str(results)[:500] + '...' if len(str(results)) > 500 else str(results)
            current_app.logger.debug(f"API response sample: {response_sample}")
            
            if total is None:
                total = results.get('total', 0)
                current_app.logger.info(f"User '{user_id}' has {total} playlists in total according to API")
                if total == 0:
                    current_app.logger.warning(f"API reported 0 total playlists for {user_id} - possible API error or no playlists")
            
            playlists_batch = results.get('items', [])
            batch_count = len(playlists_batch)
            all_playlists.extend(playlists_batch)
            
            current_app.logger.info(f"Batch for {user_id}: offset={offset}, received={batch_count} playlists")
            
            if batch_count == 0 and offset < total:
                current_app.logger.warning(f"Received 0 playlists for {user_id} at offset {offset} but expected more (total: {total}) - stopping.")
                break
            
            if not results.get('next'): # Spotify API uses 'next' field to indicate more pages
                current_app.logger.info(f"No more 'next' URL for {user_id} at offset {offset}. Fetched {len(all_playlists)}/{total}.")
                break
                
            offset += batch_count # Correctly increment offset by the number of items received
            
            if len(all_playlists) >= total:
                current_app.logger.info(f"Fetched all {total} playlists for {user_id}.")
                break

        except Exception as e:
            current_app.logger.error(f"Error fetching playlists for user '{user_id}' at offset {offset}: {str(e)}")
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            break
    
    if loop_count >= max_loops:
        current_app.logger.warning(f"Reached maximum loop count ({max_loops}) for user {user_id}")
    
    end_time = time.time()
    duration = int((end_time - start_time) * 1000)
    current_app.logger.info(f"Completed fetching {len(all_playlists)}/{total if total is not None else 'unknown'} playlists for user '{user_id}' in {duration}ms")
    
    return all_playlists

def filter_playlists_by_keywords(playlists, keywords, debug_info=None):
    """
    Filter playlists by checking if any of the keywords are in the playlist name
    
    Args:
        playlists: List of playlist objects
        keywords: List of keywords to filter by
        debug_info: Optional debug info dictionary to update with filtering stats
        
    Returns:
        Filtered list of playlists
    """
    filtered = []
    keywords_lower = [k.lower() for k in keywords]
    
    for playlist in playlists:
        name = playlist.get('name', '').lower()
        
        # Check if any keyword is in the playlist name
        if any(keyword in name for keyword in keywords_lower):
            filtered.append(playlist)
            
            # Add to debug info if provided
            if debug_info is not None and 'matched_keywords' in debug_info:
                matched = [k for k in keywords_lower if k in name]
                for keyword in matched:
                    if keyword not in debug_info['matched_keywords']:
                        debug_info['matched_keywords'][keyword] = 0
                    debug_info['matched_keywords'][keyword] += 1
    
    return filtered

@import_bp.route('/official-playlists', methods=['GET', 'POST'])
@login_required
def import_official_playlists():
    """Display and import official Spotify playlists from multiple regional accounts"""
    # Resolve the best available Spotify token: a manually-supplied bearer token
    # (see users.update_bearer_token) takes priority, then the logged-in user's
    # own token, then the system fallback account.
    access_token, token_source = get_spotify_token()
    if not access_token:
        flash("No active Spotify session. Please connect your Spotify account.", "warning")
        return redirect(url_for('users.spotify_link'))

    auth_token = {
        'access_token': access_token,
        'token_type': 'Bearer',
    }
    if token_source == 'user':
        # Only the user's own token has a refresh_token Authlib can use to
        # auto-refresh; manual and system tokens are used as-is.
        auth_token['expires_at'] = (
            current_user.spotify_token_expiry.timestamp() if current_user.spotify_token_expiry else None
        )
        auth_token['refresh_token'] = current_user.spotify_refresh_token
    # Handle POST request for importing a playlist
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        
        # Check if user is authenticated for queue system
        if not current_user.is_authenticated:
            flash("Please log in to import playlists.", "warning")
            return redirect(url_for('users.login'))
        
        # Get the import queue from app config
        queue = current_app.config.get('import_queue')
        if not queue:
            flash("Import queue not initialized.", "danger")
            return redirect(url_for('core.view_songs'))
        
        from musicround.helpers.import_queue import enqueue_import_job
        job_record = enqueue_import_job(
            queue=queue,
            priority=request.form.get('priority', 10),
            service_name='spotify',
            item_type='playlist',
            item_id=playlist_id,
            user_id=current_user.id,
            spotify_token=access_token,
        )
        flash(f'Official Spotify playlist import queued as job #{job_record.id}.', 'info')
            
        return redirect(url_for('core.view_songs'))

    # Get filter keywords from the query string (default to empty list)
    filter_keywords = request.args.get('filter', '').split(',')
    filter_keywords = [k.strip() for k in filter_keywords if k.strip()]
    
    # List of official Spotify user accounts to fetch playlists from
    spotify_accounts = [
        'spotify',
        'spotifycharts',
        'spotifymaps', 
        'spotifyuk',
        'spotifyusa', 
        'spotify_germany'
    ]
    
    # Get selected account from query string or default to all
    selected_account = request.args.get('account', 'all')
    
    # Get debug mode parameter
    debug_mode = request.args.get('debug', 'false').lower() == 'true'
    
    # Prepare debug info
    debug_info = {
        'accounts': {},
        'total_fetched': 0,
        'total_filtered': 0,
        'filtered_out': 0,
        'matched_keywords': {},
        'query_time_ms': 0,
        'duplicates_removed': 0,
        'token_source': token_source,
    }
    
    # Initialize playlists list
    all_playlists = []
    
    try:
        start_query_time = time.time()
        
        if selected_account == 'all':
            for acc_id in spotify_accounts:
                current_app.logger.info(f"Fetching playlists for official account: {acc_id}")
                playlists = fetch_all_user_playlists(oauth.spotify, auth_token, acc_id)
                if debug_mode:
                    debug_info['accounts'][acc_id] = {'fetched': len(playlists), 'filtered_in': 0, 'filtered_out': 0}
                all_playlists.extend(playlists)
                debug_info['total_fetched'] += len(playlists)
        else:
            current_app.logger.info(f"Fetching playlists for selected official account: {selected_account}")
            playlists = fetch_all_user_playlists(oauth.spotify, auth_token, selected_account)
            if debug_mode:
                debug_info['accounts'][selected_account] = {'fetched': len(playlists), 'filtered_in': 0, 'filtered_out': 0}
            all_playlists.extend(playlists)
            debug_info['total_fetched'] += len(playlists)
        
        # Remove duplicates based on playlist ID
        unique_playlists = []
        seen_ids = set()
        for playlist in all_playlists:
            if playlist['id'] not in seen_ids:
                seen_ids.add(playlist['id'])
                unique_playlists.append(playlist)
            else:
                debug_info['duplicates_removed'] += 1
        
        all_playlists = unique_playlists
        debug_info['total_filtered'] = len(all_playlists)
        
        end_query_time = time.time()
        debug_info['query_time_ms'] = int((end_query_time - start_query_time) * 1000)
        
        # Log summary
        current_app.logger.info(
            f"Search summary: Fetched {debug_info['total_fetched']} playlists, "
            f"filtered to {debug_info['total_filtered']} playlists "
            f"({debug_info['filtered_out']} filtered out, {debug_info['duplicates_removed']} duplicates removed) "
            f"in {debug_info['query_time_ms']}ms"
        )
        
        # Sort playlists by follower count or name if available
        all_playlists.sort(key=lambda x: x.get('name', '').lower())
        
        # Randomize order if no specific sorting
        if not filter_keywords:
            random.shuffle(all_playlists)
            
    except Exception as e:
        current_app.logger.error(f"Error fetching official playlists: {e}")
        flash('Error retrieving playlists from Spotify', 'danger')
        all_playlists = []
    
    # Handle empty result
    if not all_playlists:
        flash('No Spotify playlists found matching your criteria', 'warning')
    
    spotify_username = session.get('direct_spotify_username')
    
    return render_template(
        'import_official_playlists.html',
        playlists=all_playlists,
        filter_keywords=filter_keywords,
        selected_account=selected_account,
        spotify_accounts=spotify_accounts,
        debug_info=debug_info,
        debug_mode=debug_mode,
        has_direct_bearer_token=bool(session.get('direct_bearer_token')),
        spotify_username=spotify_username,
        direct_mode=False
    )

@import_bp.route('/direct-official-playlists', methods=['GET', 'POST'])
@login_required
def direct_official_playlists():
    """Display and import official Spotify playlists using the direct client with bearer token"""
    # Check if user has provided a bearer token
    bearer_token = session.get('direct_bearer_token')
    if not bearer_token:
        flash('Please provide a bearer token first', 'warning')
        return redirect(url_for('import.direct_spotify_auth'))
    
    # Initialize direct Spotify client with bearer token
    from musicround.helpers.spotify_direct import SpotifyDirectClient
    direct_client = SpotifyDirectClient(bearer_token=bearer_token)
      # Handle POST request for importing a playlist
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        
        # Check if user is authenticated for queue system
        if not current_user.is_authenticated:
            flash("Please log in to import playlists.", "warning")
            return redirect(url_for('users.login'))
        
        # Get the import queue from app config
        queue = current_app.config.get('import_queue')
        if not queue:
            flash("Import queue not initialized.", "danger")
            return redirect(url_for('core.view_songs'))
        
        from musicround.helpers.import_queue import enqueue_import_job
        job_record = enqueue_import_job(
            queue=queue,
            priority=request.form.get('priority', 10),
            service_name='spotify',
            item_type='playlist',
            item_id=playlist_id,
            user_id=current_user.id,
            spotify_token=bearer_token,
        )
        flash(f'Direct Spotify playlist import queued as job #{job_record.id}.', 'info')
        
        return redirect(url_for('core.view_songs'))

    # Get filter keywords from the query string (default to empty list)
    filter_keywords = request.args.get('filter', '').split(',')
    filter_keywords = [k.strip() for k in filter_keywords if k.strip()]
    
    # List of official Spotify user accounts to fetch playlists from
    spotify_accounts = [
        'spotify',
        'spotifycharts',
        'spotifymaps', 
        'spotifyuk',
        'spotifyusa', 
        'spotify_germany'
    ]
    
    # Get selected account from query string or default to all
    selected_account = request.args.get('account', 'all')
    
    # Get debug mode parameter
    debug_mode = request.args.get('debug', 'false').lower() == 'true'
    
    # Prepare debug info
    debug_info = {
        'accounts': {},
        'total_fetched': 0,
        'total_filtered': 0,
        'filtered_out': 0,
        'matched_keywords': {},
        'query_time_ms': 0,
        'duplicates_removed': 0
    }
    
    # Initialize playlists list
    all_playlists = []
    
    try:
        start_time = time.time()
        
        # Process each Spotify account or just the selected one
        accounts_to_process = [selected_account] if selected_account != 'all' else spotify_accounts
        
        for account in accounts_to_process:
            if account not in spotify_accounts and account != 'all':
                continue
                
            account_debug = {
                'total': 0,
                'fetched': 0,
                'filtered': 0,
                'time_ms': 0
            }
            
            account_start = time.time()
            
            # Fetch all playlists for this account using direct client
            account_playlists = direct_client.fetch_all_user_playlists(account)
            
            account_end = time.time()
            account_debug['time_ms'] = int((account_end - account_start) * 1000)
            
            account_debug['total'] = len(account_playlists)
            account_debug['fetched'] = len(account_playlists)
            debug_info['total_fetched'] += len(account_playlists)
            
            # Apply keyword filtering if keywords provided
            if filter_keywords:
                filtered_playlists = filter_playlists_by_keywords(
                    account_playlists, 
                    filter_keywords, 
                    debug_info
                )
                account_debug['filtered'] = len(filtered_playlists)
                debug_info['filtered_out'] += (len(account_playlists) - len(filtered_playlists))
                all_playlists.extend(filtered_playlists)
            else:
                # No filtering, use all playlists
                all_playlists.extend(account_playlists)
                account_debug['filtered'] = len(account_playlists)
            
            debug_info['accounts'][account] = account_debug
            
        # Remove duplicates based on playlist ID
        unique_playlists = []
        seen_ids = set()
        for playlist in all_playlists:
            if playlist['id'] not in seen_ids:
                seen_ids.add(playlist['id'])
                unique_playlists.append(playlist)
            else:
                debug_info['duplicates_removed'] += 1
        
        all_playlists = unique_playlists
        debug_info['total_filtered'] = len(all_playlists)
        
        end_time = time.time()
        debug_info['query_time_ms'] = int((end_time - start_time) * 1000)
        
        # Log summary
        current_app.logger.info(
            f"Direct search summary: Fetched {debug_info['total_fetched']} playlists, "
            f"filtered to {debug_info['total_filtered']} playlists "
            f"({debug_info['filtered_out']} filtered out, {debug_info['duplicates_removed']} duplicates removed) "
            f"in {debug_info['query_time_ms']}ms"
        )
        
        # Sort playlists by follower count or name if available
        all_playlists.sort(key=lambda x: x.get('name', '').lower())
        
        # Randomize order if no specific sorting
        if not filter_keywords:
            random.shuffle(all_playlists)
            
    except Exception as e:
        current_app.logger.error(f"Error fetching official playlists with direct client: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        flash('Error retrieving playlists from Spotify. Please refresh your Spotify token and try again.', 'danger')
        all_playlists = []
    
    # Handle empty result
    if not all_playlists:
        flash('No Spotify playlists found matching your criteria', 'warning')
    
    return render_template(
        'import_official_playlists.html',
        playlists=all_playlists,
        filter_keywords=filter_keywords,
        selected_account=selected_account,
        spotify_accounts=spotify_accounts,
        debug_info=debug_info,
        debug_mode=debug_mode,
        direct_mode=True,
        has_direct_bearer_token=True,
        spotify_username=session.get('direct_spotify_username')
    )

@import_bp.route('/test-spotify-client', methods=['GET'])
@login_required
def test_spotify_client():
    """Test route to compare different Spotify client implementations"""
    admin_response = _require_import_diagnostics_admin()
    if admin_response:
        return admin_response
    
    # Get Spotify account to check from query parameters
    account = request.args.get('account', 'spotify')
    
    # Results container
    results = {
        'spotipy': {
            'playlists': [],
            'count': 0,
            'total': 0,
            'time_ms': 0,
            'error': None
        },
        'direct': {
            'playlists': [],
            'count': 0,
            'total': 0,
            'time_ms': 0,
            'error': None
        }
    }
    
    # Test spotipy implementation
    try:
        auth_token = session.get('spotify_token')
        if not auth_token and current_user.is_authenticated and current_user.spotify_token:
            # Attempt to build a token object compatible with Authlib from user's stored token
            auth_token = {
                'access_token': current_user.spotify_token,  # Assuming this is the access token string
                'token_type': 'Bearer',  # Default token type
                'expires_at': current_user.spotify_token_expiry.timestamp() if current_user.spotify_token_expiry else None,
                'refresh_token': current_user.spotify_refresh_token
            }
            # Ensure expires_at is a Unix timestamp if present
            if auth_token.get('expires_at') and isinstance(auth_token['expires_at'], datetime):
                auth_token['expires_at'] = int(auth_token['expires_at'].timestamp())

        if not auth_token:
            raise Exception("Spotify token not found for current user or session.")

        start_time = time.time()
        
        current_app.logger.info(f"Testing Authlib Spotify implementation for account {account}")
        # Use the fetch_all_user_playlists function which now uses oauth.spotify
        spotipy_playlists = fetch_all_user_playlists(oauth.spotify, auth_token, account)
        
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        results['spotipy']['playlists'] = spotipy_playlists
        results['spotipy']['count'] = len(spotipy_playlists)
        results['spotipy']['time_ms'] = duration_ms

    except Exception as e:
        import traceback
        current_app.logger.error(f"Error testing spotipy: {e}")
        current_app.logger.error(traceback.format_exc())
        results['spotipy']['error'] = _safe_spotify_diagnostic_error('Spotify')
    
    # Test direct implementation
    try:
        from musicround.helpers.spotify_direct import SpotifyDirectClient
        
        # Get bearer token from session if available
        bearer_token = session.get('direct_bearer_token')
        if not bearer_token:
            current_app.logger.warning("No bearer token in session for direct client")
            results['direct']['error'] = "No bearer token available. Please set a token in Direct Auth page first."
        else:
            direct_client = SpotifyDirectClient(bearer_token=bearer_token)
            
            start_time = time.time()
            current_app.logger.info(f"Testing direct implementation for account {account}")
            direct_playlists = direct_client.fetch_all_user_playlists(account)
            
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            results['direct']['playlists'] = direct_playlists
            results['direct']['count'] = len(direct_playlists)
            results['direct']['time_ms'] = duration_ms
            
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error testing direct client: {e}")
        current_app.logger.error(traceback.format_exc())
        results['direct']['error'] = _safe_spotify_diagnostic_error('Direct Spotify')
    
    # Compare playlists between implementations
    comparison = {
        'only_in_spotipy': [],
        'only_in_direct': [],
        'in_both': []
    }
    
    if results['spotipy']['playlists'] and results['direct']['playlists']:
        spotipy_ids = {pl['id'] for pl in results['spotipy']['playlists']}
        direct_ids = {pl['id'] for pl in results['direct']['playlists']}
        
        comparison['only_in_spotipy'] = list(spotipy_ids - direct_ids)
        comparison['only_in_direct'] = list(direct_ids - spotipy_ids)
        comparison['in_both'] = list(spotipy_ids.intersection(direct_ids))
    
    # Add direct auth link to template data
    direct_auth_url = url_for('import.direct_spotify_auth')
    
    # Render the comparison template
    return render_template(
        'spotify_client_test.html',
        account=account,
        results=results,
        comparison=comparison,
        direct_auth_url=direct_auth_url,
        has_bearer_token=bool(session.get('direct_bearer_token'))
    )

@import_bp.route('/raw-playlists', methods=['GET'])
@login_required
def get_raw_playlists():
    """
    Get raw playlists from Spotify without any pagination logic.
    This helps diagnose issues with the playlist retrieval.
    """
    admin_response = _require_import_diagnostics_admin()
    if admin_response:
        return admin_response
    
    # Get Spotify account to check
    account = request.args.get('account', 'spotify')
    # Get limit parameter (max 50)
    limit = min(int(request.args.get('limit', '50')), 50)
    # Get offset parameter
    offset = int(request.args.get('offset', '0'))
    
    results = {
        'spotipy': {
            'raw_response': None,
            'error': None
        },
        'direct': {
            'raw_response': None,
            'error': None
        }
    }
    
    # Test Authlib Spotify raw response
    try:
        access_token, token_source = get_spotify_token()
        if not access_token:
            results['spotipy']['error'] = "No Spotify token available."
        else:
            token = {'access_token': access_token, 'token_type': 'Bearer'}
            current_app.logger.info(
                "Getting raw playlists with Authlib Spotify client for %s, limit=%s, offset=%s, source=%s",
                account,
                limit,
                offset,
                token_source,
            )
            response = oauth.spotify.get(
                f'users/{account}/playlists',
                params={'limit': limit, 'offset': offset},
                token=token,
            )
            response.raise_for_status()
            results['spotipy']['raw_response'] = response.json()
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error getting raw Spotify playlists: {e}")
        current_app.logger.error(traceback.format_exc())
        results['spotipy']['error'] = _safe_spotify_diagnostic_error('Spotify')
    
    # Test direct API raw response
    try:
        from musicround.helpers.spotify_direct import SpotifyDirectClient
        
        # Get bearer token from session if available
        bearer_token = session.get('direct_bearer_token')
        if not bearer_token:
            current_app.logger.warning("No bearer token in session for direct client")
            results['direct']['error'] = "No bearer token available. Please set a token in Direct Auth page first."
        else:
            direct_client = SpotifyDirectClient(bearer_token=bearer_token)
            current_app.logger.info(f"Getting raw playlists with direct API for {account}, limit={limit}, offset={offset}")
            raw_result = direct_client.user_playlists(account, limit=limit, offset=offset)
            results['direct']['raw_response'] = raw_result
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error getting raw direct playlists: {e}")
        current_app.logger.error(traceback.format_exc())
        results['direct']['error'] = _safe_spotify_diagnostic_error('Direct Spotify')
    
    # Add direct auth link to template data
    direct_auth_url = url_for('import.direct_spotify_auth')
    
    return render_template(
        'raw_playlists.html',
        account=account,
        limit=limit,
        offset=offset,
        results=results,
        direct_auth_url=direct_auth_url,
        has_bearer_token=bool(session.get('direct_bearer_token'))
    )

@import_bp.route('/direct-auth', methods=['GET', 'POST'])
@login_required
def direct_spotify_auth():
    """
    Allow users to manually enter a Spotify bearer token for direct API access.
    This bypasses the OAuth flow and is useful when API limitations are in place.
    """
    error = None
    success = None
    
    if request.method == 'POST':
        bearer_token = request.form.get('bearer_token', '').strip()
        if bearer_token:
            try:
                result = _validate_direct_spotify_token(bearer_token)
                if result and 'id' in result:
                    _store_direct_spotify_session(bearer_token, result)
                    success = f"Successfully authenticated as {session['direct_spotify_username']}"
                else:
                    _clear_direct_spotify_session()
                    error = "Token validation failed. Please check the token and try again."
            except Exception as e:
                current_app.logger.error(f"Error validating bearer token: {e}")
                _clear_direct_spotify_session()
                error = "Token validation failed. Please check the token and try again."
        else:
            error = "No bearer token provided"
            
    # Get stored user info if available
    spotify_user = session.get('direct_spotify_user')
    spotify_username = session.get('direct_spotify_username')
    
    return render_template(
        'spotify_direct_auth.html',
        error=error,
        success=success,
        spotify_user=spotify_user,
        spotify_username=spotify_username
    )

@import_bp.route('/update-direct-token', methods=['POST'])
@login_required
def update_direct_token():
    """Update the direct bearer token and redirect back to the referring page"""
    # Get return URL from form or default to playlist page
    return_url = _safe_return_url(request.form.get('return_url'))
    
    # Check if clearing token was requested
    if request.form.get('clear_token'):
        _clear_direct_spotify_session()
        flash('Bearer token cleared successfully', 'success')
        return redirect(return_url)
    
    # Get bearer token from form
    bearer_token = request.form.get('bearer_token', '').strip()
    if not bearer_token:
        flash('No bearer token provided', 'warning')
        return redirect(return_url)
    
    try:
        result = _validate_direct_spotify_token(bearer_token)
        if result and 'id' in result:
            _store_direct_spotify_session(bearer_token, result)
            flash(f'Successfully authenticated as {session["direct_spotify_username"]}', 'success')
        else:
            _clear_direct_spotify_session()
            flash('Token validation failed. Please check the token and try again.', 'error')
    except Exception as e:
        current_app.logger.error(f"Error validating bearer token: {e}")
        _clear_direct_spotify_session()
        flash('Token validation failed. Please check the token and try again.', 'error')
    
    return redirect(return_url)


def _import_job_payload(job):
    """Serialize an import job record for polling APIs."""
    return {
        'id': job.id,
        'service_name': job.service_name,
        'item_type': job.item_type,
        'item_id': job.item_id,
        'priority': job.priority,
        'user_id': job.user_id,
        'status': job.status,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'duration': job.duration,
        'error_message': job.error_message,
        'imported_count': job.imported_count or 0,
        'skipped_count': job.skipped_count or 0,
        'attempt_count': job.attempt_count or 0,
        'max_attempts': job.max_attempts or 3,
        'item_url': job.item_url,
    }


def _import_queue_status_data(queue):
    """Collect queue status once for both HTML and JSON views."""
    local_queue_size = queue.qsize()
    queue_snapshot = queue.snapshot()
    active_jobs = []
    pending_jobs = []
    recent_jobs = []
    queue_size = local_queue_size

    try:
        from musicround.models import ImportJobRecord

        recent_jobs = ImportJobRecord.query.order_by(ImportJobRecord.created_at.desc()).limit(50).all()
        active_jobs = ImportJobRecord.query.filter_by(status='processing').all()
        pending_jobs = (
            ImportJobRecord.query.filter_by(status='pending')
            .order_by(
                ImportJobRecord.priority.asc(),
                ImportJobRecord.created_at.asc(),
                ImportJobRecord.id.asc(),
            )
            .limit(50)
            .all()
        )
        queue_size = ImportJobRecord.query.filter_by(status='pending').count()
        snapshot_record_ids = {
            job.get('record_id') for job in queue_snapshot if job.get('record_id')
        }
        for job in pending_jobs:
            if job.id in snapshot_record_ids:
                continue
            queue_snapshot.append({
                'priority': job.priority,
                'counter': None,
                'service': job.service_name,
                'type': job.item_type,
                'item_id': job.item_id,
                'user_id': job.user_id,
                'record_id': job.id,
                'attempt_count': job.attempt_count or 0,
                'max_attempts': job.max_attempts or 3,
            })
        queue_snapshot.sort(
            key=lambda job: (
                job.get('priority', 0),
                job.get('counter') is None,
                job.get('counter') or 0,
                job.get('record_id') or 0,
            )
        )
    except (ImportError, AttributeError):
        pass

    stats = {
        'queue_size': queue_size,
        'active_jobs': len(active_jobs),
        'completed_today': 0,
        'failed_today': 0,
        'dead_letter_jobs': 0,
    }

    if recent_jobs:
        import datetime
        today = datetime.datetime.utcnow().date()
        for job in recent_jobs:
            if job.completed_at and job.completed_at.date() == today:
                if job.status == 'completed':
                    stats['completed_today'] += 1
                elif job.status == 'failed':
                    stats['failed_today'] += 1
                elif job.status == 'dead_letter':
                    stats['dead_letter_jobs'] += 1

    return {
        'stats': stats,
        'active_jobs': active_jobs,
        'recent_jobs': recent_jobs,
        'queue_snapshot': queue_snapshot,
    }


def _require_import_queue_admin():
    """Return the configured import queue or a Flask response for common failures."""
    if not current_user.is_admin:
        return None, redirect(url_for('core.index'))

    queue = current_app.config.get('import_queue')
    if not queue:
        return None, redirect(url_for('core.view_songs'))
    return queue, None


@import_bp.route('/queue-status')
@login_required
def queue_status():
    """
    Display real-time status of the import queue for administrators
    """
    # Check if user is an admin
    queue, failure_response = _require_import_queue_admin()
    if failure_response:
        if not current_user.is_admin:
            flash('Admin access required for Import Queue view.', 'danger')
        else:
            flash("Import queue not initialized.", "danger")
        return failure_response

    # Helper function to get current time
    from datetime import datetime
    def now():
        return datetime.utcnow()

    data = _import_queue_status_data(queue)

    return render_template(
        'import_queue_status.html',
        stats=data['stats'],
        active_jobs=data['active_jobs'],
        recent_jobs=data['recent_jobs'],
        queue_snapshot=data['queue_snapshot'],
        queue=queue,
        now=now
    )


@import_bp.route('/queue-status.json')
@login_required
def queue_status_json():
    """Return import queue status for polling clients and MCP workflows."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    queue = current_app.config.get('import_queue')
    if not queue:
        return jsonify({'error': 'Import queue not initialized'}), 503

    data = _import_queue_status_data(queue)
    return jsonify({
        'stats': data['stats'],
        'queue': data['queue_snapshot'],
        'active_jobs': [_import_job_payload(job) for job in data['active_jobs']],
        'recent_jobs': [_import_job_payload(job) for job in data['recent_jobs']],
    })


@import_bp.route('/jobs/<int:job_id>/retry', methods=['POST'])
@login_required
def retry_import_job(job_id):
    """Retry a failed or dead-letter import job from the admin queue view."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    reset_attempts = request.form.get('reset_attempts') == '1'
    if request.is_json:
        reset_attempts = bool((request.get_json(silent=True) or {}).get('reset_attempts'))

    try:
        result = automation.retry_import_job(job_id, reset_attempts=reset_attempts)
    except automation.AutomationError as exc:
        current_app.logger.error("Import job retry failed for job %s: %s", job_id, exc, exc_info=True)
        return jsonify({
            'error': 'Import job retry failed. Check the server logs.',
            'code': 'import_job_retry_failed',
        }), 400
    return jsonify(result)
