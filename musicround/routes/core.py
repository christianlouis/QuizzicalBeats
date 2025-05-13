"""
Core routes that form the basic navigation structure of the app.
"""
from flask import Blueprint, render_template, redirect, url_for, current_app, request, send_from_directory, abort, session
from flask_login import current_user, login_required
from musicround import db

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
    """Process Spotify search and display results"""
    if 'access_token' not in session:
        # Redirect to Spotify login if not authenticated
        return redirect(url_for('auth.spotify_login'))
    
    search_term = request.form.get('search_term', '')
    if not search_term:
        return redirect(url_for('core.search'))
    
    try:
        # Initialize Spotify client with access token
        import spotipy
        from spotipy.exceptions import SpotifyException
        
        current_app.logger.info(f"Searching Spotify for: {search_term}")
        
        # Try to check if token is valid before using it
        try:
            sp = spotipy.Spotify(auth=session.get('access_token'))
            # Make a simple API call to verify token
            sp.current_user()
        except SpotifyException as e:
            # If token is expired, try refreshing it
            if e.http_status == 401:
                current_app.logger.info("Spotify token expired, attempting refresh")
                # Check if we have a refresh token
                if current_user.spotify_refresh_token:
                    try:
                        # Create OAuth object to refresh token
                        from spotipy.oauth2 import SpotifyOAuth
                        from musicround.config import Config
                        
                        sp_oauth = SpotifyOAuth(
                            client_id=Config.SPOTIFY_CLIENT_ID,
                            client_secret=Config.SPOTIFY_CLIENT_SECRET,
                            redirect_uri=Config.SPOTIFY_REDIRECT_URI,
                            scope=Config.SPOTIFY_SCOPE
                        )
                        
                        # Get new token
                        token_info = sp_oauth.refresh_access_token(current_user.spotify_refresh_token)
                        
                        # Update session and user
                        session['access_token'] = token_info['access_token']
                        current_user.spotify_token = token_info['access_token']
                        if 'refresh_token' in token_info:
                            current_user.spotify_refresh_token = token_info['refresh_token']
                        
                        # Update token expiry
                        import datetime
                        current_user.spotify_token_expiry = datetime.datetime.now() + datetime.timedelta(seconds=token_info['expires_in'])
                        
                        # Save changes
                        db.session.commit()
                        
                        # Create new Spotify client with updated token
                        sp = spotipy.Spotify(auth=token_info['access_token'])
                        
                    except Exception as refresh_error:
                        current_app.logger.error(f"Error refreshing Spotify token: {str(refresh_error)}")
                        # Redirect to login if we can't refresh
                        return redirect(url_for('auth.spotify_login'))
                else:
                    # No refresh token, redirect to login
                    return redirect(url_for('auth.spotify_login'))
            else:
                # Some other Spotify error
                raise
        
        # Prepare more specific search parameters for better results
        # Try different search strategies for artists vs tracks
        search_strategies = [
            # Regular search for all types
            {'q': search_term, 'type': 'track,album,playlist', 'limit': 10},
            
            # Search specifically for artist
            {'q': f'artist:{search_term}', 'type': 'track', 'limit': 10},
            
            # Search specifically for track
            {'q': f'track:{search_term}', 'type': 'track', 'limit': 10}
        ]
        
        tracks = []
        albums = []
        playlists = []
        
        # Try different search strategies until we get results
        for strategy in search_strategies:
            current_app.logger.info(f"Trying search strategy: {strategy}")
            
            # Perform search with current strategy
            results = sp.search(**strategy)
            
            # Extract track results if available
            if 'tracks' in results and results['tracks']['items']:
                for item in results['tracks']['items']:
                    # Skip None items or items without required fields
                    if item is None or 'id' not in item or 'artists' not in item or 'album' not in item:
                        continue
                        
                    artist_names = [artist['name'] for artist in item['artists']]
                    
                    # Get album image safely
                    image_url = None
                    if 'album' in item and item['album'] and 'images' in item['album'] and item['album']['images']:
                        image_url = item['album']['images'][0]['url'] if item['album']['images'] else None
                    
                    # Get album name safely
                    album_name = item['album']['name'] if 'album' in item and item['album'] and 'name' in item['album'] else 'Unknown Album'
                    
                    tracks.append({
                        'id': item['id'],
                        'name': item['name'],
                        'artist': ', '.join(artist_names),
                        'album': album_name,
                        'image_url': image_url,
                        'preview_url': item.get('preview_url'),
                        'duration_ms': item.get('duration_ms', 0)
                    })
            
            # Extract album results if available
            if 'albums' in results and results['albums']['items']:
                for item in results['albums']['items']:
                    # Skip None items or items without required fields
                    if item is None or 'id' not in item or 'artists' not in item:
                        continue
                        
                    artist_names = [artist['name'] for artist in item['artists']]
                    
                    # Get album image safely
                    image_url = None
                    if 'images' in item and item['images']:
                        image_url = item['images'][0]['url'] if item['images'] else None
                    
                    albums.append({
                        'id': item['id'],
                        'name': item['name'],
                        'artist': ', '.join(artist_names),
                        'image_url': image_url,
                        'total_tracks': item.get('total_tracks', 0)
                    })
            
            # Extract playlist results if available
            if 'playlists' in results and results['playlists']['items']:
                for item in results['playlists']['items']:
                    # Skip None items or items without required fields
                    if item is None or 'id' not in item or 'owner' not in item:
                        continue
                    
                    # Get playlist image safely
                    image_url = None
                    if 'images' in item and item['images']:
                        image_url = item['images'][0]['url'] if item['images'] else None
                    
                    # Get track count safely
                    track_count = 0
                    if 'tracks' in item and item['tracks'] is not None and 'total' in item['tracks']:
                        track_count = item['tracks']['total']
                    
                    # Get owner name safely
                    owner_name = item['owner'].get('display_name') or item['owner'].get('id', 'Unknown')
                    
                    playlists.append({
                        'id': item['id'],
                        'name': item['name'],
                        'owner': owner_name,
                        'image_url': image_url,
                        'tracks': track_count
                    })
            
            # If we got any results, break the loop
            if tracks or albums or playlists:
                break
        
        # If still no results after all strategies, try one more approach
        if not tracks and not albums and not playlists:
            current_app.logger.info("No results from standard searches, trying market-specific search")
            # Try a more generic search with market specification
            results = sp.search(q=search_term, type='track,album,playlist', limit=10, market='US')
            
            # Extract track results
            if 'tracks' in results and results['tracks']['items']:
                for item in results['tracks']['items']:
                    artist_names = [artist['name'] for artist in item['artists']]
                    tracks.append({
                        'id': item['id'],
                        'name': item['name'],
                        'artist': ', '.join(artist_names),
                        'album': item['album']['name'],
                        'image_url': item['album']['images'][0]['url'] if item['album']['images'] else None,
                        'preview_url': item['preview_url'],
                        'duration_ms': item['duration_ms']
                    })
        
        # Remove duplicates (in case our strategies found the same items)
        unique_tracks = []
        track_ids_seen = set()
        for track in tracks:
            if track['id'] not in track_ids_seen:
                track_ids_seen.add(track['id'])
                unique_tracks.append(track)
        
        unique_albums = []
        album_ids_seen = set()
        for album in albums:
            if album['id'] not in album_ids_seen:
                album_ids_seen.add(album['id'])
                unique_albums.append(album)
        
        unique_playlists = []
        playlist_ids_seen = set()
        for playlist in playlists:
            if playlist['id'] not in playlist_ids_seen:
                playlist_ids_seen.add(playlist['id'])
                unique_playlists.append(playlist)
        
        # Log the number of results found
        current_app.logger.info(f"Search results: {len(unique_tracks)} tracks, {len(unique_albums)} albums, {len(unique_playlists)} playlists")
        
        # Render search results template
        return render_template('service_search_results.html',
                             service_name='Spotify',
                             search_term=search_term,
                             tracks=unique_tracks,
                             albums=unique_albums,
                             playlists=unique_playlists,
                             track_import_url=url_for('import_songs.import_song'),
                             album_import_url=url_for('import_songs.import_album'),
                             playlist_import_url=url_for('import_songs.import_playlist'),
                             track_id_field='song_id',
                             album_id_field='album_id',
                             playlist_id_field='playlist_id',
                             tracks_label='Tracks',
                             has_preview=True,
                             search_url=url_for('core.search'))
    
    except Exception as e:
        # Log the detailed error
        import traceback
        current_app.logger.error(f"Spotify search error: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        
        # Render error template
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
    
    # Get all songs
    songs = Song.query.all()
    
    # Get all tags
    tags = Tag.query.all()
    
    return render_template('view_songs.html', songs=songs, tags=tags)

@core_bp.route('/data/<path:filepath>')
@login_required
def serve_user_audio(filepath):
    """
    Serve user custom audio files from the data directory
    """
    # For security, ensure the filepath doesn't try to access parent directories
    if '..' in filepath:
        abort(404)
        
    # Only allow access to the current user's custom MP3 files or to admins
    if 'custommp3/' in filepath:
        # Extract username from the filepath
        parts = filepath.split('/')
        if len(parts) >= 2 and parts[0] == 'custommp3':
            username = parts[1]
            
            # Check if current user is the owner of the file or an admin
            if username != current_user.username and not current_user.is_admin:
                abort(403)  # Unauthorized
    
    return send_from_directory('/data', filepath)