"""
Import routes for the Music Round application
"""
import json
import time
import random
from flask import Blueprint, render_template, redirect, url_for, request, current_app, flash, session, jsonify
from musicround.models import Song, db
from musicround.routes.import_songs import import_pl, import_track
from musicround.helpers.auth_helpers import oauth  # Import the oauth object

import_bp = Blueprint('import', __name__, url_prefix='/import')

def fetch_all_user_playlists(user_id, limit=50):  # Removed sp argument
    """
    Fetch all playlists from a specific Spotify user account with pagination
    
    Args:
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
    
    while total is None or offset < total:
        try:
            # Use Spotify API to get playlists with pagination
            # Use oauth.spotify instead of sp
            results = oauth.spotify.get(f'users/{user_id}/playlists', params={'limit': limit, 'offset': offset}).json()
            
            # If first request, get the total
            if total is None:
                total = results['total']
                current_app.logger.info(f"User '{user_id}' has {total} playlists in total")
            
            # Add the current batch of playlists to our collection
            playlists_batch = results.get('items', [])
            all_playlists.extend(playlists_batch)
            
            # Update offset for next batch
            offset += limit
            
            # Log progress
            current_app.logger.info(f"Fetched {len(playlists_batch)} playlists for '{user_id}', progress: {len(all_playlists)}/{total}")
            
            # Break if we've reached the end
            if not results.get('next'):
                break
                
        except Exception as e:
            current_app.logger.error(f"Error fetching playlists for user '{user_id}' at offset {offset}: {e}")
            break
    
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
        return redirect(url_for('auth.login'))
    
    # Handle POST request for importing a playlist
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        from musicround.helpers.import_helper import ImportHelper
        result = ImportHelper.import_item('spotify', 'playlist', playlist_id)

        if result['imported_count'] > 0:
            flash(f"Successfully imported {result['imported_count']} songs from playlist!", 'success')
        elif result['skipped_count'] > 0 and result['error_count'] == 0:
            flash(f"All {result['skipped_count']} songs were already in the database.", 'info')
        elif result['error_count'] > 0:
             flash(f"Playlist import completed with {result['imported_count']} new songs, {result['skipped_count']} skipped, and {result['error_count']} errors.", 'warning')
        else:
            flash('No songs were imported from the playlist. It might be empty or an issue occurred.', 'info')
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
            account_playlists = fetch_all_user_playlists(account)  # Removed sp argument
            
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
    
    return render_template(
        'import_official_playlists.html',
        playlists=all_playlists,
        filter_keywords=filter_keywords,
        selected_account=selected_account,
        spotify_accounts=spotify_accounts,
        debug_info=debug_info,
        debug_mode=debug_mode
    )