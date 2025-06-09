"""
Unified import helper for importing music content across different services.
This module provides consistent import functionality for tracks, albums, and playlists
from various music streaming services like Spoti                try:
                    imported_songs = ImportHelper.import_spotify_playlist(spotify_client, item_id)
                    if not imported_songs or imported_songs.get('imported_count', 0) == 0:
                        current_app.logger.warning(f"Spotify playlist import returned empty result for playlist ID: {item_id}")
                        return {
                            'imported_count': 0,
                            'skipped_count': 0,
                            'error_count': 1,
                            'errors': [f"No songs found in Spotify playlist {item_id} or playlist import failed."]
                        }
                    return imported_songser.
"""
import json
import logging
import secrets
import string
import traceback
from flask import current_app, flash, session
from flask_login import current_user
from authlib.integrations.base_client.errors import MissingTokenError # Corrected import path
from httpx import HTTPStatusError
from musicround.models import Song, Tag, db
from musicround.helpers.metadata import get_song_metadata_by_isrc
from musicround.helpers.auth_helpers import oauth, update_oauth_tokens # Ensure update_oauth_tokens is imported
from datetime import datetime # Ensure datetime is imported

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

    @staticmethod
    def _create_song_from_spotify(track_info):
        """Helper to create a Song object from Spotify track_info when ISRC/rich metadata is not found."""
        if not track_info:
            return None
        
        artist_names = ", ".join([artist['name'] for artist in track_info.get('artists', [])])
        cover_url = None
        if track_info.get('album', {}).get('images'):
            cover_url = track_info['album']['images'][0]['url']

        song = Song(
            spotify_id=track_info.get('id'),
            title=track_info.get('name'),
            artist=artist_names,
            album_name=track_info.get('album', {}).get('name'),
            preview_url=track_info.get('preview_url'),
            cover_url=cover_url,
            popularity=track_info.get('popularity'),
            source='spotify'
        )
        release_date = track_info.get('album', {}).get('release_date')
        if release_date:
            try:
                song.year = int(release_date.split('-')[0])
            except (ValueError, IndexError, TypeError):
                current_app.logger.warning(f"Could not parse year from release_date: {release_date} for track {song.title}")
        
        return song

    @staticmethod
    def _fetch_audio_features_for_song(sp, song_obj, spotify_track_id, token=None): # Added token parameter
        """Fetches audio features for a given song and updates the song object."""
        if not spotify_track_id:
            current_app.logger.warning(f"Cannot fetch audio features: Spotify track ID missing for song {song_obj.title if song_obj else 'Unknown'}.")
            return

        if not token and (not current_user or not current_user.is_authenticated or not current_user.spotify_token):
            current_app.logger.error(f"Cannot fetch audio features for {spotify_track_id}: User not authenticated or no Spotify token, and no explicit token passed.")
            return
        
        # Construct token if not passed explicitly but current_user is available
        # This provides a fallback if the calling context didn't pass it but expects this method to handle it.
        # However, for consistency, it's better if the caller (import_spotify_track) always passes it.
        token_to_use = token
        if not token_to_use:
            expires_at_timestamp = None
            if current_user.spotify_token_expiry:
                if isinstance(current_user.spotify_token_expiry, datetime):
                    expires_at_timestamp = int(current_user.spotify_token_expiry.timestamp())
                else:
                    try:
                        expires_at_timestamp = int(datetime.fromisoformat(str(current_user.spotify_token_expiry)).timestamp())
                    except ValueError:
                        pass # Logged by caller
            token_to_use = {
                'access_token': current_user.spotify_token,
                'refresh_token': current_user.spotify_refresh_token,
                'token_type': 'Bearer',
                'expires_at': expires_at_timestamp
            }
            current_app.logger.info(f"Constructed token within _fetch_audio_features_for_song for {spotify_track_id}")

        original_access_token = token_to_use.get('access_token') if token_to_use else None

        try:
            current_app.logger.info(f"Fetching audio features for Spotify track ID: {spotify_track_id}")
            audio_features_resp = sp.get(f'audio-features/{spotify_track_id}', token=token_to_use) # Pass token
            audio_features_resp.raise_for_status()
            features = audio_features_resp.json()

            if sp.token and original_access_token and sp.token.get('access_token') != original_access_token:
                current_app.logger.info(f"Spotify token refreshed during _fetch_audio_features for {spotify_track_id}, user {current_user.id}.")
                if update_oauth_tokens(current_user, sp.token, 'spotify'):
                    # token_to_use = sp.token # Update local token if it were to be used again in this function
                    current_app.logger.info(f"Refreshed Spotify token saved (audio features) for user {current_user.id}.")
                else:
                    current_app.logger.error(f"Failed to save refreshed Spotify token (audio features) for user {current_user.id}.")

            if features:
                song_obj.danceability = features.get('danceability')
                song_obj.energy = features.get('energy')
                song_obj.key = features.get('key')
                song_obj.loudness = features.get('loudness')
                song_obj.mode = features.get('mode')
                song_obj.speechiness = features.get('speechiness')
                song_obj.acousticness = features.get('acousticness')
                song_obj.instrumentalness = features.get('instrumentalness')
                song_obj.liveness = features.get('liveness')
                song_obj.valence = features.get('valence')
                song_obj.tempo = features.get('tempo')
                song_obj.duration_ms = features.get('duration_ms')
                song_obj.time_signature = features.get('time_signature')
                
                current_app.logger.info(f"Audio features updated for song: {song_obj.title}")
            else:
                current_app.logger.warning(f"No audio features returned for Spotify track ID: {spotify_track_id}")

        except MissingTokenError as mte:
            current_app.logger.error(f"Authlib MissingTokenError fetching audio features for {spotify_track_id}: {str(mte)}")
        except HTTPStatusError as hse:
            current_app.logger.error(f"HTTPStatusError ({hse.response.status_code}) fetching audio features for {spotify_track_id}: {hse.response.text}")
        except Exception as e:
            current_app.logger.error(f"Error fetching audio features for {spotify_track_id}: {str(e)}", exc_info=True)

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
                    db.session.flush()
                except Exception as e:
                    current_app.logger.error(f"Error creating tag '{genre_name}': {e}")
                    continue
            
            # Add tag to song if not already present
            if tag not in song.tags:
                song.tags.append(tag)
                current_app.logger.info(f"Added tag '{tag.name}' to song '{song.title}'")

    @staticmethod
    def import_item(service_name, item_type, item_id, oauth_spotify=None): # Added oauth_spotify parameter
        """
        Generic import function to import items from various services.
        
        Args:
            service_name (str): The name of the service (e.g., 'spotify', 'deezer').
            item_type (str): The type of item to import (e.g., 'track', 'album', 'playlist').
            item_id (str): The ID of the item to import.
            oauth_spotify: Optional Authlib Spotify client instance.
            
        Returns:
            dict: A dictionary containing import statistics (imported_count, skipped_count, error_count, errors).
        """
        current_app.logger.info(f"Import item called: service='{service_name}', type='{item_type}', id='{item_id}'")
        if service_name.lower() == 'spotify':
            # Use the provided oauth_spotify client, or fallback to the global one if not provided
            spotify_client = oauth_spotify if oauth_spotify else oauth.spotify
            
            if not spotify_client:
                current_app.logger.error("Spotify client not available for import.")
                return {
                    'imported_count': 0,
                    'skipped_count': 0,
                    'error_count': 1,
                    'errors': ["Spotify client not configured or passed correctly."]
                }
            if item_type.lower() == 'track':
                return ImportHelper.import_spotify_track(spotify_client, item_id)
            elif item_type.lower() == 'album':
                try:
                    imported_songs = ImportHelper.import_spotify_album(spotify_client, item_id)
                    if not imported_songs or len(imported_songs) == 0:
                        current_app.logger.warning(f"Spotify album import returned empty result for album ID: {item_id}")
                        return {
                            'imported_count': 0,
                            'skipped_count': 0,
                            'error_count': 1,
                            'errors': [f"No songs found in Spotify album {item_id} or album import failed."]
                        }
                    return imported_songs
                except Exception as e:
                    current_app.logger.error(f"Exception occurred while importing Spotify album {item_id}: {str(e)}")
                    current_app.logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        'imported_count': 0,
                        'skipped_count': 0,
                        'error_count': 1,
                        'errors': [f"Failed to import Spotify album {item_id}: {str(e)}"]
                    }
            elif item_type.lower() == 'playlist':
                try:
                    imported_songs = ImportHelper.import_spotify_playlist(spotify_client, item_id)
                    if not imported_songs or imported_songs.get('imported_count', 0) == 0:
                        current_app.logger.warning(f"Spotify playlist import returned empty result for playlist ID: {item_id}")
                        return {
                            'imported_count': 0,
                            'skipped_count': 0,
                            'error_count': 1,
                            'errors': [f"No songs found in Spotify playlist {item_id} or playlist import failed."]
                        }
                    return imported_songs
                except Exception as e:
                    current_app.logger.error(f"Exception occurred while importing Spotify playlist {item_id}: {str(e)}")
                    current_app.logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        'imported_count': 0,
                        'skipped_count': 0,
                        'error_count': 1,
                        'errors': [f"Failed to import Spotify playlist {item_id}: {str(e)}"]
                    }
            else:
                current_app.logger.error(f"Unsupported item_type '{item_type}' for Spotify import.")
                return {
                    'imported_count': 0,
                    'skipped_count': 0,
                    'error_count': 1,
                    'errors': [f"Unsupported item type '{item_type}' for Spotify."]
                }
        elif service_name.lower() == 'deezer':
            # Ensure we have the Deezer client available
            # The Deezer client is typically initialized in create_app and stored in app.config['deezer']
            deezer_client = current_app.config.get('deezer')
            if not deezer_client:
                current_app.logger.error("Deezer client not found in app.config.")
                return {
                    'imported_count': 0,
                    'skipped_count': 0,
                    'error_count': 1,
                    'errors': ["Deezer client not configured."]
                }
            lastfm_api_key = current_app.config.get('LASTFM_API_KEY')
            
            if item_type.lower() == 'track':
                song, was_new = deezer_client.import_track(item_id, lastfm_api_key=lastfm_api_key)
                if song:
                    if was_new:
                        return {'imported_count': 1, 'skipped_count': 0, 'error_count': 0, 'errors': []}
                    else:
                        return {'imported_count': 0, 'skipped_count': 1, 'error_count': 0, 'errors': []}
                else:
                    return {'imported_count': 0, 'skipped_count': 0, 'error_count': 1, 'errors': [f"Failed to import Deezer track {item_id}."]}
            elif item_type.lower() == 'album':
                try:
                    result = deezer_client.import_album(item_id, lastfm_api_key=lastfm_api_key)
                    imported_count = result.get('imported_count', 0)
                    skipped_count = result.get('skipped_count', 0)
                    
                    if imported_count == 0 and skipped_count == 0:
                        current_app.logger.warning(f"Deezer album import returned empty result for album ID: {item_id}")
                        return {
                            'imported_count': 0,
                            'skipped_count': 0,
                            'error_count': 1,
                            'errors': [f"No songs found in Deezer album {item_id} or album import failed."]
                        }
                    return {
                        'imported_count': imported_count,
                        'skipped_count': skipped_count,
                        'error_count': 0,
                        'errors': []
                    }
                except Exception as e:
                    current_app.logger.error(f"Exception occurred while importing Deezer album {item_id}: {str(e)}")
                    current_app.logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        'imported_count': 0,
                        'skipped_count': 0,
                        'error_count': 1,
                        'errors': [f"Failed to import Deezer album {item_id}: {str(e)}"]
                    }
            elif item_type.lower() == 'playlist':
                try:
                    imported_songs = deezer_client.import_playlist(item_id, lastfm_api_key=lastfm_api_key)
                    if not imported_songs or len(imported_songs) == 0:
                        current_app.logger.warning(f"Deezer playlist import returned empty result for playlist ID: {item_id}")
                        return {
                            'imported_count': 0,
                            'skipped_count': 0,
                            'error_count': 1,
                            'errors': [f"No songs found in Deezer playlist {item_id} or playlist import failed."]
                        }
                    return {
                        'imported_count': len(imported_songs),
                        'skipped_count': 0,
                        'error_count': 0,
                        'errors': []
                    }
                except Exception as e:
                    current_app.logger.error(f"Exception occurred while importing Deezer playlist {item_id}: {str(e)}")
                    current_app.logger.error(f"Traceback: {traceback.format_exc()}")
                    return {
                        'imported_count': 0,
                        'skipped_count': 0,
                        'error_count': 1,
                        'errors': [f"Failed to import Deezer playlist {item_id}: {str(e)}"]
                    }
            else:
                current_app.logger.error(f"Unsupported item_type '{item_type}' for Deezer import.")
                return {
                    'imported_count': 0,
                    'skipped_count': 0,
                    'error_count': 1,
                    'errors': [f"Unsupported item type '{item_type}' for Deezer."]
                }
        else:
            current_app.logger.error(f"Unsupported service_name '{service_name}'.")
            return {
                'imported_count': 0,
                'skipped_count': 0,
                'error_count': 1,
                'errors': [f"Unsupported service '{service_name}'."]
            }

    @staticmethod
    def import_spotify_track(sp, track_id):
        """Import a single track from Spotify"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': []
        }

        if not current_user or not current_user.is_authenticated or not current_user.spotify_token:
            current_app.logger.error(f"Import Spotify track: User not authenticated or no Spotify token for track {track_id}.")
            result['errors'].append("User not authenticated or no Spotify token.")
            result['error_count'] += 1
            return result

        expires_at_timestamp = None
        if current_user.spotify_token_expiry:
            if isinstance(current_user.spotify_token_expiry, datetime):
                expires_at_timestamp = int(current_user.spotify_token_expiry.timestamp())
            else:
                try:
                    expires_at_timestamp = int(datetime.fromisoformat(str(current_user.spotify_token_expiry)).timestamp())
                except ValueError:
                    current_app.logger.warning(f"Could not parse spotify_token_expiry for user {current_user.id} in import_spotify_track.")
        
        authlib_token_for_request = {
            'access_token': current_user.spotify_token,
            'refresh_token': current_user.spotify_refresh_token,
            'token_type': 'Bearer',
            'expires_at': expires_at_timestamp
        }
        
        try:
            current_app.logger.info(f"Attempting to import Spotify track ID: {track_id} for user {current_user.id}")
            existing_song = Song.query.filter_by(spotify_id=track_id).first()
            if existing_song:
                current_app.logger.info(f'Spotify track ID {track_id} already exists as song: {existing_song.title} by {existing_song.artist}')
                result['skipped_count'] += 1
                return result
                
            resp = sp.get(f'tracks/{track_id}', token=authlib_token_for_request)
            resp.raise_for_status()
            track_info = resp.json()

            if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                current_app.logger.info(f"Spotify token refreshed during import_spotify_track (track ID: {track_id}) for user {current_user.id}.")
                if update_oauth_tokens(current_user, sp.token, 'spotify'):
                    authlib_token_for_request = sp.token # Update local token for any further use in this scope
                    current_app.logger.info(f"Refreshed Spotify token saved for user {current_user.id} after track import.")
                else:
                    current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id} after track import.")

            if not track_info:
                result['errors'].append(f"Track with ID {track_id} not found on Spotify or empty response.")
                result['error_count'] += 1
                current_app.logger.warning(f"Track with ID {track_id} not found on Spotify or empty response.")
                return result
                
            isrc = track_info.get('external_ids', {}).get('isrc')
            song = None
            
            if isrc:
                current_app.logger.info(f"Track {track_id} has ISRC: {isrc}. Checking existing songs by ISRC.")
                existing_by_isrc = Song.query.filter(Song.isrc == isrc).first()
                if existing_by_isrc:
                    current_app.logger.info(f'Song already exists by ISRC {isrc}: {existing_by_isrc.title} by {existing_by_isrc.artist}. Updating Spotify ID if needed.')
                    if not existing_by_isrc.spotify_id:
                        existing_by_isrc.spotify_id = track_id
                    # Potentially update other Spotify-specific fields if they are missing or different
                    db.session.commit()
                    result['skipped_count'] += 1
                    return result
                
                current_app.logger.info(f"Looking up comprehensive metadata for ISRC: {isrc}")
                metadata = get_song_metadata_by_isrc(isrc, current_app)
                
                if metadata and metadata.get("title"):
                    current_app.logger.info(f"Creating song for ISRC {isrc} using enriched metadata.")
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
                        source='spotify', # Indicate primary import source
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
                    current_app.logger.info(f"Enriched metadata found from sources: {metadata.get('sources', [])} for track {track_id}")
                else:
                    current_app.logger.info(f"No comprehensive metadata found for ISRC {isrc}, or metadata was incomplete. Falling back for track {track_id}.")
            
            if song is None: # If no ISRC, or ISRC lookup failed to produce a song object
                current_app.logger.info(f"Creating song for track {track_id} using basic Spotify data (no ISRC or failed ISRC enrichment).")
                song = ImportHelper._create_song_from_spotify(track_info) # Ensure this helper is robust
            
            if song:
                # Ensure spotify_id is set if created via ISRC path primarily
                if not song.spotify_id: song.spotify_id = track_id
                if not song.source: song.source = 'spotify'


                db.session.add(song)
                try:
                    db.session.flush() # Flush to get song.id for relationships if needed, and catch early DB errors
                except Exception as e_flush:
                    current_app.logger.error(f"Error flushing session for song {song.title} (Spotify ID: {track_id}): {str(e_flush)}", exc_info=True)
                    db.session.rollback()
                    result['errors'].append(f"DB flush error for {song.title}: {str(e_flush)}")
                    result['error_count'] += 1
                    return result

                # Fetch and apply genres if not already set by metadata service
                if not song.genre and track_info.get('album'):
                    album_id_for_genre = track_info['album'].get('id')
                    if album_id_for_genre:
                        try:
                            # Use the potentially refreshed token for this new call
                            album_details_resp = sp.get(f'albums/{album_id_for_genre}', token=authlib_token_for_request)
                            album_details_resp.raise_for_status()
                            album_details = album_details_resp.json()

                            # Check for token refresh again after this call
                            if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                                current_app.logger.info(f"Spotify token refreshed during album genre fetch for track {track_id}, user {current_user.id}.")
                                if update_oauth_tokens(current_user, sp.token, 'spotify'):
                                    authlib_token_for_request = sp.token 
                                    current_app.logger.info(f"Refreshed Spotify token saved (album genre fetch) for user {current_user.id}.")
                                else:
                                    current_app.logger.error(f"Failed to save refreshed Spotify token (album genre fetch) for user {current_user.id}.")

                            if album_details.get('genres'):
                                current_app.logger.info(f"Found genres from album {album_id_for_genre} for track {track_id}: {album_details['genres']}")
                                ImportHelper.create_tags_from_genre(song, album_details['genres'])
                                if not song.genre: # Set primary genre field if still empty
                                     song.genre = ", ".join(album_details['genres']) if isinstance(album_details['genres'], list) else str(album_details['genres'])
                        except Exception as e_album_genre:
                            current_app.logger.warning(f"Could not fetch/process album genres for track {track_id}: {str(e_album_genre)}")
                
                # Process genres from additional_data if present
                if song.additional_data:
                    try:
                        additional_data_json = json.loads(song.additional_data)
                        if 'genres' in additional_data_json:
                             ImportHelper.create_tags_from_genre(song, additional_data_json['genres'])
                        elif 'tags' in additional_data_json: # Support 'tags' field as well
                             ImportHelper.create_tags_from_genre(song, additional_data_json['tags'])
                    except (json.JSONDecodeError, TypeError):
                        current_app.logger.warning(f"Could not parse additional_data for genres for song {song.title} (Spotify ID: {track_id})")
                
                # Fetch audio features
                ImportHelper._fetch_audio_features_for_song(sp, song, track_id, token=authlib_token_for_request) # Pass token
                
                # Final commit                db.session.commit()
                result['imported_count'] += 1
                result['song_id'] = song.id  # Add the song ID to the result
                current_app.logger.info(f"Successfully imported Spotify track {track_id} as '{song.title}' with ID {song.id}")
            else:
                result['errors'].append(f"Failed to create song object for track {track_id}")
                result['error_count'] += 1
                current_app.logger.error(f"Song object creation failed for Spotify track ID: {track_id}")
            
            return result
            
        except MissingTokenError as mte:
            # This specific error should ideally be prevented by the explicit token passing
            current_app.logger.error(f"Authlib MissingTokenError (should not happen with explicit token) for Spotify track {track_id}: {str(mte)}", exc_info=True)
            result['errors'].append(f"Spotify authentication error (missing token) for track {track_id}.")
            result['error_count'] += 1
            db.session.rollback()
            return result
        except HTTPStatusError as hse:
            status_code = hse.response.status_code
            error_text = hse.response.text
            current_app.logger.error(f"HTTPStatusError ({status_code}) importing Spotify track {track_id}: {error_text}", exc_info=True)
            error_detail = f"Spotify API error ({status_code}) for track {track_id}."
            try:
                error_json = hse.response.json()
                if error_json.get('error', {}).get('message'):
                    error_detail = f"Spotify error for track {track_id}: {error_json['error']['message']}"
            except ValueError: 
                pass 
            result['errors'].append(error_detail)
            result['error_count'] += 1
            return result
        except Exception as e:
            current_app.logger.error(f"Generic error importing Spotify track {track_id}: {str(e)}", exc_info=True)
            result['errors'].append(f"Unexpected error for track {track_id}: {str(e)}")
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

        if not current_user or not current_user.is_authenticated or not current_user.spotify_token:
            current_app.logger.error(f"Import Spotify album: User not authenticated or no Spotify token for album {album_id}.")
            result['errors'].append("User not authenticated or no Spotify token.")
            result['error_count'] += 1
            return result

        expires_at_timestamp = None
        if current_user.spotify_token_expiry:
            if isinstance(current_user.spotify_token_expiry, datetime):
                expires_at_timestamp = int(current_user.spotify_token_expiry.timestamp())
            else:
                try:
                    expires_at_timestamp = int(datetime.fromisoformat(str(current_user.spotify_token_expiry)).timestamp())
                except ValueError:
                    current_app.logger.warning(f"Could not parse spotify_token_expiry for user {current_user.id} in import_spotify_album.")

        authlib_token_for_request = {
            'access_token': current_user.spotify_token,
            'refresh_token': current_user.spotify_refresh_token,
            'token_type': 'Bearer',
            'expires_at': expires_at_timestamp
        }
        
        try:
            current_app.logger.info(f"Starting import for Spotify album ID: {album_id} for user {current_user.id}")
            album_resp = sp.get(f'albums/{album_id}', token=authlib_token_for_request) 
            album_resp.raise_for_status()
            album_data = album_resp.json()
            album_name = album_data.get('name', 'Unknown Album')
            current_app.logger.info(f"Importing tracks from album: '{album_name}' (ID: {album_id})")

            if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                current_app.logger.info(f"Spotify token refreshed during album metadata fetch (album ID: {album_id}) for user {current_user.id}.")
                if update_oauth_tokens(current_user, sp.token, 'spotify'):
                    authlib_token_for_request = sp.token # Update local token
                    current_app.logger.info(f"Refreshed Spotify token saved for user {current_user.id} after album metadata.")
                else:
                    current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id} after album metadata.")

            tracks_url = f'albums/{album_id}/tracks' # Initial URL
            # Spotify API for album tracks might be relative, ensure sp.get handles it or construct full URL if needed.
            # Authlib's client.get usually handles relative URLs by joining with the base_url.

            page_count = 0
            while tracks_url:
                page_count += 1
                current_app.logger.info(f"Fetching page {page_count} of tracks for album '{album_name}' from URL: {tracks_url}")
                
                # For subsequent calls in pagination, use the potentially updated authlib_token_for_request
                tracks_resp = sp.get(tracks_url, token=authlib_token_for_request)
                tracks_resp.raise_for_status()
                tracks_data = tracks_resp.json()

                if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                    current_app.logger.info(f"Spotify token refreshed during album tracks fetch (album ID: {album_id}, page: {page_count}) for user {current_user.id}.")
                    if update_oauth_tokens(current_user, sp.token, 'spotify'):
                        authlib_token_for_request = sp.token # Update local token for next iteration / track import
                        current_app.logger.info(f"Refreshed Spotify token saved for user {current_user.id} (album tracks page {page_count}).")
                    else:
                        current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id} (album tracks page {page_count}).")
                
                track_items = tracks_data.get('items', [])
                if not track_items and page_count == 1:
                    current_app.logger.warning(f"No tracks found in album '{album_name}' (ID: {album_id}) on the first page.")
                
                for track_item_simplified in track_items:
                    track_id = track_item_simplified.get('id')
                    if not track_id:
                        current_app.logger.warning(f"Skipping track with no ID in album '{album_name}' (ID: {album_id})")
                        result['errors'].append(f"Found a track with no ID in album {album_id}.")
                        result['error_count'] +=1
                        continue
                    
                    # Call import_spotify_track. It will handle its own token now.
                    track_import_result = ImportHelper.import_spotify_track(sp, track_id)
                    
                    result['imported_count'] += track_import_result.get('imported_count', 0)
                    result['skipped_count'] += track_import_result.get('skipped_count', 0)
                    result['error_count'] += track_import_result.get('error_count', 0)
                    if track_import_result.get('errors'):
                        result['errors'].extend(track_import_result['errors'])
                
                tracks_url = tracks_data.get('next') 
                if tracks_url:
                    current_app.logger.info(f"Next page of tracks for album '{album_name}' at: {tracks_url}")
                else:
                    current_app.logger.info(f"No more track pages for album '{album_name}' (ID: {album_id}).")
            db.session.commit() # Commit any changes made by track imports

        except MissingTokenError as mte:
            current_app.logger.error(f"Authlib MissingTokenError while importing Spotify album {album_id}: {str(mte)}", exc_info=True)
            result['errors'].append(f"Spotify authentication error (missing token) for album {album_id}.")
            result['error_count'] += 1 
        except HTTPStatusError as hse:
            status_code = hse.response.status_code
            error_text = hse.response.text
            current_app.logger.error(f"HTTPStatusError ({status_code}) importing Spotify album {album_id}: {error_text}", exc_info=True)
            error_detail = f"Spotify API error ({status_code}) for album {album_id}."
            try:
                error_json = hse.response.json()
                if error_json.get('error', {}).get('message'):
                    error_detail = f"Spotify error for album {album_id}: {error_json['error']['message']}"
            except ValueError: 
                pass 
            result['errors'].append(error_detail)
            result['error_count'] += 1
        except Exception as e:
            current_app.logger.error(f"Unexpected error importing Spotify album {album_id}: {str(e)}", exc_info=True)
            result['errors'].append(f"Failed to import album {album_id} due to unexpected error: {str(e)}")
            result['error_count'] += 1
        
        return result

    @staticmethod
    def import_spotify_playlist(sp, playlist_id):
        """Import all tracks from a Spotify playlist"""
        result = {
            'imported_count': 0,
            'skipped_count': 0,
            'error_count': 0,
            'errors': [],
            'imported_song_ids': []  # Track IDs of successfully imported songs
        }

        if not current_user or not current_user.is_authenticated or not current_user.spotify_token:
            current_app.logger.error(f"Import Spotify playlist: User not authenticated or no Spotify token for playlist {playlist_id}.")
            result['errors'].append("User not authenticated or no Spotify token.")
            result['error_count'] += 1
            return result

        expires_at_timestamp = None
        if current_user.spotify_token_expiry:
            if isinstance(current_user.spotify_token_expiry, datetime):
                expires_at_timestamp = int(current_user.spotify_token_expiry.timestamp())
            else:
                try:
                    expires_at_timestamp = int(datetime.fromisoformat(str(current_user.spotify_token_expiry)).timestamp())
                except ValueError:
                    current_app.logger.warning(f"Could not parse spotify_token_expiry for user {current_user.id} in import_spotify_playlist.")
        
        authlib_token_for_request = {
            'access_token': current_user.spotify_token,
            'refresh_token': current_user.spotify_refresh_token,
            'token_type': 'Bearer',
            'expires_at': expires_at_timestamp
        }

        try:
            current_app.logger.info(f"Starting import for Spotify playlist ID: {playlist_id} for user {current_user.id}")
            # First, get playlist details to get the name (optional, but good for logging)
            playlist_details_resp = sp.get(f'playlists/{playlist_id}?fields=name,tracks.next', token=authlib_token_for_request)
            playlist_details_resp.raise_for_status()
            playlist_data = playlist_details_resp.json()
            playlist_name = playlist_data.get('name', 'Unknown Playlist')
            current_app.logger.info(f"Importing tracks from playlist: '{playlist_name}' (ID: {playlist_id})")

            if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                current_app.logger.info(f"Spotify token refreshed during playlist metadata fetch (playlist ID: {playlist_id}) for user {current_user.id}.")
                if update_oauth_tokens(current_user, sp.token, 'spotify'):
                    authlib_token_for_request = sp.token # Update local token
                    current_app.logger.info(f"Refreshed Spotify token saved for user {current_user.id} after playlist metadata.")
                else:
                    current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id} after playlist metadata.")
            
            tracks_url = f'playlists/{playlist_id}/tracks' # Initial URL
            page_count = 0

            while tracks_url:
                page_count += 1
                current_app.logger.info(f"Fetching page {page_count} of tracks for playlist '{playlist_name}' from URL: {tracks_url}")
                
                tracks_resp = sp.get(tracks_url, token=authlib_token_for_request)
                tracks_resp.raise_for_status()
                tracks_data = tracks_resp.json()

                if sp.token and sp.token.get('access_token') != authlib_token_for_request.get('access_token'):
                    current_app.logger.info(f"Spotify token refreshed during playlist tracks fetch (playlist ID: {playlist_id}, page: {page_count}) for user {current_user.id}.")
                    if update_oauth_tokens(current_user, sp.token, 'spotify'):
                        authlib_token_for_request = sp.token # Update local token
                        current_app.logger.info(f"Refreshed Spotify token saved for user {current_user.id} (playlist tracks page {page_count}).")
                    else:
                        current_app.logger.error(f"Failed to save refreshed Spotify token for user {current_user.id} (playlist tracks page {page_count}).")

                track_items = tracks_data.get('items', [])
                if not track_items and page_count == 1 and not tracks_data.get('next'): # Check if playlist is actually empty
                    current_app.logger.warning(f"No tracks found in playlist '{playlist_name}' (ID: {playlist_id}). It might be empty.")
                
                for item_wrapper in track_items:
                    track_info_obj = item_wrapper.get('track')
                    if not track_info_obj or not isinstance(track_info_obj, dict): # Skip if track is None (e.g., local file) or not a dict
                        current_app.logger.warning(f"Skipping item in playlist '{playlist_name}' (ID: {playlist_id}) as it's not a valid track object or is unavailable: {track_info_obj}")
                        result['errors'].append(f"Skipped an invalid/unavailable item in playlist {playlist_id}.")
                        # Not necessarily an error_count increment unless we want to be strict
                        continue

                    track_id = track_info_obj.get('id')
                    if not track_id: # Should not happen if track_info_obj is valid
                        current_app.logger.warning(f"Skipping track with no ID in playlist '{playlist_name}' (ID: {playlist_id})")
                        result['errors'].append(f"Found a track with no ID in playlist {playlist_id}.")
                        result['error_count'] +=1
                        continue
                      # Call import_spotify_track. It will handle its own token.
                    track_import_result = ImportHelper.import_spotify_track(sp, track_id)
                    
                    result['imported_count'] += track_import_result.get('imported_count', 0)
                    result['skipped_count'] += track_import_result.get('skipped_count', 0)
                    result['error_count'] += track_import_result.get('error_count', 0)
                    if track_import_result.get('errors'):
                        result['errors'].extend(track_import_result['errors'])
                    
                    # Track the song ID if it was successfully imported
                    if track_import_result.get('imported_count', 0) > 0 and track_import_result.get('song_id'):
                        result['imported_song_ids'].append(track_import_result['song_id'])
                
                tracks_url = tracks_data.get('next')
                if tracks_url:
                    current_app.logger.info(f"Next page of tracks for playlist '{playlist_name}' at: {tracks_url}")
                else:
                    current_app.logger.info(f"No more track pages for playlist '{playlist_name}' (ID: {playlist_id}).")
            db.session.commit() # Commit any changes made by track imports
        except Exception as e:
            current_app.logger.error(f"Error importing Spotify playlist {playlist_id}: {str(e)}")
            result['errors'].append(str(e))
            result['error_count'] += 1
            return result