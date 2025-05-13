import random
import os
import requests
import json
from flask import Blueprint, session, redirect, request, render_template, url_for, current_app, flash
from musicround.models import Song, db
from musicround.helpers.metadata import get_song_metadata_by_isrc
from musicround.helpers.import_helper import ImportHelper

import_songs_bp = Blueprint('import_songs', __name__, url_prefix='/import')

# Legacy function retained for backward compatibility
def import_track(track_id):
    """Legacy helper function that now uses the new ImportHelper"""
    result = ImportHelper.import_item('spotify', 'track', track_id)
    return result['imported_count'] > 0

# Legacy function retained for backward compatibility
def import_pl(playlist_id):
    """Legacy helper function that now uses the new ImportHelper"""
    ImportHelper.import_item('spotify', 'playlist', playlist_id)

# Legacy function retained for backward compatibility
def import_al(album_id):
    """Legacy helper function that now uses the new ImportHelper"""
    ImportHelper.import_item('spotify', 'album', album_id)

@import_songs_bp.route('/song', methods=['GET', 'POST'])
def import_song():
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
    if request.method == 'POST':
        track_id = request.form['song_id']
        result = ImportHelper.import_item('spotify', 'track', track_id)
        
        if result['imported_count'] > 0:
            flash(f'Successfully imported {result["imported_count"]} song!', 'success')
        elif result['skipped_count'] > 0:
            flash('Song was already in the database.', 'info')
        else:
            flash(f'Error importing song: {", ".join(result["errors"])}', 'danger')
            
        return redirect(url_for('core.view_songs'))
        
    return render_template('service_import.html',
                         service_name='Spotify',
                         item_type='Track',
                         url_example_prefix='https://open.spotify.com/track/',
                         url_example_id='6rqhFgbbKwnb9MLmUQDhG6',
                         id_field='song_id',
                         form_action=url_for('import_songs.import_song'),
                         back_url=url_for('core.search'))

@import_songs_bp.route('/playlist', methods=['GET', 'POST'])
def import_playlist():
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
    if request.method == 'POST':
        playlist_id = request.form['playlist_id']
        result = ImportHelper.import_item('spotify', 'playlist', playlist_id)
        
        if result['imported_count'] > 0:
            flash(f'Successfully imported {result["imported_count"]} songs from playlist!', 'success')
        elif result['skipped_count'] > 0 and result['error_count'] == 0:
            flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
        elif result['error_count'] > 0:
            flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
        else:
            flash(f'Error importing playlist: {", ".join(result["errors"])}', 'danger')
            
        return redirect(url_for('core.view_songs'))
        
    return render_template('service_import.html',
                         service_name='Spotify',
                         item_type='Playlist',
                         url_example_prefix='https://open.spotify.com/playlist/',
                         url_example_id='37i9dQZF1DXcBWIGoYBM5M',
                         id_field='playlist_id',
                         form_action=url_for('import_songs.import_playlist'),
                         back_url=url_for('core.search'))

@import_songs_bp.route('/album', methods=['GET', 'POST'])
def import_album():
    if 'access_token' not in session:
        return redirect(url_for('users.login'))
    
    if request.method == 'POST':
        album_id = request.form['album_id']
        result = ImportHelper.import_item('spotify', 'album', album_id)
        
        if result['imported_count'] > 0:
            flash(f'Successfully imported {result["imported_count"]} songs from album!', 'success')
        elif result['skipped_count'] > 0 and result['error_count'] == 0:
            flash(f'All {result["skipped_count"]} songs were already in the database.', 'info')
        elif result['error_count'] > 0:
            flash(f'Encountered {result["error_count"]} errors during import.', 'warning')
        else:
            flash(f'Error importing album: {", ".join(result["errors"])}', 'danger')
            
        return redirect(url_for('core.view_songs'))
        
    return render_template('service_import.html',
                         service_name='Spotify',
                         item_type='Album',
                         url_example_prefix='https://open.spotify.com/album/',
                         url_example_id='4aawyAB9vmqN3uQ7FjRGTy',
                         id_field='album_id',
                         form_action=url_for('import_songs.import_album'),
                         back_url=url_for('core.search'))