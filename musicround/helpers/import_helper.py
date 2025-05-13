"""
Unified import helper for importing music content across different services.
This module provides consistent import functionality for tracks, albums, and playlists
from various music streaming services like Spotify and Deezer.
"""
import json
import logging
import secrets
import string
from flask import current_app, flash
from musicround.models import Song, Tag, db
from musicround.helpers.metadata import get_song_metadata_by_isrc

def generate_token(length=32):
    """
    Generate a secure random token for authentication or validation purposes.
    
    Args:
        length (int): The length of the token to generate (default: 32)
        
    Returns:
        str: A secure random token string
    """
    # Use secrets module for cryptographically strong random numbers
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token

class ImportHelper:
    """Unified helper for importing music content from different services."""

    # Helper method to create tags from genres
    @staticmethod
    def create_tags_from_genre(song, genre_data):
        """
        Create tags from genre data and associate them with a song
        
        Args:
            song (Song): Song object to associate tags with
            genre_data (str or list): Genre data that could be string, list, or comma-separated values
        """
        if not genre_data:
            return
        
        genres = []
        
        # Handle different types of genre data
        if isinstance(genre_data, str):
            # Handle comma-separated genre string
            genres = [g.strip() for g in genre_data.split(',')]
        elif isinstance(genre_data, list):
            # Handle genre list
            genres = [g.strip() if isinstance(g, str) else str(g).strip() for g in genre_data]
        
        # Add each genre as a tag
        for genre_name in genres:
            if not genre_name:
                continue
                
            # Convert to lowercase for consistency
            genre_name = genre_name.lower()
            
            # Find existing tag or create new one
            tag = Tag.query.filter(Tag.name.ilike(genre_name)).first()
            if not tag:
                tag = Tag(name=genre_name)
                db.session.add(tag)
                try:
                    db.session.flush()  # Flush to get ID but don't commit yet
                except Exception as e:
                    current_app.logger.error(f"Error creating tag '{genre_name}': {e}")
                    continue
            
            # Add tag to song if not already present
            if tag not in song.tags:
                song.tags.append(tag)
                current_app.logger.info(f"Added tag '{tag.name}' to song '{song.title}'")

    @staticmethod
    def import_item(service_name, item_type, item_id):
        """
        Import a track, album, or playlist from a specific service.
        
        Args:
            service_name (str): Name of the service (e.g., 'spotify', 'deezer')
            item_type (str): Type of item ('track', 'album', 'playlist')
            item_id (str): ID of the item to import
            
        Returns:
            dict: Summary of import operation with counts of imported items
        """
        current_app.logger.info(f"Importing {item_type} {item_id} from {service_name}")
        
        result = {
            'success': False,
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': [],
            'service': service_name,
            'item_type': item_type,
            'item_id': item_id
        }
        
        try:
            if service_name.lower() == 'spotify':
                # Get Spotify client
                sp = current_app.config.get('sp')
                if not sp:
                    result['errors'].append("Spotify client not configured")
                    return result
                
                # Handle based on item type
                if item_type.lower() == 'track':
                    track_result = ImportHelper.import_spotify_track(sp, item_id)
                    result.update(track_result)
                elif item_type.lower() == 'album':
                    album_result = ImportHelper.import_spotify_album(sp, item_id)
                    result.update(album_result)
                elif item_type.lower() == 'playlist':
                    playlist_result = ImportHelper.import_spotify_playlist(sp, item_id)
                    result.update(playlist_result)
                else:
                    result['errors'].append(f"Unknown item type: {item_type}")
                    return result
                    
            elif service_name.lower() == 'deezer':
                # Get Deezer client
                deezer_client = current_app.config.get('deezer')
                if not deezer_client:
                    result['errors'].append("Deezer client not configured")
                    return result
                
                # Handle based on item type
                if item_type.lower() == 'track':
                    track_result = ImportHelper.import_deezer_track(deezer_client, item_id)
                    result.update(track_result)
                elif item_type.lower() == 'album':
                    album_result = ImportHelper.import_deezer_album(deezer_client, item_id)
                    result.update(album_result)
                elif item_type.lower() == 'playlist':
                    playlist_result = ImportHelper.import_deezer_playlist(deezer_client, item_id)
                    result.update(playlist_result)
                else:
                    result['errors'].append(f"Unknown item type: {item_type}")
                    return result
            else:
                result['errors'].append(f"Unsupported service: {service_name}")
                return result
                
            result['success'] = len(result['errors']) == 0
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing {item_type} {item_id} from {service_name}: {str(e)}")
            result['errors'].append(str(e))
            result['success'] = False
            return result

    # ------------- SPOTIFY IMPORT METHODS -------------

    @staticmethod
    def import_spotify_track(sp, track_id):
        """Import a single track from Spotify"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # First check if this Spotify track is already in our database
            existing_song = Song.query.filter_by(spotify_id=track_id).first()
            if existing_song:
                current_app.logger.info(f'Song already exists: {existing_song.title} by {existing_song.artist}')
                result['skipped_count'] += 1
                return result
                
            # Get track info from Spotify
            track_info = sp.track(track_id)
            if not track_info:
                result['errors'].append(f"Track with ID {track_id} not found on Spotify")
                result['error_count'] += 1
                return result
                
            # Try to get ISRC if available
            isrc = track_info.get('external_ids', {}).get('isrc')
            song = None
            
            # If we have an ISRC, check if a song with this ISRC already exists
            if isrc:
                existing_by_isrc = Song.query.filter(Song.isrc == isrc).first()
                if existing_by_isrc:
                    current_app.logger.info(f'Song already exists by ISRC: {existing_by_isrc.title} by {existing_by_isrc.artist}')
                    result['skipped_count'] += 1
                    return result
                
                # Get comprehensive metadata using ISRC
                current_app.logger.info(f"Looking up metadata for ISRC: {isrc}")
                metadata = get_song_metadata_by_isrc(isrc, current_app)
                
                if metadata and metadata.get("title"):
                    # Create song with enriched metadata
                    song = Song(
                        spotify_id=track_id,
                        deezer_id=metadata.get("deezer_id"),
                        title=metadata.get("title", track_info['name']),
                        artist=metadata.get("artist_name", ", ".join([artist['name'] for artist in track_info['artists']])),
                        genre=metadata.get("genre"),
                        year=metadata.get("year"),
                        preview_url=metadata.get("preview_url", track_info.get('preview_url')),
                        cover_url=metadata.get("cover_url") or (track_info['album']['images'][0]['url'] if track_info.get('album', {}).get('images') else None),
                        popularity=metadata.get("popularity", track_info.get('popularity')),
                        isrc=isrc,
                        album_name=track_info.get('album', {}).get('name'),
                        metadata_sources=','.join(metadata.get("sources", [])),
                        source='spotify',
                        spotify_preview_url=metadata.get("spotify_preview_url"),
                        deezer_preview_url=metadata.get("deezer_preview_url"),
                        apple_preview_url=metadata.get("apple_preview_url"),
                        youtube_preview_url=metadata.get("youtube_preview_url"),
                        spotify_cover_url=metadata.get("spotify_cover_url"),
                        deezer_cover_url=metadata.get("deezer_cover_url"),
                        apple_cover_url=metadata.get("apple_cover_url"),
                        additional_data=json.dumps({
                            k: v for k, v in metadata.items() 
                            if k not in ['artist_name', 'title', 'year', 'genre', 'popularity', 
                                        'preview_url', 'sources', 'isrc', 'spotify_id', 
                                        'deezer_id', 'cover_url', 'spotify_preview_url', 
                                        'deezer_preview_url', 'apple_preview_url', 
                                        'youtube_preview_url', 'spotify_cover_url', 
                                        'deezer_cover_url', 'apple_cover_url']
                        }) if metadata else None
                    )
                    current_app.logger.info(f"Metadata found from sources: {metadata.get('sources', [])}")
                else:
                    # Fallback to just Spotify data with the ISRC
                    song = ImportHelper._create_song_from_spotify(track_info, isrc)
            else:
                # No ISRC available, just use Spotify data
                song = ImportHelper._create_song_from_spotify(track_info)
            
            # We already checked for duplicates above, so we can add the song directly
            if song:
                db.session.add(song)
                
                # Create tags from genre information
                if song.genre:
                    ImportHelper.create_tags_from_genre(song, song.genre)
                
                # Also check additional data for genres
                if song.additional_data:
                    try:
                        additional_data = json.loads(song.additional_data)
                        if 'genres' in additional_data:
                            ImportHelper.create_tags_from_genre(song, additional_data['genres'])
                    except Exception as e:
                        current_app.logger.error(f"Error parsing additional data for genres: {e}")
                
                # Get audio features if this is a Spotify track - NEW ADDITION
                ImportHelper._fetch_audio_features_for_song(sp, song)
                
                db.session.commit()
                current_app.logger.info(f'Imported Spotify track {song.title} by {song.artist}')
                result['imported_count'] += 1
            else:
                current_app.logger.warning(f'Could not create song from Spotify track {track_id}')
                result['skipped_count'] += 1
                
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Spotify track {track_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result

    @staticmethod
    def import_spotify_album(sp, album_id):
        """Import all tracks from a Spotify album"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # Get album tracks from Spotify
            album_tracks = sp.album_tracks(album_id)
            if not album_tracks or 'items' not in album_tracks:
                result['errors'].append(f"Album with ID {album_id} not found on Spotify")
                result['error_count'] += 1
                return result
                
            # Import each track in the album
            for track in album_tracks['items']:
                if track and 'id' in track:
                    track_result = ImportHelper.import_spotify_track(sp, track['id'])
                    result['imported_count'] += track_result['imported_count']
                    result['skipped_count'] += track_result['skipped_count']
                    result['error_count'] += track_result['error_count']
                    result['errors'].extend(track_result['errors'])
            
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Spotify album {album_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result

    @staticmethod
    def import_spotify_playlist(sp, playlist_id):
        """Import all tracks from a Spotify playlist"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # Get playlist tracks from Spotify
            tracks_info = sp.playlist_tracks(playlist_id)
            if not tracks_info or 'items' not in tracks_info:
                result['errors'].append(f"Playlist with ID {playlist_id} not found on Spotify")
                result['error_count'] += 1
                return result
                
            # Import each track in the playlist
            items = tracks_info.get('items', [])
            for item in items:
                # 'track' can be None if it's a local or unavailable track
                track_obj = item.get('track')
                if track_obj and 'id' in track_obj:
                    track_result = ImportHelper.import_spotify_track(sp, track_obj['id'])
                    result['imported_count'] += track_result['imported_count']
                    result['skipped_count'] += track_result['skipped_count']
                    result['error_count'] += track_result['error_count']
                    result['errors'].extend(track_result['errors'])
            
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Spotify playlist {playlist_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result
            
    @staticmethod
    def _create_song_from_spotify(track_info, isrc=None):
        """Create a song object from Spotify track data"""
        # Basic song with just Spotify data
        preview_url = track_info.get('preview_url')
        cover_url = track_info['album']['images'][0]['url'] if track_info.get('album', {}).get('images') else None
        
        # Extract year from album if available
        year = None
        if track_info.get('album') and track_info['album'].get('release_date'):
            year = track_info['album']['release_date'][:4]
        
        # Try to get genre from album
        genre = None

        # Create song object
        return Song(
            spotify_id=track_info['id'],
            title=track_info['name'],
            artist=", ".join([artist['name'] for artist in track_info['artists']]),
            genre=genre,
            year=year,
            preview_url=preview_url,
            cover_url=cover_url,
            popularity=track_info.get('popularity'),
            isrc=isrc,
            album_name=track_info.get('album', {}).get('name'),
            metadata_sources='spotify',
            source='spotify'
        )

    @staticmethod
    def _fetch_audio_features_for_song(sp, song):
        """Fetch audio features for a Spotify song and update the song object"""
        try:
            audio_features = sp.audio_features(song.spotify_id)
            if audio_features and len(audio_features) > 0:
                features = audio_features[0]
                song.danceability = features.get('danceability')
                song.energy = features.get('energy')
                song.key = features.get('key')
                song.loudness = features.get('loudness')
                song.mode = features.get('mode')
                song.speechiness = features.get('speechiness')
                song.acousticness = features.get('acousticness')
                song.instrumentalness = features.get('instrumentalness')
                song.liveness = features.get('liveness')
                song.valence = features.get('valence')
                song.tempo = features.get('tempo')
                current_app.logger.info(f"Audio features fetched for song '{song.title}'")
        except Exception as e:
            current_app.logger.error(f"Error fetching audio features for song '{song.title}': {str(e)}")

    # ------------- DEEZER IMPORT METHODS -------------

    @staticmethod
    def import_deezer_track(deezer_client, track_id):
        """Import a single track from Deezer"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # First check if this Deezer track is already in our database
            existing_song = Song.query.filter_by(deezer_id=track_id).first()
            if existing_song:
                current_app.logger.info(f'Song already exists: {existing_song.title} by {existing_song.artist}')
                result['skipped_count'] += 1
                return result
                
            # Get track info from Deezer
            track = deezer_client.get_track(track_id)
            if not track:
                result['errors'].append(f"Track with ID {track_id} not found on Deezer")
                result['error_count'] += 1
                return result
                
            # Check if ISRC is available
            isrc = track.get('isrc')
            song = None
            
            # If we have an ISRC, check if a song with this ISRC already exists
            if isrc:
                existing_by_isrc = Song.query.filter(Song.isrc == isrc).first()
                if existing_by_isrc:
                    current_app.logger.info(f'Song already exists by ISRC: {existing_by_isrc.title} by {existing_by_isrc.artist}')
                    result['skipped_count'] += 1
                    return result
                
                # Use metadata helper function to get comprehensive metadata
                current_app.logger.info(f"Looking up metadata for ISRC: {isrc}")
                metadata = get_song_metadata_by_isrc(isrc, current_app)
                
                # Use metadata if found, otherwise fall back to Deezer data only
                if metadata and metadata.get("title"):
                    song = Song(
                        deezer_id=track.get('id'),
                        spotify_id=metadata.get("spotify_id"),
                        title=metadata.get("title", track.get('title')),
                        artist=metadata.get("artist_name", track.get('artist', {}).get('name') if track.get('artist') else 'Unknown Artist'),
                        preview_url=metadata.get("preview_url", track.get('preview')),
                        cover_url=metadata.get("cover_url") or track.get('album', {}).get('cover'),
                        genre=metadata.get("genre"),
                        year=metadata.get("year"),
                        popularity=metadata.get("popularity"),
                        isrc=isrc,
                        album_name=track.get('album', {}).get('title'),
                        metadata_sources=','.join(metadata.get("sources", [])),
                        source='deezer',
                        spotify_preview_url=metadata.get("spotify_preview_url"),
                        deezer_preview_url=metadata.get("deezer_preview_url"),
                        apple_preview_url=metadata.get("apple_preview_url"),
                        youtube_preview_url=metadata.get("youtube_preview_url"),
                        spotify_cover_url=metadata.get("spotify_cover_url"),
                        deezer_cover_url=metadata.get("deezer_cover_url"),
                        apple_cover_url=metadata.get("apple_cover_url"),
                        additional_data=json.dumps(
                            {k: v for k, v in metadata.items() if k not in ['artist_name', 'title', 'year', 'genre', 
                                                                           'popularity', 'preview_url', 'sources', 
                                                                           'isrc', 'spotify_id', 'deezer_id', 'cover_url', 
                                                                           'spotify_preview_url', 'deezer_preview_url', 
                                                                           'apple_preview_url', 'youtube_preview_url',
                                                                           'spotify_cover_url', 'deezer_cover_url', 
                                                                           'apple_cover_url']}
                        ) if metadata else None
                    )
                    current_app.logger.info(f"Metadata found from sources: {metadata.get('sources', [])}")
                else:
                    # Fallback to just Deezer data
                    song = Song(
                        deezer_id=track.get('id'),
                        title=track.get('title'),
                        artist=track.get('artist', {}).get('name') if track.get('artist') else 'Unknown Artist',
                        preview_url=track.get('preview'),
                        cover_url=track.get('album', {}).get('cover'),
                        album_name=track.get('album', {}).get('title'),
                        metadata_sources='deezer',
                        source='deezer'
                    )
            else:
                # No ISRC available, just use Deezer data
                song = Song(
                    deezer_id=track.get('id'),
                    title=track.get('title'),
                    artist=track.get('artist', {}).get('name') if track.get('artist') else 'Unknown Artist',
                    preview_url=track.get('preview'),
                    cover_url=track.get('album', {}).get('cover'),
                    album_name=track.get('album', {}).get('title'),
                    metadata_sources='deezer',
                    source='deezer'
                )

            # We already checked for duplicates above, so we can add the song directly
            if song:
                db.session.add(song)
                
                # Create tags from genre information
                if song.genre:
                    ImportHelper.create_tags_from_genre(song, song.genre)
                
                # Also check additional data for genres
                if song.additional_data:
                    try:
                        additional_data = json.loads(song.additional_data)
                        if 'genres' in additional_data:
                            ImportHelper.create_tags_from_genre(song, additional_data['genres'])
                    except Exception as e:
                        current_app.logger.error(f"Error parsing additional data for genres: {e}")
                
                db.session.commit()
                current_app.logger.info(f'Imported Deezer track {song.title} by {song.artist}')
                result['imported_count'] += 1
            else:
                current_app.logger.warning(f'Could not create song from Deezer track {track_id}')
                result['skipped_count'] += 1
                
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Deezer track {track_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result

    @staticmethod
    def import_deezer_album(deezer_client, album_id):
        """Import all tracks from a Deezer album"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # Get album info from Deezer
            album = deezer_client.get_album(album_id)
            if not album or not album.get('tracks') or not album['tracks'].get('data'):
                result['errors'].append(f"Album with ID {album_id} not found on Deezer")
                result['error_count'] += 1
                return result
                
            # Import each track in the album
            tracks = album['tracks']['data']
            for track in tracks:
                track_id = track.get('id')
                if track_id:
                    track_result = ImportHelper.import_deezer_track(deezer_client, track_id)
                    result['imported_count'] += track_result['imported_count']
                    result['skipped_count'] += track_result['skipped_count']
                    result['error_count'] += track_result['error_count']
                    result['errors'].extend(track_result['errors'])
            
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Deezer album {album_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result

    @staticmethod
    def import_deezer_playlist(deezer_client, playlist_id):
        """Import all tracks from a Deezer playlist"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            # Get playlist info from Deezer
            playlist = deezer_client.get_playlist(playlist_id)
            if not playlist or not playlist.get('tracks') or not playlist['tracks'].get('data'):
                result['errors'].append(f"Playlist with ID {playlist_id} not found on Deezer")
                result['error_count'] += 1
                return result
                
            # Import each track in the playlist
            tracks = playlist['tracks']['data']
            for track in tracks:
                track_id = track.get('id')
                if track_id:
                    track_result = ImportHelper.import_deezer_track(deezer_client, track_id)
                    result['imported_count'] += track_result['imported_count']
                    result['skipped_count'] += track_result['skipped_count']
                    result['error_count'] += track_result['error_count']
                    result['errors'].extend(track_result['errors'])
            
            return result
            
        except Exception as e:
            current_app.logger.error(f"Error importing Deezer playlist {playlist_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result