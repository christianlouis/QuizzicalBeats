"""
Import routes for the Music Round application
"""
import json
import time
import random
from flask import Blueprint, render_template, redirect, url_for, request, current_app, flash, session, jsonify
from musicround.models import Song, db
from musicround.routes.import_songs import import_pl
from musicround.helpers.import_helper import ImportHelper

import_bp = Blueprint('import', __name__, url_prefix='/import')

def fetch_all_user_playlists(sp, user_id, limit=50):
    """
    Fetch all playlists from a specific Spotify user account with pagination
    
    Args:
        sp: Spotify API client
        user_id: Spotify user ID to fetch playlists from
        limit: Number of playlists to fetch per request (max 50)
        
    Returns:
        List of all playlists from the specified user
    """
    all_playlists = []
    offset = 0
    total = None
    
    start_time = time.time()
    current_app.logger.info(f"Started fetching playlists for user '{user_id}'")
    
    # Hard limit to prevent infinite loops (should never be needed if API works correctly)
    max_loops = 100
    loop_count = 0
    
    while loop_count < max_loops:
        loop_count += 1
        try:
            # Use Spotify API to get playlists with pagination
            current_app.logger.info(f"Fetching playlists for {user_id} with offset={offset}, limit={limit}, loop={loop_count}")
            results = sp.user_playlists(user_id, limit=limit, offset=offset)
            
            # Log raw API response for debugging (only first few characters to avoid flooding logs)
            response_sample = str(results)[:500] + '...' if len(str(results)) > 500 else str(results)
            current_app.logger.debug(f"API response sample: {response_sample}")
            
            # If first request, get and validate the total
            if total is None:
                total = results.get('total', 0)
                current_app.logger.info(f"User '{user_id}' has {total} playlists in total according to API")
                if total == 0:
                    current_app.logger.warning(f"API reported 0 total playlists for {user_id} - possible API error")
            
            # Add the current batch of playlists to our collection
            playlists_batch = results.get('items', [])
            batch_count = len(playlists_batch)
            all_playlists.extend(playlists_batch)
            
            current_app.logger.info(f"Batch for {user_id}: offset={offset}, received={batch_count} playlists")
            
            # If we didn't get any playlists in this batch, something is wrong
            if batch_count == 0:
                current_app.logger.warning(f"Received 0 playlists for {user_id} at offset {offset} - possible API error")
                if 'items' not in results:
                    current_app.logger.warning(f"Missing 'items' key in API response for {user_id}")
                break
            
            # Break if we received fewer items than requested (last page)
            if batch_count < limit:
                current_app.logger.info(f"Reached end of results for {user_id} (received {batch_count} < limit {limit})")
                break
                
            # Update offset for next batch
            offset += batch_count
            
            # Log progress
            current_app.logger.info(f"Fetched {len(playlists_batch)} playlists for '{user_id}', progress: {len(all_playlists)}/{total}")
            
            # Break if we've reached or exceeded the total number of playlists
            if offset >= total:
                current_app.logger.info(f"Reached total {total} playlists for {user_id} at offset {offset}")
                break
                
            # Break if we've exhausted all playlists (next URL is None)
            if not results.get('next'):
                current_app.logger.info(f"No more 'next' URL for {user_id} at offset {offset}")
                # Check if we should have more results based on 'total'
                if offset < total:
                    current_app.logger.warning(
                        f"API inconsistency: 'next' is None but we've only fetched {offset} out of {total} playlists"
                    )
                break
                
        except Exception as e:
            current_app.logger.error(f"Error fetching playlists for user '{user_id}' at offset {offset}: {str(e)}")
            # Try to get more specific error information
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            break
    
    # Check if we hit the max loops limit
    if loop_count >= max_loops:
        current_app.logger.warning(f"Reached maximum loop count ({max_loops}) for user {user_id}")
    
    end_time = time.time()
    duration = int((end_time - start_time) * 1000)
    current_app.logger.info(f"Completed fetching {len(all_playlists)}/{total} playlists for user '{user_id}' in {duration}ms")
    
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
def import_official_playlists():
    """Display and import official Spotify playlists from multiple regional accounts"""
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
    sp = current_app.config['sp']
    
    # Handle POST request for importing a playlist
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        # Use the new unified ImportHelper
        result = ImportHelper.import_item('spotify', 'playlist', playlist_id)
        
        if result['imported_count'] > 0:
            flash(f'Successfully imported {result["imported_count"]} songs from official Spotify playlist!', 'success')
        elif result['skipped_count'] > 0 and result['error_count'] == 0:
            flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
        elif result['error_count'] > 0:
            flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
        else:
            flash(f'Error importing playlist: {", ".join(result["errors"])}', 'danger')
            
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
            
            # Fetch all playlists for this account
            account_playlists = fetch_all_user_playlists(sp, account)
            
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
    
    # Get the bearer token from the session to display in the form
    session_bearer_token = session.get('direct_bearer_token', '')
    spotify_username = session.get('direct_spotify_username')
    
    return render_template(
        'import_official_playlists.html',
        playlists=all_playlists,
        filter_keywords=filter_keywords,
        selected_account=selected_account,
        spotify_accounts=spotify_accounts,
        debug_info=debug_info,
        debug_mode=debug_mode,
        session_bearer_token=session_bearer_token,
        spotify_username=spotify_username,
        direct_mode=False
    )

@import_bp.route('/direct-official-playlists', methods=['GET', 'POST'])
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
        # Use the new unified ImportHelper
        result = ImportHelper.import_item('spotify', 'playlist', playlist_id)
        
        if result['imported_count'] > 0:
            flash(f'Successfully imported {result["imported_count"]} songs from official Spotify playlist!', 'success')
        elif result['skipped_count'] > 0 and result['error_count'] == 0:
            flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
        elif result['error_count'] > 0:
            flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
        else:
            flash(f'Error importing playlist: {", ".join(result["errors"])}', 'danger')
            
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
        flash(f'Error retrieving playlists from Spotify: {str(e)}', 'danger')
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
        spotify_username=session.get('direct_spotify_username')
    )

@import_bp.route('/test-spotify-client', methods=['GET'])
def test_spotify_client():
    """Test route to compare different Spotify client implementations"""
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
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
        sp = current_app.config['sp']
        start_time = time.time()
        
        current_app.logger.info(f"Testing spotipy implementation for account {account}")
        spotipy_playlists = fetch_all_user_playlists(sp, account)
        
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        results['spotipy']['playlists'] = spotipy_playlists
        results['spotipy']['count'] = len(spotipy_playlists)
        results['spotipy']['time_ms'] = duration_ms
        
        # Get total from first API call if available
        if spotipy_playlists:
            first_result = sp.user_playlists(account, limit=1)
            results['spotipy']['total'] = first_result.get('total', 'unknown')
            
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error testing spotipy: {e}")
        current_app.logger.error(traceback.format_exc())
        results['spotipy']['error'] = str(e)
    
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
            
            # Get total if available from response
            if direct_playlists and len(direct_playlists) > 0:
                first_result = direct_client.user_playlists(account, limit=1)
                results['direct']['total'] = first_result.get('total', 'unknown')
            
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error testing direct client: {e}")
        current_app.logger.error(traceback.format_exc())
        results['direct']['error'] = str(e)
    
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
def get_raw_playlists():
    """
    Get raw playlists from Spotify without any pagination logic.
    This helps diagnose issues with the playlist retrieval.
    """
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
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
    
    # Test spotipy raw response
    try:
        sp = current_app.config['sp']
        current_app.logger.info(f"Getting raw playlists with spotipy for {account}, limit={limit}, offset={offset}")
        raw_result = sp.user_playlists(account, limit=limit, offset=offset)
        results['spotipy']['raw_response'] = raw_result
    except Exception as e:
        import traceback
        current_app.logger.error(f"Error getting raw spotipy playlists: {e}")
        current_app.logger.error(traceback.format_exc())
        results['spotipy']['error'] = str(e)
    
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
        results['direct']['error'] = str(e)
    
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
def direct_spotify_auth():
    """
    Allow users to manually enter a Spotify bearer token for direct API access.
    This bypasses the OAuth flow and is useful when API limitations are in place.
    """
    error = None
    success = None
    
    if request.method == 'POST':
        bearer_token = request.form.get('bearer_token')
        if bearer_token:
            try:
                # Store the token in session
                session['direct_bearer_token'] = bearer_token
                
                # Test the token with a simple request
                from musicround.helpers.spotify_direct import SpotifyDirectClient
                client = SpotifyDirectClient(bearer_token=bearer_token)
                
                # Try to get current user info as a test
                result = client._make_api_request("me")
                
                if result and 'id' in result:
                    session['direct_spotify_user'] = result['id']
                    session['direct_spotify_username'] = result.get('display_name', result['id'])
                    success = f"Successfully authenticated as {session['direct_spotify_username']}"
                else:
                    error = "Token validation failed. Please check the token and try again."
            except Exception as e:
                current_app.logger.error(f"Error validating bearer token: {e}")
                error = f"Error: {str(e)}"
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
def update_direct_token():
    """Update the direct bearer token and redirect back to the referring page"""
    # Get return URL from form or default to playlist page
    return_url = request.form.get('return_url') or url_for('import.direct_official_playlists')
    
    # Check if clearing token was requested
    if request.form.get('clear_token'):
        session.pop('direct_bearer_token', None)
        session.pop('direct_spotify_user', None)
        session.pop('direct_spotify_username', None)
        flash('Bearer token cleared successfully', 'success')
        return redirect(return_url)
    
    # Get bearer token from form
    bearer_token = request.form.get('bearer_token')
    if not bearer_token:
        flash('No bearer token provided', 'warning')
        return redirect(return_url)
    
    try:
        # Store the token in session
        session['direct_bearer_token'] = bearer_token
        
        # Test the token with a simple request
        from musicround.helpers.spotify_direct import SpotifyDirectClient
        client = SpotifyDirectClient(bearer_token=bearer_token)
        
        # Try to get current user info as a test
        result = client._make_api_request("me")
        
        if result and 'id' in result:
            session['direct_spotify_user'] = result['id']
            session['direct_spotify_username'] = result.get('display_name', result['id'])
            flash(f'Successfully authenticated as {session["direct_spotify_username"]}', 'success')
        else:
            flash('Token validation failed. Please check the token and try again.', 'error')
    except Exception as e:
        current_app.logger.error(f"Error validating bearer token: {e}")
        flash(f'Error validating token: {str(e)}', 'error')
    
    return redirect(return_url)