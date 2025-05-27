import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_required
from musicround.models import Song, Round, Tag, db
from musicround.helpers.auth_helpers import oauth
from musicround.helpers.import_helper import ImportHelper

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
    least_used_songs = []
    all_songs = Song.query.all()

    # gather round_criteria_used for rounds of type 'song'
    used_song_ids = []
    for rnd in Round.query.all():
        if rnd.round_type == 'song':
            used_song_ids.append(rnd.round_criteria_used)

    # If a song's spotify_id never appears in used_song_ids => "least used"
    for song in all_songs:
        if song.spotify_id not in used_song_ids:
            least_used_songs.append(song)

    # Filter by genre or decade if passed
    if genre:
        least_used_songs = [s for s in least_used_songs if s.genre == genre]
    if decade:
        least_used_songs = [s for s in least_used_songs if s.year and str(s.year)[:3] + '0' == decade]
    return least_used_songs

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

def get_random_songs_from_genre(genre, x=5):
    """
    Returns x random songs from the given genre,
    filling from non-overused songs in that genre.
    If not enough, fallback to any non-overused songs.
    """
    non_overused = get_non_overused_songs(genre=genre)
    while len(non_overused) < x:
        more = get_non_overused_songs()
        if not more:  # in case the DB is empty or something else
            break
        non_overused.extend(more)

    return random.sample(non_overused, x) if len(non_overused) >= x else non_overused

def get_random_songs_from_decade(decade, x=5):
    """
    Returns x random songs from the given decade,
    filling from non-overused songs in that decade.
    If not enough, fallback to any non-overused songs.
    """
    non_overused = get_non_overused_songs(decade=decade)
    while len(non_overused) < x:
        more = get_non_overused_songs()
        if not more:
            break
        non_overused.extend(more)

    return random.sample(non_overused, x) if len(non_overused) >= x else non_overused

def get_random_songs(x):
    """
    Returns x random songs from the pool of non-overused songs,
    ensuring some naive diversity constraints:
     - no artist used more than once
     - no decade used more than x/3 times
     - number of unique artists must match number of chosen songs
    """
    non_overused_songs = get_non_overused_songs()
    if len(non_overused_songs) < x:
        return non_overused_songs
        
    random_songs = random.sample(non_overused_songs, x)

    artist_count = {}
    decade_count = {}

    for song in random_songs:
        artist_count[song.artist] = artist_count.get(song.artist, 0) + 1
        if song.year:
            dec = str(song.year)[:3] + '0'
            decade_count[dec] = decade_count.get(dec, 0) + 1

    while (
        max(artist_count.values()) > 1
        or (decade_count and max(decade_count.values()) > len(random_songs) / 3)
        or len(artist_count) != len(random_songs)
    ):
        # 1. If any artist is used more than once, replace that song
        if max(artist_count.values()) > 1:
            repeated_artist = None
            for artist, count in artist_count.items():
                if count > 1:
                    repeated_artist = artist
                    break
            if repeated_artist:
                # remove one of that artist from random_songs
                to_remove = next(s for s in random_songs if s.artist == repeated_artist)
                random_songs.remove(to_remove)
                artist_count[repeated_artist] -= 1

                # pick a new random non-overused
                refill = [s for s in non_overused_songs if s not in random_songs]
                if refill:
                    new_song = random.choice(refill)
                    random_songs.append(new_song)
                    artist_count[new_song.artist] = artist_count.get(new_song.artist, 0) + 1

                    # update decade_count
                    if to_remove.year:
                        dec_to_remove = str(to_remove.year)[:3] + '0'
                        decade_count[dec_to_remove] = decade_count.get(dec_to_remove, 0) - 1
                    if new_song.year:
                        dec_new = str(new_song.year)[:3] + '0'
                        decade_count[dec_new] = decade_count.get(dec_new, 0) + 1
                else:
                    # If no new songs available, just return what we have
                    return random_songs

        elif decade_count and max(decade_count.values()) > len(random_songs) / 3:
            # 2. If any decade is used more than x/3, remove a song from that decade
            repeated_decade = None
            for dec, count in decade_count.items():
                if count > len(random_songs) / 3:
                    repeated_decade = dec
                    break
            if repeated_decade:
                to_remove = next((s for s in random_songs if s.year and str(s.year)[:3] + '0' == repeated_decade), None)
                if to_remove:
                    random_songs.remove(to_remove)
                    decade_count[repeated_decade] -= 1

                    # pick a new random
                    refill = [s for s in non_overused_songs if s not in random_songs]
                    if refill:
                        new_song = random.choice(refill)
                        random_songs.append(new_song)
                        if new_song.year:
                            dec_new = str(new_song.year)[:3] + '0'
                            decade_count[dec_new] = decade_count.get(dec_new, 0) + 1

                        # update artist_count
                        artist_count[to_remove.artist] -= 1
                        artist_count[new_song.artist] = artist_count.get(new_song.artist, 0) + 1
                    else:
                        # If no new songs available, just return what we have
                        return random_songs

        elif len(artist_count) != len(random_songs):
            # 3. if there's mismatch in how many unique artists vs. songs, fix that
            #    i.e. if we have a repeated artist but haven't caught it above
            refill = [s for s in non_overused_songs if s not in random_songs]
            repeated_song = None
            # find a repeated artist
            for s in random_songs:
                if artist_count[s.artist] > 1:
                    repeated_song = s
                    break
            if repeated_song is None or not refill:
                break  # fallback

            random_songs.remove(repeated_song)
            artist_count[repeated_song.artist] -= 1

            new_song = random.choice(refill)
            random_songs.append(new_song)
            artist_count[new_song.artist] = artist_count.get(new_song.artist, 0) + 1

            if repeated_song.year:
                dec_removed = str(repeated_song.year)[:3] + '0'
                decade_count[dec_removed] = decade_count.get(dec_removed, 0) - 1
            if new_song.year:
                dec_new = str(new_song.year)[:3] + '0'
                decade_count[dec_new] = decade_count.get(dec_new, 0) + 1

    return random_songs

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
        deezer_client = current_app.config['deezer']
        songs_per_round = current_app.config.get('SONGS_PER_ROUND', 10)
        
        imported_songs = ImportHelper.import_item(
            item_id=playlist_id,
            item_type='playlist',
            source='deezer',
            deezer_client=deezer_client
        )

        if not imported_songs:
            current_app.logger.warning(f"No songs returned from ImportHelper.import_item for Deezer playlist {playlist_id}")
            return []

        return imported_songs[:songs_per_round]
    except Exception as e:
        current_app.logger.error(f"Error fetching or importing Deezer playlist {playlist_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return []

def get_songs_from_spotify_playlist(playlist_id):
    """
    Fetch songs from a Spotify playlist, properly import them with metadata, and return them
    """
    try:
        songs_per_round = current_app.config.get('SONGS_PER_ROUND', 10)
        
        imported_songs = ImportHelper.import_item(
            item_id=playlist_id,
            item_type='playlist',
            source='spotify',
            oauth_spotify=oauth.spotify
        )
        
        if not imported_songs:
            current_app.logger.warning(f"No songs returned from ImportHelper.import_item for Spotify playlist {playlist_id}")
            return []
            
        return imported_songs[:songs_per_round]
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
                
            round_criteria = f'Spotify Playlist: {playlist_id}'
            
        else:
            flash('Please select a valid platform', 'error')
            return redirect(url_for('generate.import_playlist'))
            
        return render_template('round.html', 
                               songs=songs, 
                               round_criteria=round_criteria, 
                               round_name=round_name,
                               playlist_import=True)
    
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
    song_ids = request.form.getlist('song_id')

    # get list of song objects from database
    songs = Song.query.filter(Song.id.in_(song_ids)).all()

    # create string representation of song IDs
    song_ids_str = ','.join(song_id for song_id in song_ids)

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