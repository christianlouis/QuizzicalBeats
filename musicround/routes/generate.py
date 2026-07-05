import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_required
from musicround.models import Song, Round, Tag, db
from musicround.helpers.auth_helpers import oauth
from musicround.helpers.import_helper import ImportHelper
from musicround.helpers.spotify_helper import get_spotify_token

generate_bp = Blueprint('generate', __name__)

# Constants
songs_per_round = 8

# Helper functions
def get_all_decades():
    """
    Return a list of 'decade' strings (e.g. '1970', '1980')
    based on the first 3 digits of the year + '0'.
    """
    all_decades = []
    for song in Song.query.all():
        if song.year:
            decade = str(song.year)[:3] + '0'
            if decade not in all_decades:
                all_decades.append(decade)
    return all_decades

def get_all_genres():
    """
    Return a list of all genres in the Song table.
    """
    all_genres = []
    for song in Song.query.all():
        if song.genre and song.genre not in all_genres:
            all_genres.append(song.genre)
    return all_genres

def get_all_tags():
    """
    Return a list of all tag names in the Tag table.
    """
    return [tag.name for tag in Tag.query.all()]

def get_songs_by_tag(tag_name, limit=8):
    """
    Return songs that have the specified tag.
    """
    tag = Tag.query.filter_by(name=tag_name).first()
    if tag:
        return tag.songs[:limit]
    return []

def get_least_used_genres():
    """
    Returns a list of genre(s) whose usage count is minimal among all genres.
    Usage is measured by how many Rounds of type 'genre' reference that genre.
    """
    all_genres_list = get_all_genres()
    # Start every genre with usage=0
    genre_usage = {g: 0 for g in all_genres_list}

    # Count how many times each genre appears in Rounds of type 'genre'
    used_genre_rounds = Round.query.filter_by(round_type='genre').all()
    for rnd in used_genre_rounds:
        # Ensure we only increment if it exists in genre_usage
        if rnd.round_criteria_used in genre_usage:
            genre_usage[rnd.round_criteria_used] += 1

    # If we have no genres at all, return an empty list
    if not genre_usage:
        return []

    # Find the minimal usage count
    min_usage = min(genre_usage.values())

    # Return all genres that match min_usage
    return [g for g, usage in genre_usage.items() if usage == min_usage]


def get_least_used_decades():
    """
    Returns a list of decade(s) whose usage count is minimal among all decades.
    Usage is measured by how many Rounds of type 'decade' reference that decade.
    """
    all_decades_list = get_all_decades()
    # Start each decade with usage=0
    decade_usage = {d: 0 for d in all_decades_list}

    # Count how many times each decade appears in Rounds of type 'decade'
    used_decade_rounds = Round.query.filter_by(round_type='decade').all()
    for rnd in used_decade_rounds:
        if rnd.round_criteria_used in decade_usage:
            decade_usage[rnd.round_criteria_used] += 1

    # If we have no decades at all, return empty
    if not decade_usage:
        return []

    # Minimal usage
    min_usage = min(decade_usage.values())

    # Return all decades that match min_usage
    return [d for d, usage in decade_usage.items() if usage == min_usage]

def get_least_used_songs(genre=None, decade=None):
    """
    Returns songs that have never been used in a round.
    Can filter by genre or decade.
    """
    song_query = Song.query
    if genre:
        song_query = song_query.filter_by(genre=genre)
    if decade:
        try:
            decade_start = int(decade)
        except (TypeError, ValueError):
            return []
        song_query = song_query.filter(Song.year >= decade_start, Song.year < decade_start + 10)

    used_song_ids = {
        int(song_id)
        for (songs_csv,) in Round.query.with_entities(Round.songs).all()
        for song_id in songs_csv.split(',')
        if song_id
    }

    if used_song_ids:
        song_query = song_query.filter(~Song.id.in_(used_song_ids))
    return song_query.all()

def get_non_overused_songs(genre=None, decade=None):
    """
    Returns a list of songs whose used_count is <= the average usage among all songs.
    Optional filtering by genre or decade.
    """
    all_songs = Song.query.all()
    total_times_used = sum(song.used_count for song in all_songs) or 1
    average_times_used = total_times_used / len(all_songs) if len(all_songs) else 1

    # pick songs that are used <= average usage
    non_overused_songs = [s for s in all_songs if s.used_count <= average_times_used]

    if genre:
        non_overused_songs = [s for s in non_overused_songs if s.genre == genre]

    if decade:
        non_overused_songs = [s for s in non_overused_songs if s.year and str(s.year)[:3] + '0' == decade]

    return non_overused_songs

def _song_key(song):
    """Return a stable key for de-duplicating Song objects."""
    return song.id if getattr(song, 'id', None) is not None else id(song)

def _unique_songs(songs):
    """Return songs once, preserving the first occurrence."""
    unique = []
    seen = set()
    for song in songs:
        key = _song_key(song)
        if key in seen:
            continue
        unique.append(song)
        seen.add(key)
    return unique

def _song_decade(song):
    """Return the song's decade as a string, or None when year is unavailable."""
    if not song.year:
        return None
    return str(song.year)[:3] + '0'

def _sample_unique_from_preferred(preferred, fallback, x):
    """Sample unique songs, prioritizing the filtered pool before fallback songs."""
    preferred = _unique_songs(preferred)
    if len(preferred) >= x:
        return random.sample(preferred, x)

    preferred_ids = {_song_key(song) for song in preferred}
    fallback = [song for song in _unique_songs(fallback) if _song_key(song) not in preferred_ids]
    random.shuffle(preferred)
    random.shuffle(fallback)
    return (preferred + fallback)[:x]

def get_random_songs_from_genre(genre, x=5):
    """
    Returns x random songs from the given genre,
    filling from non-overused songs in that genre.
    If not enough, fallback to any non-overused songs.
    """
    return _sample_unique_from_preferred(
        get_non_overused_songs(genre=genre),
        get_non_overused_songs(),
        x,
    )

def get_random_songs_from_decade(decade, x=5):
    """
    Returns x random songs from the given decade,
    filling from non-overused songs in that decade.
    If not enough, fallback to any non-overused songs.
    """
    return _sample_unique_from_preferred(
        get_non_overused_songs(decade=decade),
        get_non_overused_songs(),
        x,
    )

def get_random_songs(x):
    """
    Returns x random songs from the pool of non-overused songs,
    applying best-effort diversity constraints:
     - prefer no artist used more than once
     - prefer no decade used more than x/3 times
     - relax artist and decade constraints when needed to return enough unique songs
    """
    candidates = _unique_songs(get_non_overused_songs())
    random.shuffle(candidates)
    if len(candidates) <= x:
        return candidates

    max_per_decade = max(1, x // 3)

    selected = []
    selected_ids = set()
    selected_artists = set()
    decade_count = {}

    for song in candidates:
        decade = _song_decade(song)
        if song.artist in selected_artists:
            continue
        if decade and decade_count.get(decade, 0) >= max_per_decade:
            continue
        selected.append(song)
        selected_ids.add(_song_key(song))
        selected_artists.add(song.artist)
        if decade:
            decade_count[decade] = decade_count.get(decade, 0) + 1
        if len(selected) == x:
            return selected

    for song in candidates:
        key = _song_key(song)
        if key in selected_ids or song.artist in selected_artists:
            continue
        selected.append(song)
        selected_ids.add(key)
        selected_artists.add(song.artist)
        if len(selected) == x:
            return selected

    for song in candidates:
        key = _song_key(song)
        if key in selected_ids:
            continue
        selected.append(song)
        selected_ids.add(key)
        if len(selected) == x:
            return selected

    return selected

def get_random_songs_from_least_used_decade(x):
    """
    Returns up to x songs from *one* of the least used decade(s), chosen at random.
    Returns (songs, chosen_decade).
    """
    candidates = get_least_used_decades()
    if not candidates:
        return [], None

    chosen_decade = random.choice(candidates)
    random_songs = get_random_songs_from_decade(chosen_decade, x=x)

    return random_songs, chosen_decade


def get_random_songs_from_least_used_genre(x):
    """
    Returns up to x songs from *one* of the least used genre(s), chosen at random.
    Returns (songs, chosen_genre).
    """
    candidates = get_least_used_genres()
    if not candidates:
        return [], None

    chosen_genre = random.choice(candidates)
    random_songs = get_random_songs_from_genre(chosen_genre, x=x)

    return random_songs, chosen_genre

def get_songs_from_deezer_playlist(playlist_id):
    """
    Fetch songs from a Deezer playlist, properly import them with metadata, and return them
    """
    try:
        if not current_app.config.get('deezer'):
            current_app.logger.error("Deezer client not configured for playlist import.")
            return []

        songs_per_round = current_app.config.get('SONGS_PER_ROUND', 10)

        import_result = ImportHelper.import_item(
            service_name='deezer',
            item_type='playlist',
            item_id=playlist_id,
        )

        if (
            not import_result
            or (
                import_result.get('error_count', 0) > 0
                and import_result.get('imported_count', 0) == 0
                and import_result.get('skipped_count', 0) == 0
            )
        ):
            current_app.logger.warning(f"No songs imported from Deezer playlist {playlist_id}: {import_result}")
            return []

        song_ids = []
        seen_song_ids = set()
        for song_id in import_result.get('song_ids', []):
            if song_id is None:
                continue
            try:
                song_id = int(song_id)
            except (TypeError, ValueError):
                continue
            if song_id in seen_song_ids:
                continue
            song_ids.append(song_id)
            seen_song_ids.add(song_id)

        if not song_ids:
            current_app.logger.warning(f"No song IDs returned after importing Deezer playlist {playlist_id}")
            return []

        songs_by_id = {
            song.id: song
            for song in Song.query.filter(Song.id.in_(song_ids)).all()
        }
        ordered_songs = [songs_by_id[song_id] for song_id in song_ids if song_id in songs_by_id]
        if not ordered_songs:
            current_app.logger.warning(f"No imported songs resolved for Deezer playlist {playlist_id}")
            return []

        return ordered_songs[:songs_per_round]
    except Exception as e:
        current_app.logger.error(f"Error fetching or importing Deezer playlist {playlist_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return []

def get_songs_from_spotify_playlist(playlist_id):
    """
    Fetch songs from a Spotify playlist, properly import them with metadata, and return them
    Always returns the songs in the playlist, even if all already exist in the DB.
    """
    try:
        songs_per_round = current_app.config.get('SONGS_PER_ROUND', 10)
        import_result = ImportHelper.import_item(
            item_id=playlist_id,
            item_type='playlist',
            service_name='spotify',
            oauth_spotify=oauth.spotify,
            spotify_token=get_spotify_token()[0],
        )

        from musicround.models import Song

        # If we have imported_song_ids, use them (these are DB IDs)
        if import_result.get('imported_song_ids'):
            song_db_ids = import_result['imported_song_ids']
            imported_songs = Song.query.filter(Song.id.in_(song_db_ids)).all()
            return imported_songs[:songs_per_round]

        # If no imported_song_ids, fetch all Spotify IDs from the playlist and get those songs from DB
        # Use the Spotify API directly to get the playlist track IDs
        sp = oauth.spotify
        # Get playlist tracks (paginated)
        all_spotify_ids = []
        next_url = f'playlists/{playlist_id}/tracks'
        access_token, token_source = get_spotify_token()
        if not access_token:
            current_app.logger.warning(f"No Spotify token available to inspect playlist {playlist_id}")
            return []
        authlib_token = {
            'access_token': access_token,
            'token_type': 'Bearer',
        }
        if token_source == 'user':
            authlib_token['refresh_token'] = current_user.spotify_refresh_token
            authlib_token['expires_at'] = (
                int(current_user.spotify_token_expiry.timestamp())
                if current_user.spotify_token_expiry else None
            )
        while next_url:
            resp = sp.get(next_url, token=authlib_token)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get('items', []):
                track = item.get('track')
                if track and track.get('id'):
                    all_spotify_ids.append(track['id'])
            next_url = data.get('next')
            # If next_url is a full URL, convert to relative for sp.get
            if next_url and next_url.startswith('https://api.spotify.com/v1/'):
                next_url = next_url.replace('https://api.spotify.com/v1/', '')
        if not all_spotify_ids:
            current_app.logger.warning(f"No valid tracks found in Spotify playlist {playlist_id}")
            return []
        # Query all songs in DB with those Spotify IDs, preserving playlist order
        songs_by_spotify_id = {s.spotify_id: s for s in Song.query.filter(Song.spotify_id.in_(all_spotify_ids)).all()}
        ordered_songs = [songs_by_spotify_id[sid] for sid in all_spotify_ids if sid in songs_by_spotify_id]
        return ordered_songs[:songs_per_round]
    except Exception as e:
        current_app.logger.error(f"Error fetching or importing Spotify playlist {playlist_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return []

@generate_bp.route('/build-music-round', methods=['GET', 'POST'])
@login_required
def build_music_round():
    """Build a music round based on the selected criteria"""
    if request.method == 'POST':
        round_type = request.form['round_type']
        if round_type == 'Random':
            round_criteria = 'Random'
            songs = get_random_songs(songs_per_round)
            return render_template('round.html', songs=songs, round_criteria=round_criteria)

        elif round_type == 'Decade':
            round_criteria = 'Least Used Decade'
            songs, decade_used = get_random_songs_from_least_used_decade(songs_per_round)
            return render_template(
                'round.html',
                songs=songs,
                round_criteria=round_criteria,
                decade=decade_used
            )

        elif round_type == 'Genre':
            round_criteria = 'Least Used Genre'
            songs, genre_used = get_random_songs_from_least_used_genre(songs_per_round)
            return render_template(
                'round.html',
                songs=songs,
                round_criteria=round_criteria,
                genre=genre_used
            )
            
        elif round_type == 'Tag':
            tag_name = request.form.get('tag_name')
            if tag_name:
                round_criteria = f'Tag: {tag_name}'
                songs = get_songs_by_tag(tag_name, songs_per_round)
                return render_template(
                    'round.html',
                    songs=songs,
                    round_criteria=round_criteria,
                    tag=tag_name
                )

    # Pass tag choices to the template for selection
    tags = get_all_tags()
    return render_template('build_music_round.html', tags=tags)

@generate_bp.route('/import-playlist', methods=['GET', 'POST'])
@login_required
def import_playlist():
    """Import a playlist from Deezer or Spotify"""
    if request.method == 'POST':
        playlist_url = request.form.get('playlist_url', '')
        platform = request.form.get('platform', '').lower()
        round_name = request.form.get('round_name', '')
        expected_song_count = current_app.config.get('SONGS_PER_ROUND', songs_per_round)
        
        if not playlist_url:
            flash('Please enter a playlist URL or ID', 'error')
            return redirect(url_for('generate.import_playlist'))
        
        # Extract playlist ID from URL or use as is
        playlist_id = playlist_url
        
        if platform == 'deezer':
            # Extract Deezer playlist ID from URL if needed
            if 'deezer.com' in playlist_url:
                try:
                    playlist_id = playlist_url.split('playlist/')[1].split('?')[0]
                except (IndexError, ValueError):
                    flash('Invalid Deezer playlist URL', 'error')
                    return redirect(url_for('generate.import_playlist'))
            
            songs = get_songs_from_deezer_playlist(playlist_id)
            if not songs:
                flash('No songs found or error fetching playlist from Deezer', 'error')
                return redirect(url_for('generate.import_playlist'))
            if len(songs) != expected_song_count:
                flash(
                    f'Deezer playlist resolved {len(songs)} songs; expected exactly {expected_song_count}. '
                    'Replace unavailable tracks before saving the round.',
                    'error',
                )
                return redirect(url_for('generate.import_playlist'))
                
            round_criteria = f'Deezer Playlist: {playlist_id}'
            
        elif platform == 'spotify':
            # Extract Spotify playlist ID from URL if needed
            if 'spotify.com' in playlist_url:
                try:
                    playlist_id = playlist_url.split('playlist/')[1].split('?')[0]
                except (IndexError, ValueError):
                    flash('Invalid Spotify playlist URL', 'error')
                    return redirect(url_for('generate.import_playlist'))
            
            songs = get_songs_from_spotify_playlist(playlist_id)
            if not songs:
                flash('No songs found or error fetching playlist from Spotify', 'error')
                return redirect(url_for('generate.import_playlist'))
            if len(songs) != expected_song_count:
                flash(
                    f'Spotify playlist resolved {len(songs)} songs; expected exactly {expected_song_count}. '
                    'Replace unavailable tracks before saving the round.',
                    'error',
                )
                return redirect(url_for('generate.import_playlist'))
                
            round_criteria = f'Spotify Playlist: {playlist_id}'
            
        else:
            flash('Please select a valid platform', 'error')
            return redirect(url_for('generate.import_playlist'))
            
        return render_template('round.html', 
                               songs=songs, 
                               round_criteria=round_criteria, 
                               round_name=round_name,
                               playlist_import=True,
                               expected_song_count=expected_song_count)
    
    return render_template('import_playlist.html')

@generate_bp.route('/save_round', methods=['POST'])
@login_required
def save_round():
    """
    Persists a new Round to the DB (with chosen songs).
    Increments used_count on all chosen songs.
    """
    # get round criteria and name from form
    round_criteria = request.form.get('round_criteria')
    round_name = request.form.get('round_name')
    
    # get optional genre and decade from form
    genre = request.form.get('genre')
    decade = request.form.get('decade')
    tag = request.form.get('tag')
    
    # get list of song IDs from form
    raw_song_ids = [song_id.strip() for song_id in request.form.getlist('song_id') if song_id.strip()]
    if not raw_song_ids:
        flash('Please select at least one song before saving a round.', 'error')
        return redirect(url_for('generate.build_music_round'))

    playlist_import = request.form.get('playlist_import') == '1' or (
        round_criteria or ''
    ).lower().startswith(('spotify playlist:', 'deezer playlist:'))
    if playlist_import:
        try:
            expected_song_count = int(
                request.form.get('expected_song_count')
                or current_app.config.get('SONGS_PER_ROUND', songs_per_round)
            )
        except (TypeError, ValueError):
            expected_song_count = songs_per_round
        if len(raw_song_ids) != expected_song_count:
            flash(
                f'Playlist round resolved {len(raw_song_ids)} songs; expected exactly {expected_song_count}. '
                'Replace unavailable tracks before saving the round.',
                'error',
            )
            return redirect(url_for('generate.import_playlist'))

    try:
        song_ids = [int(song_id) for song_id in raw_song_ids]
    except ValueError:
        flash('Invalid song selection. Please build the round again.', 'error')
        return redirect(url_for('generate.build_music_round'))

    # get list of song objects from database while preserving the submitted order
    songs_by_id = {
        song.id: song
        for song in Song.query.filter(Song.id.in_(song_ids)).all()
    }
    songs = [songs_by_id[song_id] for song_id in song_ids if song_id in songs_by_id]
    if len(songs) != len(song_ids):
        flash('One or more selected songs could not be found. Please build the round again.', 'error')
        return redirect(url_for('generate.build_music_round'))

    # create string representation of song IDs
    song_ids_str = ','.join(str(song_id) for song_id in song_ids)

    # determine round type
    if genre:
        round_type = 'Genre'
        round_criteria_used = genre
    elif decade:
        round_type = 'Decade'
        round_criteria_used = decade
    elif tag:
        round_type = 'Tag'
        round_criteria_used = tag
    else:
        round_type = 'Random'
        round_criteria_used = 'Random Selection'

    # create new Round object and add to database
    new_round = Round(
        name=round_name,
        round_type=round_type,
        round_criteria_used=round_criteria_used,
        songs=song_ids_str,
        created_at=datetime.utcnow()
    )
    db.session.add(new_round)

    # update usage count for each song
    for song in songs:
        song.used_count += 1
        db.session.add(song)

    db.session.commit()

    # redirect back to the rounds page
    return redirect(url_for('rounds.rounds_list'))
