"""
Core routes for the Music Round application
"""
import os
import json
import time
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, jsonify, abort, send_from_directory
from flask_login import login_required, current_user
from musicround.models import db, Round, Song
from musicround.config import Config
import requests
import traceback
from musicround.helpers.auth_helpers import oauth, update_oauth_tokens
from musicround.helpers.spotify_helper import get_spotify_token, get_spotify_user_info
from datetime import datetime

core_bp = Blueprint('core', __name__)

@core_bp.route('/')
def index():
    """
    If user is not logged in, show login.
    Otherwise, show homepage with user info.
    """
    if not current_user.is_authenticated:
        return redirect(url_for('users.login'))
    
    return render_template('homepage.html', user_info={'display_name': current_user.username})

@core_bp.route('/search', methods=['GET'])
@login_required
def search():
    """
    Show search page for Spotify
    """
    return render_template('service_search.html', 
                          service_name='Spotify',
                          search_results_url=url_for('core.search_results'),
                          track_import_url=url_for('import_songs.import_song'),
                          album_import_url=url_for('import_songs.import_album'),
                          playlist_import_url=url_for('import_songs.import_playlist'),
                          url_placeholder="https://open.spotify.com/track/...")

@core_bp.route('/search-results', methods=['POST'])
@login_required
def search_results():
    """Process Spotify search and display results using Authlib"""
    if not current_user.spotify_token:
        current_app.logger.warning(f"User {current_user.id} does not have a Spotify token for search.")
        flash("Please connect your Spotify account to search.", "warning")
        return redirect(url_for('users.spotify_auth'))

    # Prepare Authlib token object from current_user
    expires_at_timestamp = None
    if current_user.spotify_token_expiry:
        if isinstance(current_user.spotify_token_expiry, datetime):
            expires_at_timestamp = int(current_user.spotify_token_expiry.timestamp())
        else:
            try: # Should be a datetime object from DB, but being defensive
                expires_at_timestamp = int(datetime.fromisoformat(str(current_user.spotify_token_expiry)).timestamp())
            except ValueError:
                current_app.logger.warning(f"Could not parse spotify_token_expiry for user {current_user.id}.")

    authlib_token = {
        'access_token': current_user.spotify_token,
        'refresh_token': current_user.spotify_refresh_token,
        'token_type': 'Bearer',
        'expires_at': expires_at_timestamp
    }
    
    if current_user.spotify_token_expiry and current_user.spotify_token_expiry < datetime.now():
        current_app.logger.info(f"User {current_user.id}'s Spotify token appears expired. Authlib will attempt refresh.")

    search_api_url = 'https://api.spotify.com/v1/search'
    search_term = request.form.get('search_term', '')
    if not search_term:
        return redirect(url_for('core.search'))
    
    try:
        current_app.logger.info(f"Searching Spotify for: '{search_term}' for user {current_user.id}")
        
        search_strategies = [
            {'q': search_term, 'type': 'track,album,playlist', 'limit': 10},
            {'q': f'artist:{search_term}', 'type': 'track,album,playlist', 'limit': 10},
            {'q': f'track:{search_term}', 'type': 'track,album,playlist', 'limit': 10},
            {'q': search_term, 'type': 'track,album,playlist', 'limit': 10, 'market': 'US'},
            {'q': f'{search_term}', 'type': 'track,album,playlist', 'limit': 20, 'include_external': 'audio'}
        ]
        
        tracks = []
        albums = []
        playlists = []
        results_found = False

        for strategy_params in search_strategies:
            current_app.logger.info(f"Trying search strategy: {strategy_params} for user {current_user.id}")
            try:
                response = oauth.spotify.get(search_api_url, params=strategy_params, token=authlib_token)
                response.raise_for_status()
                results = response.json()
                
                # Check if the token was refreshed by Authlib
                # The new token would be in oauth.spotify.token
                if oauth.spotify.token and oauth.spotify.token.get('access_token') != authlib_token.get('access_token'):
                    current_app.logger.info(f"Spotify token refreshed for user {current_user.id}.")
                    if update_oauth_tokens(current_user, oauth.spotify.token, 'spotify'):
                        # Update the local authlib_token variable to use the new token for subsequent requests in this function
                        authlib_token = oauth.spotify.token 
                        current_app.logger.info(f"Refreshed Spotify token saved and authlib_token updated for user {current_user.id}.")
                    else:
                        current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id}.")

                if results:
                    if 'tracks' in results and results['tracks']['items']:
                        results_found = True
                        for item in results['tracks']['items']:
                            if item is None or 'id' not in item or 'artists' not in item or 'album' not in item:
                                continue
                            try:    
                                artist_names = [artist['name'] for artist in item['artists']]
                                image_url = None
                                if 'album' in item and item['album'] and 'images' in item['album'] and item['album']['images']:
                                    image_url = item['album']['images'][0]['url']
                                album_name = item['album']['name'] if 'album' in item and item['album'] and 'name' in item['album'] else 'Unknown Album'
                                tracks.append({
                                    'id': item['id'], 'name': item['name'], 'artist': ', '.join(artist_names),
                                    'album': album_name, 'image_url': image_url,
                                    'preview_url': item.get('preview_url'), 'duration_ms': item.get('duration_ms', 0)
                                })
                            except Exception as item_error:
                                current_app.logger.error(f"Error processing track item: {str(item_error)} for item {item}")

                    if 'albums' in results and results['albums']['items']:
                        results_found = True
                        for item in results['albums']['items']:
                            if item is None or 'id' not in item or 'artists' not in item:
                                continue
                            try:
                                artist_names = [artist['name'] for artist in item['artists']]
                                image_url = None
                                if 'images' in item and item['images']:
                                    image_url = item['images'][0]['url']
                                albums.append({
                                    'id': item['id'], 'name': item['name'], 'artist': ', '.join(artist_names),
                                    'image_url': image_url, 'total_tracks': item.get('total_tracks', 0)
                                })
                            except Exception as item_error:
                                current_app.logger.error(f"Error processing album item: {str(item_error)} for item {item}")
                    
                    if 'playlists' in results and results['playlists']['items']:
                        results_found = True
                        for item in results['playlists']['items']:
                            if item is None or 'id' not in item or 'owner' not in item:
                                continue
                            try:
                                image_url = None
                                if 'images' in item and item['images']:
                                    image_url = item['images'][0]['url']
                                track_count = item['tracks']['total'] if 'tracks' in item and item['tracks'] else 0
                                owner_name = item['owner'].get('display_name') or item['owner'].get('id', 'Unknown')
                                playlists.append({
                                    'id': item['id'], 'name': item['name'], 'owner': owner_name,
                                    'image_url': image_url, 'tracks': track_count
                                })
                            except Exception as item_error:
                                current_app.logger.error(f"Error processing playlist item: {str(item_error)} for item {item}")
                
                if results_found:
                    current_app.logger.info(f"Results found with strategy: {strategy_params}")
                    break 
            
            except requests.exceptions.HTTPError as http_err:
                current_app.logger.error(f"HTTP error with search strategy {strategy_params} for user {current_user.id}: {http_err}")
                if hasattr(http_err, 'response') and http_err.response is not None:
                    current_app.logger.error(f"Response status: {http_err.response.status_code}, Response text: {http_err.response.text}")
                    if http_err.response.status_code == 401:
                        current_app.logger.warning(f"Spotify token invalid/expired for user {current_user.id} during search. Clearing tokens.")
                        current_user.spotify_token = None
                        current_user.spotify_refresh_token = None
                        current_user.spotify_token_expiry = None
                        current_user.spotify_id = None 
                        db.session.commit()
                        flash("Your Spotify session has expired or is invalid. Please reconnect your Spotify account.", "warning")
                        return redirect(url_for('users.spotify_auth'))
                continue
            except Exception as search_error:
                current_app.logger.error(f"Error with search strategy {strategy_params} for user {current_user.id}: {str(search_error)}")
                current_app.logger.error(traceback.format_exc())
                continue
        
        if not results_found:
            current_app.logger.info(f"No results from primary searches for user {current_user.id}, trying fallback approaches")
            fallback_strategies = [
                {'q': search_term, 'type': 'track,album,playlist', 'limit': 20, 'market': 'US'},
                {'q': f'{search_term}*', 'type': 'track', 'limit': 20},
                {'q': search_term, 'type': 'track', 'limit': 50}
            ]
            for strategy_params in fallback_strategies:
                current_app.logger.info(f"Trying fallback strategy: {strategy_params} for user {current_user.id}")
                try:
                    response = oauth.spotify.get(search_api_url, params=strategy_params, token=authlib_token)
                    response.raise_for_status()
                    results = response.json()

                    # Check if the token was refreshed by Authlib
                    if oauth.spotify.token and oauth.spotify.token.get('access_token') != authlib_token.get('access_token'):
                        current_app.logger.info(f"Spotify token refreshed during fallback for user {current_user.id}.")
                        if update_oauth_tokens(current_user, oauth.spotify.token, 'spotify'):
                            # Update the local authlib_token variable
                            authlib_token = oauth.spotify.token
                            current_app.logger.info(f"Refreshed Spotify token saved (fallback) and authlib_token updated for user {current_user.id}.")
                        else:
                             current_app.logger.error(f"Failed to save refreshed Spotify token (fallback) for user {current_user.id}.")

                    if results:
                        if 'tracks' in results and results['tracks']['items']:
                            results_found = True
                            for item in results['tracks']['items']:
                                if item is None or 'id' not in item or 'artists' not in item:
                                    continue
                                try:
                                    artist_names = [artist.get('name', 'Unknown Artist') for artist in item.get('artists', [])]
                                    album_name = "Unknown Album"
                                    image_url = None
                                    if 'album' in item and item['album']:
                                        album_name = item['album'].get('name', 'Unknown Album')
                                        if 'images' in item['album'] and item['album']['images']:
                                            image_url = item['album']['images'][0].get('url')
                                    tracks.append({
                                        'id': item['id'], 'name': item.get('name', 'Unknown Track'),
                                        'artist': ', '.join(artist_names), 'album': album_name, 'image_url': image_url,
                                        'preview_url': item.get('preview_url'), 'duration_ms': item.get('duration_ms', 0)
                                    })
                                except Exception as item_error:
                                     current_app.logger.error(f"Error processing fallback track item: {str(item_error)} for item {item}")
                        if results_found:
                            current_app.logger.info(f"Results found with fallback strategy: {strategy_params}")
                            break 
                except requests.exceptions.HTTPError as http_err:
                    current_app.logger.error(f"HTTP error with fallback strategy {strategy_params} for user {current_user.id}: {http_err}")
                    if hasattr(http_err, 'response') and http_err.response is not None:
                        current_app.logger.error(f"Response status: {http_err.response.status_code}, Response text: {http_err.response.text}")
                        if http_err.response.status_code == 401:
                            current_app.logger.warning(f"Spotify token invalid/expired for user {current_user.id} during fallback. Clearing tokens.")
                            current_user.spotify_token = None
                            current_user.spotify_refresh_token = None
                            current_user.spotify_token_expiry = None
                            current_user.spotify_id = None
                            db.session.commit()
                            flash("Your Spotify session has expired or is invalid. Please reconnect your Spotify account.", "warning")
                            return redirect(url_for('users.spotify_auth'))
                    continue
                except Exception as fallback_error:
                    current_app.logger.error(f"Error with fallback strategy {strategy_params} for user {current_user.id}: {str(fallback_error)}")
                    current_app.logger.error(traceback.format_exc())
                    continue
        
        unique_tracks = list({track['id']: track for track in tracks}.values())
        unique_albums = list({album['id']: album for album in albums}.values())
        unique_playlists = list({playlist['id']: playlist for playlist in playlists}.values())
        
        current_app.logger.info(f"Search for '{search_term}' by user {current_user.id} yielded: {len(unique_tracks)} tracks, {len(unique_albums)} albums, {len(unique_playlists)} playlists")
        
        return render_template('service_search_results.html',
                             service_name='Spotify', search_term=search_term,
                             tracks=unique_tracks, albums=unique_albums, playlists=unique_playlists,
                             track_import_url=url_for('import_songs.import_song'),
                             album_import_url=url_for('import_songs.import_album'),
                             playlist_import_url=url_for('import_songs.import_playlist'),
                             track_id_field='song_id', album_id_field='album_id',
                             playlist_id_field='playlist_id', tracks_label='Tracks',
                             has_preview=True, search_url=url_for('core.search'))
    
    except Exception as e:
        current_app.logger.error(f"Generic Spotify search error for user {current_user.id} ({search_term}): {str(e)}")
        current_app.logger.error(traceback.format_exc())
        if "token" in str(e).lower() or "auth" in str(e).lower() or "401" in str(e):
             flash("An authentication error occurred with Spotify. Please try reconnecting your account.", "danger")
             return redirect(url_for('users.spotify_auth'))
        return render_template('error.html', 
                              error_message="An error occurred while searching Spotify.",
                              error_details=str(e),
                              back_url=url_for('core.search'))

@core_bp.route('/view-songs')
@login_required
def view_songs():
    """
    Show all songs in database
    """
    from musicround.models import Song, Tag
    
    songs = Song.query.all()
    tags = Tag.query.all()
    
    return render_template('view_songs.html', songs=songs, tags=tags)

@core_bp.route('/data/<path:filepath>')
@login_required
def serve_user_audio(filepath):
    """
    Serve user custom audio files from the data directory
    """
    if '..' in filepath:
        abort(404)
        
    if 'custommp3/' in filepath:
        parts = filepath.split('/')
        if len(parts) >= 2 and parts[0] == 'custommp3':
            username = parts[1]
            if username != current_user.username and not current_user.is_admin:
                abort(403)
    
    return send_from_directory('/data', filepath)