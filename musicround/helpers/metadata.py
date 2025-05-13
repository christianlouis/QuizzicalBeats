import requests
import json
import statistics
import musicbrainzngs
import openai
from flask import current_app
from collections import Counter
import traceback  # Added for detailed error tracking

def get_song_metadata_by_isrc(isrc, app=None):
    """
    Get comprehensive song metadata by ISRC code from multiple sources.
    
    Args:
        isrc (str): The ISRC code to look up
        app: Flask application context (optional)
        
    Returns:
        dict: Standardized metadata with the following keys:
            - artist_name: Artist name(s)
            - title: Title of the song
            - year: Year the song was first released
            - genre: Primary genre
            - genres: All genres as an array
            - popularity: Popularity rating (0-100)
            - preview_url: Main preview URL (prioritized from sources)
            - sources: List of sources that provided data
            - spotify_id: Spotify track ID if available
            - deezer_id: Deezer track ID if available
            - And more provider-specific data
    """
    # Initialize result dictionary
    metadata = {
        "artist_name": None,
        "title": None,
        "year": None,
        "genre": None,
        "genres": [],  # New array to store all genres
        "popularity": None,
        "preview_url": None,
        "sources": [],
        "isrc": isrc,
        "spotify_id": None,
        "deezer_id": None,
        # Cover URLs from different sources
        "cover_url": None,
        "spotify_cover_url": None,
        "deezer_cover_url": None,
        "apple_cover_url": None,
        # Preview URLs from different sources
        "spotify_preview_url": None,
        "deezer_preview_url": None,
        "apple_preview_url": None,
        "youtube_preview_url": None
    }
    
    # Store results from different sources to compare
    artist_names = []
    titles = []
    years = []
    genres = []  # This will collect all genres for final processing
    preview_urls = []
    
    # Initialize logger if app context provided
    logger = app.logger if app else None
    if logger:
        logger.info(f"=== DEBUG: Starting metadata refresh for ISRC: {isrc} ===")

    try:
        # 0. Query ACRCloud first (provides info from multiple platforms)
        if logger:
            logger.info(f"DEBUG: Querying ACRCloud for ISRC: {isrc}")
        acrcloud_data = get_acrcloud_data(isrc, app)
        if acrcloud_data:
            metadata["sources"].append("acrcloud")
            if logger:
                logger.info(f"DEBUG: ACRCloud data received: {json.dumps(acrcloud_data, default=str)}")
                
            if acrcloud_data.get("artist_name"):
                artist_names.append(acrcloud_data["artist_name"])
            if acrcloud_data.get("title"):
                titles.append(acrcloud_data["title"])
            if acrcloud_data.get("year"):
                years.append(acrcloud_data["year"])
            if acrcloud_data.get("genre"):
                # Debug the genre value
                if logger:
                    logger.info(f"DEBUG: ACRCloud genre type: {type(acrcloud_data['genre']).__name__}")
                    logger.info(f"DEBUG: ACRCloud genre value: {acrcloud_data['genre']}")
                
                # Handle genre properly whether it's a string, list, or dict
                if isinstance(acrcloud_data["genre"], list):
                    if logger:
                        logger.info(f"DEBUG: Processing genre as list: {acrcloud_data['genre']}")
                    genres.extend(acrcloud_data["genre"])  # ACRCloud might return multiple genres
                elif isinstance(acrcloud_data["genre"], str):
                    if logger:
                        logger.info(f"DEBUG: Processing genre as string: {acrcloud_data['genre']}")
                    genres.append(acrcloud_data["genre"])
                elif isinstance(acrcloud_data["genre"], dict):
                    # Debug the dict structure
                    if logger:
                        logger.info(f"DEBUG: Processing genre as dict: {acrcloud_data['genre']}")
                    
                    # Extract genre name from dict if available
                    for genre_key, genre_value in acrcloud_data["genre"].items():
                        if logger:
                            logger.info(f"DEBUG: Genre key: {genre_key}, value type: {type(genre_value).__name__}")
                        
                        if isinstance(genre_value, str):
                            if logger:
                                logger.info(f"DEBUG: Adding genre string: {genre_value}")
                            genres.append(genre_value)
                        elif isinstance(genre_value, list) and genre_value:
                            if logger:
                                logger.info(f"DEBUG: Adding genres from list: {genre_value}")
                            genres.extend([g for g in genre_value if isinstance(g, str)])
                        else:
                            if logger:
                                logger.info(f"DEBUG: Skipping genre value of type: {type(genre_value).__name__}")
                else:
                    if logger:
                        logger.info(f"DEBUG: Unknown genre type: {type(acrcloud_data['genre']).__name__}")
                
            # Store platform IDs
            if acrcloud_data.get("spotify_id"):
                metadata["spotify_id"] = acrcloud_data["spotify_id"]
            if acrcloud_data.get("deezer_id"):
                metadata["deezer_id"] = acrcloud_data["deezer_id"]
                
            # Store preview URLs from different sources
            if acrcloud_data.get("spotify_preview_url"):
                metadata["spotify_preview_url"] = acrcloud_data["spotify_preview_url"]
            if acrcloud_data.get("deezer_preview_url"):
                metadata["deezer_preview_url"] = acrcloud_data["deezer_preview_url"]
            if acrcloud_data.get("apple_preview_url"):
                metadata["apple_preview_url"] = acrcloud_data["apple_preview_url"]
            if acrcloud_data.get("youtube_preview_url"):
                metadata["youtube_preview_url"] = acrcloud_data["youtube_preview_url"]
                
            # Store cover URLs from different sources
            if acrcloud_data.get("spotify_cover_url"):
                metadata["spotify_cover_url"] = acrcloud_data["spotify_cover_url"]
            if acrcloud_data.get("deezer_cover_url"):
                metadata["deezer_cover_url"] = acrcloud_data["deezer_cover_url"]
            if acrcloud_data.get("apple_cover_url"):
                metadata["apple_cover_url"] = acrcloud_data["apple_cover_url"]
            
            # Store album cover as main cover if available
            if acrcloud_data.get("album_cover"):
                metadata["cover_url"] = acrcloud_data["album_cover"]
    except Exception as e:
        if logger:
            logger.error(f"ACRCloud error for ISRC {isrc}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    try:
        # 1. Query MusicBrainz (direct ISRC support)
        mb_data = get_musicbrainz_data(isrc, logger)
        if mb_data:
            metadata["sources"].append("musicbrainz")
            if mb_data.get("artist_name"):
                artist_names.append(mb_data["artist_name"])
            if mb_data.get("title"):
                titles.append(mb_data["title"])
            if mb_data.get("year"):
                years.append(mb_data["year"])
            if mb_data.get("genre"):
                genres.append(mb_data["genre"])
    except Exception as e:
        if logger:
            logger.error(f"MusicBrainz error for ISRC {isrc}: {e}")
    
    try:
        # 2. Query Spotify (direct ISRC support)
        spotify_data = get_spotify_data(isrc, app)
        if spotify_data:
            metadata["sources"].append("spotify")
            if spotify_data.get("artist_name"):
                artist_names.append(spotify_data["artist_name"])
            if spotify_data.get("title"):
                titles.append(spotify_data["title"])
            if spotify_data.get("year"):
                years.append(spotify_data["year"])
            if spotify_data.get("genre"):
                genres.append(spotify_data["genre"])
            if spotify_data.get("popularity") is not None:
                metadata["popularity"] = spotify_data["popularity"]
            if spotify_data.get("spotify_preview_url"):
                metadata["spotify_preview_url"] = spotify_data["spotify_preview_url"]
            if spotify_data.get("id"):
                metadata["spotify_id"] = spotify_data["id"]
            if spotify_data.get("spotify_cover_url"):
                metadata["spotify_cover_url"] = spotify_data["spotify_cover_url"]
    except Exception as e:
        if logger:
            logger.error(f"Spotify error for ISRC {isrc}: {e}")
    
    try:
        # 3. Query Deezer (direct ISRC support in newer API)
        deezer_data = get_deezer_data(isrc, app)
        if deezer_data:
            metadata["sources"].append("deezer")
            if deezer_data.get("artist_name"):
                artist_names.append(deezer_data["artist_name"])
            if deezer_data.get("title"):
                titles.append(deezer_data["title"])
            if deezer_data.get("year"):
                years.append(deezer_data["year"])
            if deezer_data.get("genre"):
                genres.append(deezer_data["genre"])
            if deezer_data.get("deezer_preview_url"):
                metadata["deezer_preview_url"] = deezer_data["deezer_preview_url"]
            if deezer_data.get("id"):
                metadata["deezer_id"] = deezer_data["id"]
            if deezer_data.get("deezer_cover_url"):
                metadata["deezer_cover_url"] = deezer_data["deezer_cover_url"]
    except Exception as e:
        if logger:
            logger.error(f"Deezer error for ISRC {isrc}: {e}")
    
    # Debug the collected data before processing
    if logger:
        logger.info(f"DEBUG: All collected artist names: {artist_names}")
        logger.info(f"DEBUG: All collected titles: {titles}")
        logger.info(f"DEBUG: All collected years: {years}")
        logger.info(f"DEBUG: All collected genres: {genres}")

    # Determine most common values so far
    if artist_names and titles:
        try:
            # Use the most frequent values from collected data
            if logger:
                logger.info(f"DEBUG: Computing most common artist from: {artist_names}")
            metadata["artist_name"] = Counter(artist_names).most_common(1)[0][0]
            
            if logger:
                logger.info(f"DEBUG: Computing most common title from: {titles}")
            metadata["title"] = Counter(titles).most_common(1)[0][0]
            
            # With artist and title, we can query services that don't support ISRC
            try:
                # 4. Query Last.fm
                lastfm_data = get_lastfm_data(metadata["artist_name"], metadata["title"], app)
                if lastfm_data:
                    metadata["sources"].append("lastfm")
                    if lastfm_data.get("genre"):
                        genres.append(lastfm_data["genre"])
            except Exception as e:
                if logger:
                    logger.error(f"Last.fm error for {metadata['artist_name']} - {metadata['title']}: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
            
            try:
                # 5. Query OpenAI for additional verification
                openai_data = get_openai_data(metadata["artist_name"], metadata["title"], app)
                if openai_data:
                    metadata["sources"].append("openai")
                    if openai_data.get("year"):
                        years.append(openai_data["year"])
                    if openai_data.get("genre"):
                        genres.append(openai_data["genre"])
            except Exception as e:
                if logger:
                    logger.error(f"OpenAI error for {metadata['artist_name']} - {metadata['title']}: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
        except Exception as e:
            if logger:
                logger.error(f"Error determining most common values: {e}")
                logger.error(f"Artist names: {artist_names}")
                logger.error(f"Titles: {titles}")
                logger.error(f"Traceback: {traceback.format_exc()}")
    
    # Process collected data
    if years:
        try:
            # For year, take the earliest one as "first released"
            if logger:
                logger.info(f"DEBUG: Processing years: {years}")
            
            numeric_years = [int(y) for y in years if y and y.isdigit()]
            if numeric_years:
                metadata["year"] = str(min(numeric_years))
                if logger:
                    logger.info(f"DEBUG: Selected earliest year: {metadata['year']}")
        except Exception as e:
            # Fallback to most common if conversion fails
            if logger:
                logger.error(f"Year processing error: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
            
            try:
                metadata["year"] = Counter(years).most_common(1)[0][0]
                if logger:
                    logger.info(f"DEBUG: Fallback to most common year: {metadata['year']}")
            except Exception as e2:
                if logger:
                    logger.error(f"Year fallback error: {e2}")
    
    # Process all genres and create a clean list for tagging
    if genres:
        try:
            # First, clean up genres for storage
            clean_genres = []
            for g in genres:
                if isinstance(g, str) and g.strip():
                    # Translate specific genre names to English
                    if g.strip().lower() == "vaihtoehtoinen":
                        clean_genres.append("Alternative")
                        if logger:
                            logger.info(f"DEBUG: Translated genre 'Vaihtoehtoinen' to 'Alternative'")
                    else:
                        clean_genres.append(g.strip())
                elif isinstance(g, list):
                    # Flatten any nested lists and translate if needed
                    for item in g:
                        if isinstance(item, str) and item.strip():
                            if item.strip().lower() == "vaihtoehtoinen":
                                clean_genres.append("Alternative")
                                if logger:
                                    logger.info(f"DEBUG: Translated genre 'Vaihtoehtoinen' to 'Alternative'")
                            else:
                                clean_genres.append(item.strip())
            
            # Store all unique genres in the metadata
            unique_genres = []
            for g in clean_genres:
                if g.lower() not in [existing.lower() for existing in unique_genres]:
                    unique_genres.append(g)
            
            metadata["genres"] = unique_genres
            
            if logger:
                logger.info(f"DEBUG: All cleaned genres: {unique_genres}")
                
            # For the main genre field, take the most common one
            if clean_genres:
                # Get a case-insensitive count by converting all to lowercase
                lowercase_genres = [g.lower() for g in clean_genres]
                genre_counter = Counter(lowercase_genres)
                most_common_genre_lower = genre_counter.most_common(1)[0][0]
                
                # Find the original case version from our clean genres
                for g in clean_genres:
                    if g.lower() == most_common_genre_lower:
                        metadata["genre"] = g
                        break
                
                if logger:
                    logger.info(f"DEBUG: Selected most common genre as main: {metadata['genre']}")
        except Exception as e:
            if logger:
                logger.error(f"Genre processing error: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
    
    # Process preview URLs with priority for Spotify, then Apple Music, then Deezer
    preview_sources = [
        metadata.get("spotify_preview_url"),
        metadata.get("apple_preview_url"),
        metadata.get("deezer_preview_url"),
        metadata.get("youtube_preview_url")
    ]
    
    # Select the first available preview URL as the main one
    for url in preview_sources:
        if url:
            metadata["preview_url"] = url
            if logger:
                logger.info(f"DEBUG: Selected preview URL: {url}")
            break
    
    # Process cover URLs with priority
    cover_sources = [
        metadata.get("spotify_cover_url"),
        metadata.get("apple_cover_url"),
        metadata.get("deezer_cover_url")
    ]
    
    # Select the first available cover URL as the main one if not already set
    if not metadata["cover_url"]:
        for url in cover_sources:
            if url:
                metadata["cover_url"] = url
                if logger:
                    logger.info(f"DEBUG: Selected cover URL: {url}")
                break
    
    if logger:
        logger.info(f"=== DEBUG: Completed metadata refresh for ISRC: {isrc} ===")
        logger.info(f"=== Final metadata: {json.dumps(metadata, default=str)} ===")
    
    return metadata

def get_musicbrainz_data(isrc, logger=None):
    """Query MusicBrainz API using ISRC"""
    result = {}
    
    # Set user agent for MusicBrainz API
    musicbrainzngs.set_useragent("MusicRound", "0.1", "fret@fret.de")
    
    try:
        # Search MusicBrainz by ISRC
        mb_results = musicbrainzngs.search_recordings(isrc=isrc, limit=1)
        if mb_results and mb_results.get('recording-list') and len(mb_results['recording-list']) > 0:
            recording = mb_results['recording-list'][0]
            
            # Extract title
            result["title"] = recording.get('title')
            
            # Extract artist name
            if recording.get('artist-credit'):
                artist_names = []
                for artist_credit in recording['artist-credit']:
                    if isinstance(artist_credit, dict) and 'artist' in artist_credit:
                        artist_names.append(artist_credit['artist']['name'])
                if artist_names:
                    result["artist_name"] = ", ".join(artist_names)
            
            # Extract genre tags
            if 'tag-list' in recording:
                tags = [tag['name'] for tag in recording['tag-list']]
                if tags:
                    result["genre"] = tags[0]
            
            # Get release year
            if 'release-list' in recording and recording['release-list']:
                release = recording['release-list'][0]
                if 'date' in release:
                    result["year"] = release['date'][:4]  # Extract year from date
    except Exception as e:
        if logger:
            logger.error(f"MusicBrainz API error: {e}")
    
    return result

def get_spotify_data(isrc, app=None):
    """Query Spotify API using ISRC"""
    result = {}
    
    try:
        # Get Spotify client from app context
        sp = app.config.get('sp') if app else None
        if not sp:
            return result
        
        # Search Spotify by ISRC
        query = f"isrc:{isrc}"
        spotify_result = sp.search(q=query, type='track')
        
        if spotify_result and spotify_result.get('tracks') and spotify_result['tracks'].get('items'):
            track = spotify_result['tracks']['items'][0]
            
            # Extract track title
            result["title"] = track.get('name')
            
            # Extract artist names
            if track.get('artists'):
                result["artist_name"] = ", ".join([artist['name'] for artist in track['artists']])
            
            # Extract popularity
            result["popularity"] = track.get('popularity')
            
            # Extract preview URL
            result["spotify_preview_url"] = track.get('preview_url')
            
            # Store main track ID
            result["id"] = track.get('id')
            
            # Get album details to extract more info
            if track.get('album') and track['album'].get('id'):
                album = sp.album(track['album']['id'])
                
                # Extract genre
                if album.get('genres') and len(album['genres']) > 0:
                    result["genre"] = album['genres'][0]
                
                # Extract release year
                if album.get('release_date'):
                    result["year"] = album['release_date'][:4]
                    
                # Extract cover images
                if track['album'].get('images') and len(track['album']['images']) > 0:
                    for img in track['album']['images']:
                        if img.get('height') and img.get('width') and img.get('url'):
                            if img['height'] > 600:  # Consider this a large image
                                result["spotify_cover_url"] = img['url']
                                break
                    # If we didn't find a large image, use the first one
                    if not result.get("spotify_cover_url") and track['album']['images'][0].get('url'):
                        result["spotify_cover_url"] = track['album']['images'][0]['url']
    except Exception as e:
        if app:
            app.logger.error(f"Spotify API error: {e}")
    
    return result

def get_deezer_data(isrc, app=None):
    """Query Deezer API using ISRC"""
    result = {}
    
    try:
        # Get Deezer client from app context or create a basic one
        deezer_client = app.config.get('deezer') if app else None
        
        if not deezer_client:
            # If no client in app context, make direct API call
            response = requests.get(f"https://api.deezer.com/track/isrc:{isrc}")
            if response.status_code == 200:
                track = response.json()
            else:
                return result
        else:
            # Try to use the ISRC search if available, or search by track if not
            try:
                track = deezer_client._make_request(f"track/isrc:{isrc}")
            except:
                # Deezer client might not have direct ISRC support, so try a workaround
                # (This would require having title and artist from another source)
                track = None
        
        if track and not track.get('error'):
            # Extract title
            result["title"] = track.get('title')
            
            # Extract artist name
            if track.get('artist'):
                result["artist_name"] = track['artist'].get('name')
            
            # Extract preview URL
            result["deezer_preview_url"] = track.get('preview')
            
            # Extract Deezer ID
            result["id"] = track.get('id')
            
            # Get album details to extract more info
            if track.get('album') and track['album'].get('id'):
                album_id = track['album']['id']
                
                if deezer_client:
                    album = deezer_client.get_album(album_id)
                else:
                    album_response = requests.get(f"https://api.deezer.com/album/{album_id}")
                    album = album_response.json() if album_response.status_code == 200 else None
                
                if album and not album.get('error'):
                    # Extract genre
                    if album.get('genres') and album['genres'].get('data') and len(album['genres']['data']) > 0:
                        result["genre"] = album['genres']['data'][0].get('name')
                    
                    # Extract release year
                    if album.get('release_date'):
                        result["year"] = album['release_date'][:4]
                    
                    # Extract cover image
                    if track['album'].get('cover'):
                        result["deezer_cover_url"] = track['album']['cover']
                    # Try the bigger version
                    if track['album'].get('cover_xl'):
                        result["deezer_cover_url"] = track['album']['cover_xl']
                    elif track['album'].get('cover_big'):
                        result["deezer_cover_url"] = track['album']['cover_big']
    except Exception as e:
        if app:
            app.logger.error(f"Deezer API error: {e}")
    
    return result

def get_lastfm_data(artist_name, track_title, app=None):
    """Query Last.fm API using artist name and track title"""
    result = {}
    
    if not artist_name or not track_title:
        return result
    
    try:
        # Get Last.fm API key from app context or environment
        lastfm_api_key = None
        if app:
            lastfm_api_key = app.config.get('LASTFM_API_KEY')
        
        if not lastfm_api_key:
            return result
        
        # Query Last.fm API
        url = 'http://ws.audioscrobbler.com/2.0/'
        params = {
            'method': 'track.getInfo',
            'api_key': lastfm_api_key,
            'artist': artist_name,
            'track': track_title,
            'format': 'json'
        }
        
        response = requests.get(url=url, params=params)
        if response.status_code == 200:
            data = response.json()
            
            # Extract genre from top tags
            if (data.get('track') and 
                data['track'].get('toptags') and 
                data['track']['toptags'].get('tag')):
                tags = data['track']['toptags']['tag']
                if tags and len(tags) > 0:
                    result["genre"] = tags[0]['name']
    except Exception as e:
        if app:
            app.logger.error(f"Last.fm API error: {e}")
    
    return result

def get_openai_data(artist_name, track_title, app=None):
    """Query OpenAI API for additional metadata verification"""
    result = {}
    
    if not artist_name or not track_title:
        return result
    
    try:
        # Get OpenAI API details from app context
        if not app:
            return result
        
        openai_api_key = app.config.get('OPENAI_API_KEY')
        openai_url = app.config.get('OPENAI_URL')
        openai_model = app.config.get('OPENAI_MODEL')
        
        if not openai_api_key or not openai_model:
            return result
        
        # Configure OpenAI API key
        openai.api_key = openai_api_key
        
        # Create prompt
        prompt = f"Provide the genre and release year for the song '{track_title}' by {artist_name}. Return the data as a JSON object with keys 'genre' and 'year'. If the information is not available, return null for the corresponding key."
        
        # Log the query
        app.logger.info(f"ChatGPT Query: {prompt}")
        
        content = None
        
        # Check which version of the OpenAI library is being used
        if hasattr(openai, 'chat') and hasattr(openai.chat, 'completions'):
            # New OpenAI API client (>= 1.0.0)
            if openai_url:
                openai.base_url = openai_url

            # Call OpenAI API with new client
            try:
                response = openai.chat.completions.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                
                if response and hasattr(response, 'choices') and response.choices:
                    content = response.choices[0].message.content
                    app.logger.info(f"ChatGPT Response: {content}")
            except Exception as e:
                app.logger.error(f"OpenAI chat completions error: {e}")
                # Try falling back to completion API if available
                try:
                    if hasattr(openai, 'Completion'):
                        response = openai.Completion.create(
                            engine=openai_model, 
                            prompt=prompt,
                            max_tokens=200,
                            temperature=0.2,
                            top_p=1.0
                        )
                        if response and hasattr(response, 'choices') and len(response.choices) > 0:
                            content = response.choices[0].text.strip()
                            app.logger.info(f"OpenAI Completion Response: {content}")
                except Exception as inner_e:
                    app.logger.error(f"OpenAI completion fallback error: {inner_e}")
        else:
            # Old OpenAI API client (< 1.0.0)
            if openai_url:
                openai.api_base = openai_url  # Different attribute in old client
            
            # Call OpenAI API with old client
            try:
                response = openai.Completion.create(
                    engine=openai_model,  # In old API, it's 'engine' instead of 'model'
                    prompt=prompt,
                    max_tokens=200,
                    temperature=0.2,
                    top_p=1.0
                )
                
                if response and hasattr(response, 'choices') and len(response.choices) > 0:
                    content = response.choices[0].text.strip()
                    app.logger.info(f"ChatGPT Response: {content}")
            except Exception as e:
                app.logger.error(f"OpenAI completion error: {e}")
        
        # Process the response content
        if content:
            try:
                # Try to extract JSON from the content (handle cases where there might be extra text)
                import re
                json_match = re.search(r'(\{.*\})', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    data = json.loads(json_str)
                else:
                    data = json.loads(content)
                
                if data.get("genre"):
                    result["genre"] = data["genre"]
                if data.get("year"):
                    # Always convert year to string
                    result["year"] = str(data["year"])
                
                # If we got valid data, return it
                if "genre" in result or "year" in result:
                    return result
                
            except Exception as e:
                app.logger.error(f"Error parsing OpenAI response: {e}")
                app.logger.error(f"Raw response content: {content}")
    except AttributeError as e:
        app.logger.error(f"OpenAI module error: {e}")
    except Exception as e:
        if app:
            app.logger.error(f"OpenAI API error: {e}")
    
    return result

def get_acrcloud_data(isrc, app=None):
    """Query ACRCloud API using ISRC"""
    result = {}
    
    if not app:
        return result
    
    try:
        # Get ACRCloud API key from app config
        acrcloud_token = app.config.get('ACRCLOUD_TOKEN')
        if not acrcloud_token:
            logger = app.logger if app else None
            if logger:
                logger.warning("ACRCloud token not found in app config.")
            return result
        
        # Query ACRCloud API for track metadata
        url = "https://eu-api-v2.acrcloud.com/api/external-metadata/tracks"
        headers = {
            'Authorization': f'Bearer {acrcloud_token}'
        }
        params = {
            'isrc': isrc,
            'platforms': 'spotify,deezer,youtube,applemusic',
            'include_works': 1  # Include additional work metadata
        }
        
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            app.logger.warning(f"ACRCloud API error: {response.status_code} - {response.text}")
            return result
        
        data = response.json()
        if not data or not data.get('data') or not len(data['data']) > 0:
            return result
        
        track_data = data['data'][0]
        logger = app.logger if app else None
        if logger:
            logger.info(f"ACRCloud API response: {json.dumps(data, default=str)}")
        # Extract basic metadata
        if track_data.get('name'):
            result['title'] = track_data['name']
        
        if track_data.get('artists') and len(track_data['artists']) > 0:
            artist_names = [artist['name'] for artist in track_data['artists'] if 'name' in artist]
            result['artist_name'] = ', '.join(artist_names)
        
        if track_data.get('release_date'):
            result['year'] = track_data['release_date'][:4]  # Extract year
        
        if track_data.get('genres'):
            result['genre'] = track_data['genres']
        
        # Extract album cover if available
        if track_data.get('album') and track_data['album'].get('cover'):
            result['album_cover'] = track_data['album']['cover']
            
            # Also get covers from specific sizes if available
            if track_data['album'].get('covers'):
                covers = track_data['album']['covers']
                if covers.get('large'):
                    result['album_cover_large'] = covers['large']
                if covers.get('medium'):
                    result['album_cover_medium'] = covers['medium']
        
        # Get external metadata from platforms
        ext_meta = track_data.get('external_metadata', {})
        
        # Get Spotify metadata
        if 'spotify' in ext_meta and ext_meta['spotify'] and len(ext_meta['spotify']) > 0:
            spotify_data = ext_meta['spotify'][0]
            if spotify_data.get('id'):
                result['spotify_id'] = spotify_data['id']
            if spotify_data.get('preview'):
                result['spotify_preview_url'] = spotify_data['preview']
            if spotify_data.get('album') and spotify_data['album'].get('cover'):
                result['spotify_cover_url'] = spotify_data['album']['cover']
        
        # Get Deezer metadata
        if 'deezer' in ext_meta and ext_meta['deezer'] and len(ext_meta['deezer']) > 0:
            deezer_data = ext_meta['deezer'][0]
            if deezer_data.get('id'):
                result['deezer_id'] = deezer_data['id']
            # Deezer preview URL might come from additional API call
            if deezer_data.get('album') and deezer_data['album'].get('cover'):
                result['deezer_cover_url'] = deezer_data['album']['cover']

        # Get Apple Music metadata
        if 'applemusic' in ext_meta and ext_meta['applemusic'] and len(ext_meta['applemusic']) > 0:
            apple_data = ext_meta['applemusic'][0]
            if apple_data.get('preview'):
                result['apple_preview_url'] = apple_data['preview']
            if apple_data.get('album') and apple_data['album'].get('cover'):
                result['apple_cover_url'] = apple_data['album']['cover']
                
        # Get YouTube metadata
        if 'youtube' in ext_meta and ext_meta['youtube'] and len(ext_meta['youtube']) > 0:
            youtube_data = ext_meta['youtube'][0]
            if youtube_data.get('id'):
                youtube_id = youtube_data['id']
                result['youtube_id'] = youtube_id
                # Construct a YouTube Music playback URL
                result['youtube_preview_url'] = f"https://music.youtube.com/watch?v={youtube_id}"
        
        return result
    except Exception as e:
        if app:
            app.logger.error(f"ACRCloud API error: {e}")
    
    return result
