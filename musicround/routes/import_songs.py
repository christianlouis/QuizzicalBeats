import random
import os
import requests
import json
from flask import Blueprint, session, redirect, request, render_template, url_for, current_app, flash
from flask_login import login_required, current_user
from musicround.models import Song, db
from musicround.helpers.metadata import get_song_metadata_by_isrc
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.auth_helpers import oauth

import_songs_bp = Blueprint('import_songs', __name__, url_prefix='/import')

# Legacy function retained for backward compatibility
def import_track(track_id):
    """Legacy helper function that now uses the new ImportHelper"""
    result = ImportHelper.import_item(service_name='spotify', item_type='track', item_id=track_id, oauth_spotify=oauth.spotify)
    return result.get('imported_count', 0) > 0

# Legacy function retained for backward compatibility
def import_pl(playlist_id):
    """Legacy helper function that now uses the new ImportHelper"""
    ImportHelper.import_item(service_name='spotify', item_type='playlist', item_id=playlist_id, oauth_spotify=oauth.spotify)

# Legacy function retained for backward compatibility
def import_al(album_id):
    """Legacy helper function that now uses the new ImportHelper"""
    ImportHelper.import_item(service_name='spotify', item_type='album', item_id=album_id, oauth_spotify=oauth.spotify)

@import_songs_bp.route('/song', methods=['GET', 'POST'])
@login_required
def import_song():
    if not current_user.is_authenticated:
        flash("Please log in to import songs.", "warning")
        return redirect(url_for('users.login'))

    if not current_user.spotify_token:
        flash("Please connect your Spotify account to import songs.", "warning")
        return redirect(url_for('users.spotify_auth'))

    if request.method == 'POST':
        track_id = request.form.get('song_id')
        if not track_id:
            flash("No song ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))
            
        result = ImportHelper.import_item(service_name='spotify', item_type='track', item_id=track_id, oauth_spotify=oauth.spotify)
        
        imported_count = result.get('imported_count', 0)
        skipped_count = result.get('skipped_count', 0)
        errors = result.get("errors", [])

        if imported_count > 0:
            flash(f'Successfully imported {imported_count} song!', 'success')
        elif skipped_count > 0:
            flash('Song was already in the database.', 'info')
        else:
            flash(f'Error importing song: {", ".join(errors) if errors else "Unknown error"}', 'danger')
            
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
@login_required
def import_playlist():
    if not current_user.is_authenticated:
        flash("Please log in to import playlists.", "warning")
        return redirect(url_for('users.login'))

    if not current_user.spotify_token:
        flash("Please connect your Spotify account to import playlists.", "warning")
        return redirect(url_for('users.spotify_auth'))
    
    if request.method == 'POST':
        playlist_id = request.form.get('playlist_id')
        if not playlist_id:
            flash("No playlist ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))

        priority = int(request.form.get('priority', 10))
        queue = current_app.config.get('import_queue')
        if not queue:
            flash("Import queue not initialized.", "danger")
            return redirect(url_for('core.view_songs'))

        from musicround.helpers.import_queue import ImportJob

        job = ImportJob(
            priority=priority,
            service_name='spotify',
            item_type='playlist',
            item_id=playlist_id,
            user_id=current_user.id,
        )
        queue.add_job(job)
        flash('Playlist import queued.', 'info')
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
@login_required
def import_album():
    if not current_user.is_authenticated:
        flash("Please log in to import albums.", "warning")
        return redirect(url_for('users.login'))

    if not current_user.spotify_token:
        flash("Please connect your Spotify account to import albums.", "warning")
        return redirect(url_for('users.spotify_auth'))
    
    if request.method == 'POST':
        album_id = request.form.get('album_id')
        if not album_id:
            flash("No album ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))
            
        result = ImportHelper.import_item(service_name='spotify', item_type='album', item_id=album_id, oauth_spotify=oauth.spotify)
        
        imported_count = result.get('imported_count', 0)
        skipped_count = result.get('skipped_count', 0)
        error_count = result.get('error_count', 0)
        errors = result.get("errors", [])

        if imported_count > 0:
            flash(f'Successfully imported {imported_count} songs from album! ({skipped_count} skipped, {error_count} errors).', 'success')
        elif skipped_count > 0 and error_count == 0:
            flash(f'All {skipped_count} songs were already in the database.', 'info')
        elif error_count > 0:
            flash(f'Album import: {imported_count} new, {skipped_count} skipped, {error_count} errors. Errors: {", ".join(errors)}', 'warning')
        else:
            flash(f'Error importing album: {", ".join(errors) if errors else "No songs imported, album might be empty or an unknown issue occurred."}', 'danger')
            
        return redirect(url_for('core.view_songs'))
        
    return render_template('service_import.html',
                         service_name='Spotify',
                         item_type='Album',
                         url_example_prefix='https://open.spotify.com/album/',
                         url_example_id='4aawyAB9vmqN3uQ7FjRGTy',
                         id_field='album_id',
                         form_action=url_for('import_songs.import_album'),
                         back_url=url_for('core.search'))