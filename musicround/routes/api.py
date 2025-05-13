"""
API routes for song operations in the Music Round application
"""
from flask import Blueprint, jsonify, request, current_app, session, redirect, url_for
from musicround.models import Song, Tag, SongTag, db, Round
from musicround.helpers.metadata import get_song_metadata_by_isrc
from flask_wtf.csrf import CSRFProtect
import traceback  # Add import at the top
import spotipy as spotify  # Changed import from spotify to spotipy as spotify
import logging
from sqlalchemy import or_
from flask_login import login_required  # Add import for login_required

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/songs/<int:song_id>', methods=['GET', 'PUT', 'DELETE'])
def song_detail(song_id):
    """API endpoint for getting, updating, and deleting song details"""
    song = Song.query.get_or_404(song_id)
    
    if request.method == 'GET':
        # Return song details as JSON
        tag_list = [{'id': tag.id, 'name': tag.name} for tag in song.tags]
        
        return jsonify({
            'id': song.id,
            'title': song.title,
            'artist': song.artist,
            'genre': song.genre,
            'year': song.year,
            'isrc': song.isrc,
            'popularity': song.popularity,
            'used_count': song.used_count,
            'spotify_id': song.spotify_id,
            'deezer_id': song.deezer_id,
            'preview_url': song.preview_url,
            'cover_url': song.cover_url,
            'spotify_preview_url': song.spotify_preview_url,
            'deezer_preview_url': song.deezer_preview_url,
            'apple_preview_url': song.apple_preview_url,
            'youtube_preview_url': song.youtube_preview_url,
            'spotify_cover_url': song.spotify_cover_url,
            'deezer_cover_url': song.deezer_cover_url,
            'apple_cover_url': song.apple_cover_url,
            'metadata_sources': song.metadata_sources,
            'album_name': song.album_name,
            'source': song.source,
            'import_date': song.import_date.isoformat() if song.import_date else None,
            'tags': tag_list,
            # Add all Spotify audio features
            'acousticness': song.acousticness,
            'danceability': song.danceability,
            'energy': song.energy,
            'instrumentalness': song.instrumentalness,
            'key': song.key,
            'liveness': song.liveness,
            'loudness': song.loudness,
            'mode': song.mode,
            'speechiness': song.speechiness,
            'tempo': song.tempo,
            'time_signature': song.time_signature,
            'valence': song.valence,
            'duration_ms': song.duration_ms
        })
    
    elif request.method == 'PUT':
        # Update song details
        data = request.get_json()
        current_app.logger.info(f"Updating song {song_id} with data: {data}")
        
        # Update basic fields
        if data.get('title'):
            song.title = data['title']
        if data.get('artist'):
            song.artist = data['artist']
        if data.get('genre'):
            song.genre = data['genre']
        if data.get('year'):
            song.year = data['year']
        if data.get('isrc'):
            song.isrc = data['isrc']
        if 'popularity' in data and data['popularity'] is not None:
            try:
                song.popularity = int(data['popularity'])
            except (ValueError, TypeError):
                current_app.logger.warning(f"Invalid popularity value: {data['popularity']}")
        
        # Update IDs
        if data.get('spotify_id'):
            song.spotify_id = data['spotify_id']
        if data.get('deezer_id'):
            song.deezer_id = data['deezer_id']
            
        # Update URLs
        if data.get('preview_url'):
            song.preview_url = data['preview_url']
        if data.get('cover_url'):
            song.cover_url = data['cover_url']
            
        # Save changes
        db.session.commit()
        current_app.logger.info(f"Song {song_id} updated successfully")
        
        # Return updated song details including tags
        tag_list = [{'id': tag.id, 'name': tag.name} for tag in song.tags]
        
        return jsonify({
            'id': song.id,
            'title': song.title,
            'artist': song.artist,
            'genre': song.genre,
            'year': song.year,
            'isrc': song.isrc,
            'popularity': song.popularity,
            'preview_url': song.preview_url,
            'cover_url': song.cover_url,
            'tags': tag_list
        })
        
    elif request.method == 'DELETE':
        # Check if the song is used in any rounds before deleting
        rounds_with_song = []
        
        for round_obj in Round.query.all():
            song_ids = round_obj.songs.split(',')
            if str(song_id) in song_ids:
                rounds_with_song.append(round_obj.id)
        
        if rounds_with_song:
            # The song is used in rounds, return error
            return jsonify({
                'error': 'Cannot delete song as it is used in rounds',
                'rounds': rounds_with_song
            }), 400
        
        # Delete the song
        title = song.title
        artist = song.artist
        db.session.delete(song)
        db.session.commit()
        current_app.logger.info(f"Song {song_id} ({title} by {artist}) deleted successfully")
        
        return jsonify({
            'message': f"Song '{title}' by {artist} deleted successfully",
            'id': song_id
        })

@api_bp.route('/songs/<int:song_id>/refresh-metadata', methods=['POST'])
def refresh_song_metadata(song_id):
    """API endpoint for refreshing song metadata"""
    song = Song.query.get_or_404(song_id)
    
    # Check if we have an ISRC code to use for refreshing metadata
    if not song.isrc:
        current_app.logger.warning(f"Cannot refresh metadata for song {song_id} - no ISRC code")
        return jsonify({'error': 'Song has no ISRC code to refresh metadata'}), 400
    
    try:
        # Get fresh metadata using the existing ISRC
        current_app.logger.info(f"=== DEBUG: Starting metadata refresh for song {song_id} with ISRC {song.isrc} ===")
        metadata = get_song_metadata_by_isrc(song.isrc, current_app)
        
        if not metadata:
            current_app.logger.warning(f"No metadata found for ISRC {song.isrc}")
            return jsonify({'error': 'No metadata found for this ISRC'}), 404
        
        # Debug the metadata received
        current_app.logger.info(f"DEBUG: Received metadata structure: {type(metadata).__name__}")
        for key, value in metadata.items():
            value_type = type(value).__name__
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + "..."
            current_app.logger.info(f"DEBUG: Metadata key '{key}' = {value_str} (type: {value_type})")
        
        # Update song with new metadata
        if metadata.get('title'):
            current_app.logger.info(f"DEBUG: Updating title to '{metadata['title']}'")
            song.title = metadata['title']
        if metadata.get('artist_name'):
            current_app.logger.info(f"DEBUG: Updating artist to '{metadata['artist_name']}'")
            song.artist = metadata['artist_name']
        if metadata.get('genre'):
            current_app.logger.info(f"DEBUG: Updating genre to '{metadata['genre']}' (type: {type(metadata['genre']).__name__})")
            song.genre = metadata['genre']
            
            # Import helper for creating tags from genre
            from musicround.helpers.import_helper import ImportHelper
            ImportHelper.create_tags_from_genre(song, metadata['genre'])
            
        if metadata.get('year'):
            current_app.logger.info(f"DEBUG: Updating year to '{metadata['year']}'")
            song.year = metadata['year']
        
        # Check additional metadata for genres and add tags from there too
        if 'genres' in metadata:
            current_app.logger.info(f"DEBUG: Creating tags from additional genres")
            from musicround.helpers.import_helper import ImportHelper
            ImportHelper.create_tags_from_genre(song, metadata['genres'])
        
        # Update URLs if available
        if metadata.get('preview_url'):
            current_app.logger.info(f"DEBUG: Updating preview_url")
            song.preview_url = metadata['preview_url']
        if metadata.get('cover_url'):
            current_app.logger.info(f"DEBUG: Updating cover_url")
            song.cover_url = metadata['cover_url']
        
        # Update platform-specific IDs if available
        if metadata.get('spotify_id'):
            song.spotify_id = metadata['spotify_id']
        if metadata.get('deezer_id'):
            song.deezer_id = metadata['deezer_id']
            
        # Update platform-specific preview URLs
        if metadata.get('spotify_preview_url'):
            song.spotify_preview_url = metadata['spotify_preview_url']
        if metadata.get('deezer_preview_url'):
            song.deezer_preview_url = metadata['deezer_preview_url']
        if metadata.get('apple_preview_url'):
            song.apple_preview_url = metadata['apple_preview_url']
        if metadata.get('youtube_preview_url'):
            song.youtube_preview_url = metadata['youtube_preview_url']
            
        # Update platform-specific cover URLs
        if metadata.get('spotify_cover_url'):
            song.spotify_cover_url = metadata['spotify_cover_url']
        if metadata.get('deezer_cover_url'):
            song.deezer_cover_url = metadata['deezer_cover_url']
        if metadata.get('apple_cover_url'):
            song.apple_cover_url = metadata['apple_cover_url']
            
        # Update popularity if available
        if metadata.get('popularity') is not None:
            song.popularity = metadata['popularity']
            
        # Store metadata sources
        if metadata.get('sources'):
            try:
                sources_str = ','.join(metadata['sources'])
                current_app.logger.info(f"DEBUG: Setting metadata_sources to '{sources_str}'")
                song.metadata_sources = sources_str
            except Exception as source_error:
                current_app.logger.error(f"DEBUG: Error joining sources: {source_error}")
                current_app.logger.error(f"DEBUG: Sources value: {metadata['sources']} (type: {type(metadata['sources']).__name__})")
        
        # Save changes to the database
        try:
            current_app.logger.info("DEBUG: Committing changes to database")
            db.session.commit()
            current_app.logger.info(f"Metadata for song {song_id} updated successfully with sources: {metadata.get('sources')}")
        except Exception as db_error:
            db.session.rollback()
            current_app.logger.error(f"DEBUG: Database commit error: {db_error}")
            current_app.logger.error(f"DEBUG: Traceback: {traceback.format_exc()}")
            return jsonify({'error': f"Database error: {str(db_error)}"}), 500
        
        # Return updated song details including tags
        tag_list = [{'id': tag.id, 'name': tag.name} for tag in song.tags]
        
        return jsonify({
            'id': song.id,
            'title': song.title,
            'artist': song.artist,
            'genre': song.genre,
            'year': song.year,
            'isrc': song.isrc,
            'popularity': song.popularity,
            'preview_url': song.preview_url,
            'cover_url': song.cover_url,
            'spotify_id': song.spotify_id,
            'deezer_id': song.deezer_id,
            'spotify_preview_url': song.spotify_preview_url,
            'deezer_preview_url': song.deezer_preview_url,
            'apple_preview_url': song.apple_preview_url,
            'youtube_preview_url': song.youtube_preview_url,
            'metadata_sources': song.metadata_sources,
            'tags': tag_list
        })
        
    except Exception as e:
        current_app.logger.error(f"Error refreshing metadata for song {song_id}: {str(e)}")
        current_app.logger.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

# New API routes for tag operations

@api_bp.route('/tags', methods=['GET'])
def list_tags():
    """Get all available tags"""
    tags = Tag.query.order_by(Tag.name).all()
    return jsonify({
        'tags': [{'id': tag.id, 'name': tag.name} for tag in tags]
    })

@api_bp.route('/tags', methods=['POST'])
def create_tag():
    """Create a new tag"""
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': 'Tag name is required'}), 400
    
    tag_name = data['name'].strip()
    
    # Check if tag already exists
    existing_tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
    if existing_tag:
        return jsonify({
            'message': 'Tag already exists',
            'tag': {'id': existing_tag.id, 'name': existing_tag.name}
        })
    
    # Create new tag
    new_tag = Tag(name=tag_name)
    db.session.add(new_tag)
    db.session.commit()
    
    return jsonify({
        'message': 'Tag created successfully',
        'tag': {'id': new_tag.id, 'name': new_tag.name}
    }), 201

@api_bp.route('/songs/<int:song_id>/tags', methods=['GET'])
def get_song_tags(song_id):
    """Get all tags for a specific song"""
    song = Song.query.get_or_404(song_id)
    
    return jsonify({
        'song_id': song_id,
        'tags': [{'id': tag.id, 'name': tag.name} for tag in song.tags]
    })

@api_bp.route('/songs/<int:song_id>/tags', methods=['POST'])
def add_tag_to_song(song_id):
    """Add a tag to a song"""
    song = Song.query.get_or_404(song_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Check if we're adding an existing tag or creating a new one
    if data.get('tag_id'):
        # Add existing tag
        tag = Tag.query.get_or_404(data['tag_id'])
    elif data.get('tag_name'):
        # Find or create tag
        tag_name = data['tag_name'].strip()
        tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
        
        if not tag:
            tag = Tag(name=tag_name)
            db.session.add(tag)
            db.session.commit()
    else:
        return jsonify({'error': 'Either tag_id or tag_name must be provided'}), 400
    
    # Check if the song already has this tag
    if tag in song.tags:
        return jsonify({
            'message': f"Song '{song.title}' already has tag '{tag.name}'",
            'song_id': song_id,
            'tag': {'id': tag.id, 'name': tag.name}
        })
    
    # Add tag to song
    song.tags.append(tag)
    db.session.commit()
    
    return jsonify({
        'message': f"Tag '{tag.name}' added to song '{song.title}'",
        'song_id': song_id,
        'tag': {'id': tag.id, 'name': tag.name}
    })

@api_bp.route('/songs/<int:song_id>/tags/<int:tag_id>', methods=['DELETE'])
def remove_tag_from_song(song_id, tag_id):
    """Remove a tag from a song"""
    song = Song.query.get_or_404(song_id)
    tag = Tag.query.get_or_404(tag_id)
    
    # Check if the song has this tag
    if tag not in song.tags:
        return jsonify({
            'message': f"Song '{song.title}' doesn't have tag '{tag.name}'",
            'song_id': song_id,
            'tag_id': tag_id
        })
    
    # Remove tag from song
    song.tags.remove(tag)
    db.session.commit()
    
    return jsonify({
        'message': f"Tag '{tag.name}' removed from song '{song.title}'",
        'song_id': song_id,
        'tag_id': tag_id
    })

@api_bp.route('/tags/<int:tag_id>', methods=['GET'])
def get_songs_by_tag(tag_id):
    """Get all songs with a specific tag"""
    tag = Tag.query.get_or_404(tag_id)
    
    songs = []
    for song in tag.songs:
        songs.append({
            'id': song.id,
            'title': song.title,
            'artist': song.artist
        })
    
    return jsonify({
        'tag': {'id': tag.id, 'name': tag.name},
        'song_count': len(songs),
        'songs': songs
    })

@api_bp.route('/spotify/album/<album_id>', methods=['GET'])
def get_spotify_album(album_id):
    try:
        # Check for Spotify access token
        if 'access_token' not in session:
            return jsonify({'error': 'You must be logged in to access this feature'}), 401
        
        # Initialize Spotify client with access token
        sp = spotify.Spotify(auth=session.get('access_token'))
        
        # Get album details
        album = sp.album(album_id)
        album_tracks = sp.album_tracks(album_id, limit=50)
        
        # Format tracks
        tracks = []
        for track in album_tracks['items']:
            artist_names = [artist['name'] for artist in track['artists']]
            tracks.append({
                'name': track['name'],
                'artist': ', '.join(artist_names),
                'duration': track['duration_ms'],
                'track_number': track['track_number']
            })
        
        # Format album response
        album_data = {
            'id': album['id'],
            'name': album['name'],
            'artist': ', '.join([artist['name'] for artist in album['artists']]),
            'release_date': album['release_date'],
            'image_url': album['images'][0]['url'] if album['images'] else None,
            'total_tracks': album['total_tracks'],
            'tracks': tracks
        }
        
        return jsonify(album_data)
    except Exception as e:
        current_app.logger.error(f"Error fetching Spotify album: {str(e)}")
        return jsonify({'error': 'Unable to fetch album details'}), 500

@api_bp.route('/spotify/playlist/<playlist_id>', methods=['GET'])
def get_spotify_playlist(playlist_id):
    try:
        # Check for Spotify access token
        if 'access_token' not in session:
            return jsonify({'error': 'You must be logged in to access this feature'}), 401
        
        # Initialize Spotify client with access token
        sp = spotify.Spotify(auth=session.get('access_token'))
        
        # Get playlist details
        playlist = sp.playlist(playlist_id)
        
        # Format tracks
        tracks = []
        for item in playlist['tracks']['items']:
            if not item['track']:
                continue
                
            track = item['track']
            artist_names = [artist['name'] for artist in track['artists']]
            tracks.append({
                'name': track['name'],
                'artist': ', '.join(artist_names),
                'duration': track['duration_ms'],
                'album': track['album']['name'] if track.get('album') else ''
            })
        
        # Format playlist response
        playlist_data = {
            'id': playlist['id'],
            'name': playlist['name'],
            'description': playlist['description'],
            'owner': playlist['owner']['display_name'] or playlist['owner']['id'],
            'image_url': playlist['images'][0]['url'] if playlist['images'] else None,
            'followers': playlist['followers']['total'] if playlist.get('followers') else 0,
            'tracks': tracks
        }
        
        return jsonify(playlist_data)
    except Exception as e:
        current_app.logger.error(f"Error fetching Spotify playlist: {str(e)}")
        return jsonify({'error': 'Unable to fetch playlist details'}), 500

@api_bp.route('/deezer/album/<album_id>', methods=['GET'])
def get_deezer_album(album_id):
    try:
        # Get album details from Deezer using the DeezerClient instance from Flask app config
        deezer_client = current_app.config.get('deezer')  # Using correct config key 'deezer'
        album = deezer_client.get_album(album_id)
        tracks = deezer_client.get_album_tracks(album_id)
        
        # Format tracks
        formatted_tracks = []
        for track in tracks:
            formatted_tracks.append({
                'name': track['title'],
                'artist': track['artist']['name'],
                'duration': track['duration'] * 1000,  # Convert to ms for consistency
                'track_number': track.get('track_position', 0)
            })
        
        # Format album response
        album_data = {
            'id': album['id'],
            'name': album['title'],
            'artist': album['artist']['name'],
            'release_date': album.get('release_date', ''),
            'image_url': album.get('cover_xl') or album.get('cover_big') or album.get('cover'),
            'total_tracks': album.get('nb_tracks', len(formatted_tracks)),
            'tracks': formatted_tracks
        }
        
        return jsonify(album_data)
    except Exception as e:
        current_app.logger.error(f"Error fetching Deezer album: {str(e)}")
        return jsonify({'error': 'Unable to fetch album details'}), 500

@api_bp.route('/deezer/playlist/<playlist_id>', methods=['GET'])
def get_deezer_playlist(playlist_id):
    try:
        # Get playlist details from Deezer using the DeezerClient instance from Flask app config
        deezer_client = current_app.config.get('deezer')  # Using correct config key 'deezer'
        playlist = deezer_client.get_playlist(playlist_id)
        tracks = deezer_client.get_playlist_tracks(playlist_id)
        
        # Format tracks
        formatted_tracks = []
        for track in tracks:
            formatted_tracks.append({
                'name': track['title'],
                'artist': track['artist']['name'],
                'duration': track['duration'] * 1000,  # Convert to ms for consistency
                'album': track['album']['title'] if 'album' in track else ''
            })
        
        # Format playlist response
        playlist_data = {
            'id': playlist['id'],
            'name': playlist['title'],
            'description': playlist.get('description', ''),
            'owner': playlist.get('creator', {}).get('name', 'Unknown'),
            'image_url': playlist.get('picture_xl') or playlist.get('picture_big') or playlist.get('picture'),
            'followers': playlist.get('fans', 0),
            'tracks': formatted_tracks
        }
        
        return jsonify(playlist_data)
    except Exception as e:
        current_app.logger.error(f"Error fetching Deezer playlist: {str(e)}")
        return jsonify({'error': 'Unable to fetch playlist details'}), 500

@api_bp.route('/songs/search')
def search_songs():
    """Search for songs by title or artist"""
    if 'access_token' not in session:
        return jsonify({'error': 'Authentication required'}), 401
        
    query = request.args.get('q', '')
    if not query or len(query) < 2:
        return jsonify([])
        
    # Search for songs by title or artist
    songs = Song.query.filter(
        or_(
            Song.title.ilike(f'%{query}%'),
            Song.artist.ilike(f'%{query}%')
        )
    ).limit(20).all()
    
    # Convert songs to JSON
    results = []
    for song in songs:
        results.append({
            'id': song.id,
            'title': song.title,
            'artist': song.artist,
            'year': song.year,
            'genre': song.genre,
            'cover_url': song.cover_url,
            'preview_url': song.preview_url
        })
    
    return jsonify(results)

@api_bp.route('/songs/update-audio-features', methods=['POST'])
@login_required
def update_audio_features():
    """Update audio features for Spotify songs in the database"""
    # Get parameters from the request
    batch_size = request.json.get('batch_size', 50)  # Process in batches to avoid timeouts
    process_all = request.json.get('process_all', False)
    process_specific = request.json.get('process_specific', False)
    song_ids = request.json.get('song_ids', [])
    
    # If specific song IDs are provided, query those songs
    if process_specific and song_ids:
        query = Song.query.filter(
            Song.id.in_(song_ids),
            Song.spotify_id.isnot(None)  # Only process songs with Spotify IDs
        )
    else:
        # Query songs that have Spotify IDs but no audio features
        query = Song.query.filter(
            Song.spotify_id.isnot(None)  # Only process songs with Spotify IDs
        )
    
        # If not processing all, only select songs without audio features
        if not process_all:
            query = query.filter(Song.acousticness.is_(None))
    
    # Count total songs to process
    total_songs = query.count()
    
    if total_songs == 0:
        return jsonify({
            'success': True,
            'message': 'No songs found that need audio features.',
            'processed': 0,
            'total': 0
        })
    
    # Get bearer token from session
    bearer_token = session.get('direct_bearer_token')
    
    # If no direct bearer token found, try to use the standard access token as fallback
    if not bearer_token:
        bearer_token = session.get('access_token')
        if not bearer_token:
            return jsonify({
                'success': False,
                'message': 'No Spotify authentication token found in session.',
                'error': 'SPOTIFY_TOKEN_NOT_FOUND'
            }), 401
    
    # Create an instance of the SpotifyDirectClient for this request
    try:
        # Initialize our custom Spotify client with the bearer token
        from musicround.helpers.spotify_direct import SpotifyDirectClient
        direct_sp = SpotifyDirectClient(bearer_token=bearer_token)
    except Exception as e:
        current_app.logger.error(f"Error initializing SpotifyDirectClient: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to initialize Spotify client',
            'error': str(e)
        }), 500
    
    # Process songs in batches
    processed_count = 0
    error_count = 0
    
    # Get all matching songs (limit to reasonable number to prevent timeouts)
    songs = query.limit(1000).all()
    
    # Process in batches of batch_size
    for i in range(0, len(songs), batch_size):
        batch = songs[i:i+batch_size]
        track_ids = [song.spotify_id for song in batch]
        
        # Get audio features for this batch
        try:
            # Use our custom SpotifyDirectClient for batch audio features
            features = direct_sp.get_tracks_audio_features(track_ids)
            
            if not features:
                current_app.logger.warning(f"No audio features returned for batch {i//batch_size + 1}")
                error_count += len(batch)
                continue
                
            # Map features to songs by Spotify ID
            features_dict = {feature['id']: feature for feature in features if feature}
            
            # Update each song with its audio features
            for song in batch:
                if song.spotify_id in features_dict:
                    feature = features_dict[song.spotify_id]
                    
                    # Update song with audio features
                    song.acousticness = feature.get('acousticness')
                    song.danceability = feature.get('danceability')
                    song.energy = feature.get('energy')
                    song.instrumentalness = feature.get('instrumentalness')
                    song.key = feature.get('key')
                    song.liveness = feature.get('liveness')
                    song.loudness = feature.get('loudness')
                    song.mode = feature.get('mode')
                    song.speechiness = feature.get('speechiness')
                    song.tempo = feature.get('tempo')
                    song.time_signature = feature.get('time_signature')
                    song.valence = feature.get('valence')
                    song.duration_ms = feature.get('duration_ms')
                    song.analysis_url = feature.get('analysis_url')
                    
                    # Add audio features to metadata sources if not already present
                    if song.metadata_sources:
                        sources = song.metadata_sources.split(',')
                        if 'audio_features' not in sources:
                            sources.append('audio_features')
                            song.metadata_sources = ','.join(sources)
                    else:
                        song.metadata_sources = 'audio_features'
                    
                    processed_count += 1
                else:
                    current_app.logger.warning(f"No audio features found for song {song.id} ({song.spotify_id})")
                    error_count += 1
            
            # Save all changes to database
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing audio features batch: {str(e)}")
            error_count += len(batch)
    
    return jsonify({
        'success': True,
        'message': f'Successfully updated audio features for {processed_count} songs. {error_count} errors.',
        'processed': processed_count,
        'errors': error_count,
        'total': total_songs
    })

@api_bp.route('/dropbox/folders', methods=['GET'])
@login_required
def list_dropbox_folders():
    """List folders from user's Dropbox account for the folder browser"""
    from flask_login import current_user
    from musicround.helpers.dropbox_helper import get_current_user_dropbox_token
    import requests
    import json
    import traceback
    
    # Check if user has Dropbox connected
    if not current_user.dropbox_token:
        current_app.logger.error("Dropbox folder listing failed: User has no Dropbox token")
        return jsonify({'error': 'Dropbox account not connected'}), 401
        
    # Get Dropbox token
    token = get_current_user_dropbox_token()
    if not token:
        current_app.logger.error("Dropbox folder listing failed: Failed to get valid token")
        return jsonify({'error': 'Failed to get valid Dropbox token'}), 401
    
    # Get the path from query params, default to empty string (root)
    path = request.args.get('path', '')
    
    # Fix path format for Dropbox API
    # Dropbox API requires empty string for root, not "/"
    if path == '/' or not path:
        path = ""
        display_path = "/"
    else:
        display_path = path
        
    current_app.logger.info(f"Listing Dropbox folders for path: {display_path}")
        
    try:
        # Call Dropbox API to list folders
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        # Use the list_folder API with recursive=False to get only immediate children
        data = {
            'path': path,
            'recursive': False,
            'include_deleted': False,
            'include_has_explicit_shared_members': False,
            'include_mounted_folders': True,
            'include_non_downloadable_files': False
        }
        
        current_app.logger.debug(f"Sending request to Dropbox API: {json.dumps(data)}")
        current_app.logger.debug(f"Using token: {token[:5]}...{token[-5:] if len(token) > 10 else ''}")
        
        response = requests.post(
            'https://api.dropboxapi.com/2/files/list_folder',
            headers=headers,
            json=data
        )
        
        current_app.logger.debug(f"Dropbox API response status: {response.status_code}")
        
        if response.status_code != 200:
            current_app.logger.error(f"Dropbox API error: {response.status_code}, Response: {response.text}")
            
            # Check for specific error types to provide better messages
            try:
                error_data = response.json()
                error_message = f"Dropbox API error: {response.status_code}"
                
                # Handle "not_found" error by trying to create the folder if it's not root
                if (response.status_code == 409 and 
                    "not_found" in response.text and 
                    path != ""):
                    current_app.logger.info(f"Folder {display_path} doesn't exist, showing root folder instead")
                    # Return root folder with a note about the folder not existing
                    return list_root_folders(token, display_path)
                
                if 'error_summary' in error_data:
                    error_message += f": {error_data['error_summary']}"
                
                # Handle common errors
                if response.status_code == 401:
                    # Try to refresh the token and retry once
                    current_app.logger.info("Attempting to refresh Dropbox token and retry")
                    from musicround.helpers.dropbox_helper import refresh_dropbox_token
                    
                    if current_user.dropbox_refresh_token:
                        new_token_info = refresh_dropbox_token(current_user.dropbox_refresh_token)
                        if new_token_info and 'access_token' in new_token_info:
                            # Try again with the new token
                            headers['Authorization'] = f"Bearer {new_token_info['access_token']}"
                            response = requests.post(
                                'https://api.dropboxapi.com/2/files/list_folder',
                                headers=headers,
                                json=data
                            )
                            
                            if response.status_code == 200:
                                # Success! Continue with processing
                                current_app.logger.info("Successfully refreshed token and retrieved folders")
                            else:
                                current_app.logger.error(f"Still failed after token refresh: {response.status_code}, {response.text}")
                                return jsonify({'error': error_message, 'details': error_data}), response.status_code
                        else:
                            current_app.logger.error("Token refresh failed")
                
                if response.status_code != 200:  # If we're still having an error
                    return jsonify({'error': error_message, 'details': error_data}), response.status_code
                
            except Exception as json_error:
                current_app.logger.error(f"Error parsing Dropbox error response: {str(json_error)}")
                return jsonify({'error': f'Dropbox API error: {response.status_code}', 'raw_response': response.text}), 500
        
        # Process the successful response
        result = response.json()
        current_app.logger.debug(f"Received Dropbox response: {json.dumps(result)[:1000] if len(json.dumps(result)) > 1000 else json.dumps(result)}")
            
        # Filter to only include folders
        folders = []
        for entry in result.get('entries', []):
            if entry.get('.tag') == 'folder':
                folders.append({
                    'name': entry.get('name', ''),
                    'path_display': entry.get('path_display', ''),
                    'id': entry.get('id', '')
                })
        
        current_app.logger.info(f"Successfully listed {len(folders)} folders in path '{display_path}'")
                
        return jsonify({
            'path': display_path,
            'folders': folders
        })
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        current_app.logger.error(f"Error listing Dropbox folders: {str(e)}")
        current_app.logger.error(f"Traceback: {error_traceback}")
        return jsonify({
            'error': str(e),
            'traceback': error_traceback,
            'message': 'An unexpected error occurred while listing Dropbox folders'
        }), 500

@api_bp.route('/dropbox/create-folder', methods=['POST'])
@login_required
def create_dropbox_folder():
    """Create a new folder in the user's Dropbox account"""
    from flask_login import current_user
    from musicround.helpers.dropbox_helper import get_current_user_dropbox_token
    import requests
    import json
    import traceback
    
    # Check if user has Dropbox connected
    if not current_user.dropbox_token:
        current_app.logger.error("Dropbox folder creation failed: User has no Dropbox token")
        return jsonify({'error': 'Dropbox account not connected'}), 401
        
    # Get Dropbox token
    token = get_current_user_dropbox_token()
    if not token:
        current_app.logger.error("Dropbox folder creation failed: Failed to get valid token")
        return jsonify({'error': 'Failed to get valid Dropbox token'}), 401
    
    # Get path and new folder name from request
    data = request.get_json()
    if not data or 'parent_path' not in data or 'folder_name' not in data:
        return jsonify({'error': 'Missing required parameters: parent_path and folder_name'}), 400
    
    parent_path = data['parent_path']
    folder_name = data['folder_name'].strip()
    
    # Validate folder name - basic validation
    if not folder_name:
        return jsonify({'error': 'Folder name cannot be empty'}), 400
        
    if any(char in folder_name for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return jsonify({'error': 'Folder name contains invalid characters'}), 400
    
    # Construct full path
    # If parent is root, we need special handling
    if parent_path == '/' or parent_path == '':
        full_path = '/' + folder_name
    else:
        full_path = parent_path + '/' + folder_name
    
    current_app.logger.info(f"Creating Dropbox folder: {full_path}")
    
    try:
        # Call Dropbox API to create folder
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'path': full_path,
            'autorename': False
        }
        
        current_app.logger.debug(f"Sending request to Dropbox API: {json.dumps(data)}")
        
        response = requests.post(
            'https://api.dropboxapi.com/2/files/create_folder_v2',
            headers=headers,
            json=data
        )
        
        current_app.logger.debug(f"Dropbox API response status: {response.status_code}")
        
        if response.status_code != 200:
            current_app.logger.error(f"Dropbox API error: {response.status_code}, Response: {response.text}")
            
            try:
                error_data = response.json()
                error_message = f"Dropbox API error: {response.status_code}"
                
                if 'error_summary' in error_data:
                    error_message += f": {error_data['error_summary']}"
                
                # Special handling for conflict (folder already exists)
                if response.status_code == 409 and 'conflict' in response.text:
                    return jsonify({
                        'error': 'A folder with this name already exists',
                        'details': error_data
                    }), 409
                
                return jsonify({'error': error_message, 'details': error_data}), response.status_code
                
            except Exception as json_error:
                current_app.logger.error(f"Error parsing Dropbox error response: {str(json_error)}")
                return jsonify({
                    'error': f'Dropbox API error: {response.status_code}',
                    'raw_response': response.text
                }), 500
        
        # Process the successful response
        result = response.json()
        current_app.logger.debug(f"Received Dropbox response: {json.dumps(result)}")
        
        # Extract metadata from result
        metadata = result.get('metadata', {})
        
        current_app.logger.info(f"Successfully created folder: {full_path}")
        
        return jsonify({
            'success': True,
            'path': metadata.get('path_display', full_path),
            'name': metadata.get('name', folder_name),
            'id': metadata.get('id', '')
        })
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        current_app.logger.error(f"Error creating Dropbox folder: {str(e)}")
        current_app.logger.error(f"Traceback: {error_traceback}")
        return jsonify({
            'error': str(e),
            'traceback': error_traceback,
            'message': 'An unexpected error occurred while creating Dropbox folder'
        }), 500

def list_root_folders(token, attempted_path=None):
    """Get root folders as a fallback when requested path doesn't exist"""
    import requests
    import json
    
    try:
        # Call Dropbox API to list root folders
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'path': "",  # Empty string for root
            'recursive': False,
            'include_deleted': False,
            'include_has_explicit_shared_members': False,
            'include_mounted_folders': True,
            'include_non_downloadable_files': False
        }
        
        current_app.logger.debug("Listing root folders as fallback")
        
        response = requests.post(
            'https://api.dropboxapi.com/2/files/list_folder',
            headers=headers,
            json=data
        )
        
        if response.status_code != 200:
            current_app.logger.error(f"Root folder listing failed: {response.status_code}, {response.text}")
            return jsonify({
                'error': f'Could not list root folders: {response.status_code}',
                'attempted_path': attempted_path
            }), response.status_code
        
        # Process the successful response
        result = response.json()
        
        # Filter to only include folders
        folders = []
        for entry in result.get('entries', []):
            if entry.get('.tag') == 'folder':
                folders.append({
                    'name': entry.get('name', ''),
                    'path_display': entry.get('path_display', ''),
                    'id': entry.get('id', '')
                })
        
        message = None
        if attempted_path:
            message = f"Folder '{attempted_path}' doesn't exist. Showing root folder instead."
        
        return jsonify({
            'path': '/',
            'folders': folders,
            'warning': message
        })
        
    except Exception as e:
        current_app.logger.error(f"Error listing root folders: {str(e)}")
        return jsonify({
            'error': f'Error listing root folders: {str(e)}',
            'attempted_path': attempted_path
        }), 500