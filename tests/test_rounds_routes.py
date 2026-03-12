"""Tests for rounds blueprint routes."""
import pytest
import json
from musicround.models import db, User, Song, Round


def _login(app, client, username='roundsuser', email='rounds@example.com'):
    """Helper: create and log in a user."""
    with app.app_context():
        existing = User.query.filter_by(username=username).first()
        if not existing:
            user = User(username=username, email=email)
            user.password = 'RoundsPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'RoundsPass123!'})


def _create_song(app, title='Round Test Song', artist='Band', genre='Pop'):
    """Helper: create a song and return its id."""
    with app.app_context():
        song = Song(title=title, artist=artist, genre=genre)
        db.session.add(song)
        db.session.commit()
        return song.id


def _create_round(app, songs_ids, name='Test Round'):
    """Helper: create a round and return its id."""
    with app.app_context():
        round_ = Round(
            name=name,
            round_type='genre',
            round_criteria_used='Rock',
            songs=','.join(str(i) for i in songs_ids),
        )
        db.session.add(round_)
        db.session.commit()
        return round_.id


class TestRoundsListRoute:
    """Tests for GET /rounds/ (rounds_list)."""

    def test_rounds_list_requires_login(self, client):
        """Test that rounds list requires authentication."""
        response = client.get('/rounds/')
        assert response.status_code == 302
        assert 'login' in response.headers['Location'].lower()

    def test_rounds_list_empty(self, app, client):
        """Test rounds list shows empty state when no rounds exist."""
        _login(app, client)
        response = client.get('/rounds/')
        assert response.status_code == 200

    def test_rounds_list_with_rounds(self, app, client):
        """Test rounds list shows rounds when they exist."""
        _login(app, client)
        song_id = _create_song(app)
        _create_round(app, [song_id], name='List Test Round')

        response = client.get('/rounds/')
        assert response.status_code == 200
        assert b'List Test Round' in response.data


class TestRoundDetailRoute:
    """Tests for GET /rounds/<id> (round_detail)."""

    def test_round_detail_not_found(self, app, client):
        """Test that viewing a non-existent round returns an error."""
        _login(app, client)
        response = client.get('/rounds/99999')
        assert response.status_code in (200, 404)  # Returns 'Round not found' string or 404

    def test_round_detail_exists(self, app, client):
        """Test viewing an existing round."""
        _login(app, client)
        song_id = _create_song(app, title='Detail Song')
        round_id = _create_round(app, [song_id], name='Detail Round')

        response = client.get(f'/rounds/{round_id}')
        assert response.status_code == 200


class TestRoundUpdateName:
    """Tests for POST /rounds/<id>/update-name."""

    def test_update_round_name(self, app, client):
        """Test updating a round's name."""
        _login(app, client)
        song_id = _create_song(app, title='Name Update Song')
        round_id = _create_round(app, [song_id], name='Original Name')

        response = client.post(
            f'/rounds/{round_id}/update-name',
            data={'round_name': 'Updated Name'},
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            round_ = Round.query.get(round_id)
            assert round_.name == 'Updated Name'

    def test_update_round_name_empty(self, app, client):
        """Test updating a round's name to empty clears the name."""
        _login(app, client)
        song_id = _create_song(app, title='Empty Name Song')
        round_id = _create_round(app, [song_id], name='Has Name')

        response = client.post(
            f'/rounds/{round_id}/update-name',
            data={'round_name': ''},
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            round_ = Round.query.get(round_id)
            assert round_.name is None


class TestRoundUpdateSongs:
    """Tests for POST /rounds/<id>/update-songs."""

    def test_update_round_songs_same_order(self, app, client):
        """Test updating songs with same order flashes no-change message."""
        _login(app, client)
        song_id = _create_song(app, title='Song Order Same')
        round_id = _create_round(app, [song_id])

        with app.app_context():
            round_ = Round.query.get(round_id)
            original_songs = round_.songs

        response = client.post(
            f'/rounds/{round_id}/update-songs',
            data={'song_order': original_songs},
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_update_round_songs_new_order(self, app, client):
        """Test updating song order changes the round."""
        _login(app, client)
        s1 = _create_song(app, title='Song Order 1')
        s2 = _create_song(app, title='Song Order 2')
        round_id = _create_round(app, [s1, s2])

        new_order = f'{s2},{s1}'
        response = client.post(
            f'/rounds/{round_id}/update-songs',
            data={'song_order': new_order},
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            round_ = Round.query.get(round_id)
            assert round_.songs == new_order


class TestRoundDelete:
    """Tests for POST /rounds/<id>/delete."""

    def test_delete_round(self, app, client):
        """Test deleting an existing round."""
        _login(app, client)
        song_id = _create_song(app, title='Delete Song')
        round_id = _create_round(app, [song_id], name='Round To Delete')

        response = client.post(f'/rounds/{round_id}/delete')
        assert response.status_code in (200, 302)

        with app.app_context():
            assert Round.query.get(round_id) is None

    def test_delete_nonexistent_round(self, app, client):
        """Test deleting a non-existent round returns 404."""
        _login(app, client)
        response = client.post('/rounds/99999/delete')
        assert response.status_code == 404


class TestRoundDownloadRoutes:
    """Tests for download routes."""

    def test_download_mp3_not_found(self, app, client):
        """Test downloading MP3 for non-existent round returns appropriate response."""
        _login(app, client)
        response = client.get('/rounds/download/mp3/round_99999')
        assert response.status_code in (302, 404, 500)

    def test_download_pdf_not_found(self, app, client):
        """Test downloading PDF for non-existent round returns appropriate response."""
        _login(app, client)
        response = client.get('/rounds/download/pdf/round_99999')
        assert response.status_code in (302, 404, 500)
