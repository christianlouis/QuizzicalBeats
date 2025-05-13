from flask import Blueprint, render_template, redirect, url_for, request, current_app, flash, session, jsonify
from musicround.models import Song, db
import deezer
import musicbrainzngs
import requests
import openai
import os
import json
from musicround.helpers.metadata import get_song_metadata_by_isrc
from musicround.helpers.import_helper import ImportHelper

deezer_bp = Blueprint('deezer', __name__)

@deezer_bp.route('/deezer-search', methods=['GET'])
def deezer_search():
    """Display Deezer search form"""
    return render_template('service_search.html',
                         service_name='Deezer',
                         search_results_url=url_for('deezer.deezer_search_results'),
                         browse_playlists_url=url_for('deezer.browse_deezer_playlists'),
                         track_import_url=url_for('deezer.import_deezer_track_result'),
                         album_import_url=url_for('deezer.import_deezer_album_result'),
                         playlist_import_url=url_for('deezer.import_deezer_playlist_result'),
                         url_placeholder='https://www.deezer.com/...')

@deezer_bp.route('/deezer-search-results', methods=['POST'])
def deezer_search_results():
    """Search for tracks, albums, and playlists on Deezer"""
    search_term = request.form['search_term']
    deezer_client = current_app.config['deezer']
    
    try:
        tracks = deezer_client.search_tracks(search_term)
        albums = deezer_client.search_albums(search_term)
        playlists = deezer_client.search_playlists(search_term)
        
        # Format tracks for the template
        formatted_tracks = []
        for track in tracks:
            if track:
                formatted_tracks.append({
                    'id': track.get('id'),
                    'name': track.get('title'),
                    'artist': track.get('artist', {}).get('name', 'Unknown Artist') if track.get('artist') else 'Unknown Artist',
                    'album': track.get('album', {}).get('title', '') if track.get('album') else '',
                    'image_url': track.get('album', {}).get('cover_medium') if track.get('album') else None,
                    'preview_url': track.get('preview')
                })
                
        # Format albums for the template
        formatted_albums = []
        for album in albums:
            if album:
                formatted_albums.append({
                    'id': album.get('id'),
                    'name': album.get('title'),
                    'artist': album.get('artist', {}).get('name', 'Unknown Artist') if album.get('artist') else 'Unknown Artist',
                    'image_url': album.get('cover_medium'),
                    'track_count': album.get('nb_tracks')
                })
                
        # Format playlists for the template
        formatted_playlists = []
        for playlist in playlists:
            if playlist:
                formatted_playlists.append({
                    'id': playlist.get('id'),
                    'name': playlist.get('title'),
                    'owner': playlist.get('user', {}).get('name', 'Unknown') if playlist.get('user') else 'Unknown',
                    'image_url': playlist.get('picture_medium'),
                    'track_count': playlist.get('nb_tracks')
                })
                
        # Use the standardized template for search results
        return render_template('service_search_results.html',
                             service_name='Deezer',
                             search_term=search_term,
                             tracks=formatted_tracks,
                             albums=formatted_albums,
                             playlists=formatted_playlists,
                             tracks_label='Tracks',
                             search_url=url_for('deezer.deezer_search'),
                             has_preview=True,
                             track_import_url=url_for('deezer.import_deezer_track_result'),
                             track_id_field='track_id',
                             album_import_url=url_for('deezer.import_deezer_album_result'),
                             album_id_field='album_id',
                             playlist_import_url=url_for('deezer.import_deezer_playlist_result'),
                             playlist_id_field='playlist_id')
                             
    except Exception as e:
        current_app.logger.error(f"Deezer search error: {e}")
        flash("Error searching Deezer. Please try again.", "danger")
        return redirect(url_for('deezer.deezer_search'))

@deezer_bp.route('/import-deezer-track', methods=['GET'])
def import_deezer_track():
    """Display form to import a single track from Deezer"""
    return render_template('service_import.html',
                         service_name='Deezer',
                         item_type='Track',
                         url_example_prefix='https://www.deezer.com/track/',
                         url_example_id='12345678',
                         id_field='track_id',
                         form_action=url_for('deezer.import_deezer_track_result'),
                         back_url=url_for('deezer.deezer_search'))

@deezer_bp.route('/import-deezer-track-result', methods=['POST'])
def import_deezer_track_result():
    """Process the import of a single track from Deezer using the unified ImportHelper"""
    track_id = request.form['track_id']
    
    # Use the unified ImportHelper to handle track import
    result = ImportHelper.import_item('deezer', 'track', track_id)
    
    if result['imported_count'] > 0:
        flash(f'Successfully imported {result["imported_count"]} song from Deezer!', 'success')
    elif result['skipped_count'] > 0:
        flash('Song was already in the database.', 'info')
    else:
        flash(f'Error importing song: {", ".join(result["errors"])}', 'danger')
    
    return redirect(url_for('core.view_songs'))

# Legacy function kept for backward compatibility
def import_deezer_track_result_helper(track_id):
    """Helper function to import a single track from Deezer"""
    result = ImportHelper.import_item('deezer', 'track', track_id)
    return result['imported_count'] > 0

@deezer_bp.route('/import-deezer-playlist', methods=['GET', 'POST'])
def import_deezer_playlist():
    """Display form to import all tracks from a Deezer playlist"""
    if request.method == 'POST':
        playlist_id = request.form.get('playlist_id')
        if playlist_id:
            # Use the unified ImportHelper to handle playlist import
            result = ImportHelper.import_item('deezer', 'playlist', playlist_id)
            
            if result['imported_count'] > 0:
                flash(f'Successfully imported {result["imported_count"]} songs from Deezer playlist!', 'success')
            elif result['skipped_count'] > 0 and result['error_count'] == 0:
                flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
            elif result['error_count'] > 0:
                flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
            else:
                flash(f'Error importing playlist: {", ".join(result["errors"])}', 'danger')
                
            return redirect(url_for('core.view_songs'))
        else:
            flash("Playlist ID is required.", 'error')

    return render_template('service_import.html',
                         service_name='Deezer',
                         item_type='Playlist',
                         url_example_prefix='https://www.deezer.com/playlist/',
                         url_example_id='9876543',
                         id_field='playlist_id',
                         form_action=url_for('deezer.import_deezer_playlist_result'),
                         back_url=url_for('deezer.deezer_search'))

@deezer_bp.route('/import-deezer-playlist-result', methods=['POST'])
def import_deezer_playlist_result():
    """Process the import of all tracks from a Deezer playlist using the unified ImportHelper"""
    playlist_id = request.form['playlist_id']
    
    # Use the unified ImportHelper to handle playlist import
    result = ImportHelper.import_item('deezer', 'playlist', playlist_id)
    
    if result['imported_count'] > 0:
        flash(f'Successfully imported {result["imported_count"]} songs from Deezer playlist!', 'success')
    elif result['skipped_count'] > 0 and result['error_count'] == 0:
        flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
    elif result['error_count'] > 0:
        flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
    else:
        flash(f'Error importing playlist: {", ".join(result["errors"])}', 'danger')
    
    return redirect(url_for('core.view_songs'))

@deezer_bp.route('/import-deezer-album', methods=['GET'])
def import_deezer_album():
    """Display form to import all tracks from a Deezer album"""
    return render_template('service_import.html',
                         service_name='Deezer',
                         item_type='Album',
                         url_example_prefix='https://www.deezer.com/album/',
                         url_example_id='1234567',
                         id_field='album_id',
                         form_action=url_for('deezer.import_deezer_album_result'),
                         back_url=url_for('deezer.deezer_search'))

@deezer_bp.route('/import-deezer-album-result', methods=['POST'])
def import_deezer_album_result():
    """Process the import of all tracks from a Deezer album using the unified ImportHelper"""
    album_id = request.form['album_id']
    
    # Use the unified ImportHelper to handle album import
    result = ImportHelper.import_item('deezer', 'album', album_id)
    
    if result['imported_count'] > 0:
        flash(f'Successfully imported {result["imported_count"]} songs from Deezer album!', 'success')
    elif result['skipped_count'] > 0 and result['error_count'] == 0:
        flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
    elif result['error_count'] > 0:
        flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
    else:
        flash(f'Error importing album: {", ".join(result["errors"])}', 'danger')
    
    return redirect(url_for('core.view_songs'))

@deezer_bp.route('/browse-deezer-playlists')
def browse_deezer_playlists():
    """Browse popular playlists on Deezer"""
    deezer_client = current_app.config['deezer']
    
    try:
        playlists = deezer_client.get_popular_playlists()
        return render_template('browse_deezer_playlists.html', playlists=playlists)
    except Exception as e:
        current_app.logger.error(f"Error browsing Deezer playlists: {e}")
        flash("Error loading Deezer playlists. Please try again.", "danger")
        return render_template('browse_deezer_playlists.html', playlists=[])