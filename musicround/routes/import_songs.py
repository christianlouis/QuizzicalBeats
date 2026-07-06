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
from musicround.helpers.spotify_helper import get_spotify_token

import_songs_bp = Blueprint('import_songs', __name__, url_prefix='/import')


def _require_spotify_token(item_type):
    """Redirect users without any usable Spotify token before import."""
    access_token, _token_source = get_spotify_token()
    if access_token:
        return None, access_token

    flash(f"Please connect your Spotify account to import {item_type}.", "warning")
    return redirect(url_for('users.spotify_link')), None


def _safe_spotify_import_error(item_type):
    """Return a browser-safe Spotify import error message."""
    return (
        f'Error importing {item_type} from Spotify. '
        'Please check the Spotify ID and try again.'
    )


# Legacy function retained for backward compatibility
def import_track(track_id):
    """Legacy helper function that now uses the new ImportHelper"""
    access_token, _token_source = get_spotify_token()
    result = ImportHelper.import_item(
        service_name='spotify',
        item_type='track',
        item_id=track_id,
        oauth_spotify=oauth.spotify,
        spotify_token=access_token,
    )
    return result.get('imported_count', 0) > 0

# Legacy function retained for backward compatibility
def import_pl(playlist_id):
    """Legacy helper function that now uses the new ImportHelper"""
    access_token, _token_source = get_spotify_token()
    ImportHelper.import_item(
        service_name='spotify',
        item_type='playlist',
        item_id=playlist_id,
        oauth_spotify=oauth.spotify,
        spotify_token=access_token,
    )

# Legacy function retained for backward compatibility
def import_al(album_id):
    """Legacy helper function that now uses the new ImportHelper"""
    access_token, _token_source = get_spotify_token()
    ImportHelper.import_item(
        service_name='spotify',
        item_type='album',
        item_id=album_id,
        oauth_spotify=oauth.spotify,
        spotify_token=access_token,
    )

@import_songs_bp.route('/song', methods=['GET', 'POST'])
@login_required
def import_song():
    if not current_user.is_authenticated:
        flash("Please log in to import songs.", "warning")
        return redirect(url_for('users.login'))

    token_redirect, spotify_token = _require_spotify_token("songs")
    if token_redirect:
        return token_redirect

    if request.method == 'POST':
        track_id = request.form.get('song_id')
        if not track_id:
            flash("No song ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))
            
        result = ImportHelper.import_item(
            service_name='spotify',
            item_type='track',
            item_id=track_id,
            oauth_spotify=oauth.spotify,
            spotify_token=spotify_token,
        )
        
        imported_count = result.get('imported_count', 0)
        skipped_count = result.get('skipped_count', 0)

        if imported_count > 0:
            flash(f'Successfully imported {imported_count} song!', 'success')
        elif skipped_count > 0:
            flash('Song was already in the database.', 'info')
        else:
            flash(_safe_spotify_import_error('song'), 'danger')
            
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

    token_redirect, spotify_token = _require_spotify_token("playlists")
    if token_redirect:
        return token_redirect
    
    if request.method == 'POST':
        playlist_id = request.form.get('playlist_id')
        if not playlist_id:
            flash("No playlist ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))

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
            spotify_token=spotify_token,
        )
        flash(f'Playlist import queued as job #{job_record.id}.', 'info')
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

    token_redirect, spotify_token = _require_spotify_token("albums")
    if token_redirect:
        return token_redirect
    
    if request.method == 'POST':
        album_id = request.form.get('album_id')
        if not album_id:
            flash("No album ID provided for import.", "danger")
            return redirect(request.referrer or url_for('core.search'))
            
        result = ImportHelper.import_item(
            service_name='spotify',
            item_type='album',
            item_id=album_id,
            oauth_spotify=oauth.spotify,
            spotify_token=spotify_token,
        )
        
        imported_count = result.get('imported_count', 0)
        skipped_count = result.get('skipped_count', 0)
        error_count = result.get('error_count', 0)

        if imported_count > 0:
            flash(f'Successfully imported {imported_count} songs from album! ({skipped_count} skipped, {error_count} errors).', 'success')
        elif skipped_count > 0 and error_count == 0:
            flash(f'All {skipped_count} songs were already in the database.', 'info')
        elif error_count > 0:
            flash(f'Album import: {imported_count} new, {skipped_count} skipped, {error_count} errors.', 'warning')
        else:
            flash(_safe_spotify_import_error('album'), 'danger')
            
        return redirect(url_for('core.view_songs'))
        
    return render_template('service_import.html',
                         service_name='Spotify',
                         item_type='Album',
                         url_example_prefix='https://open.spotify.com/album/',
                         url_example_id='4aawyAB9vmqN3uQ7FjRGTy',
                         id_field='album_id',
                         form_action=url_for('import_songs.import_album'),
                         back_url=url_for('core.search'))
