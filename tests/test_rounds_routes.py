"""Tests for rounds blueprint routes."""
import pytest
import json
from unittest.mock import patch, mock_open
from flask import jsonify
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


class TestLegacyEmptyRoundRoutes:
    """Tests for legacy rounds with empty song lists."""

    def test_empty_round_mp3_returns_clear_error(self, app, client):
        """Test MP3 generation does not crash for empty legacy rounds."""
        _login(app, client)
        round_id = _create_round(app, [])

        response = client.post(
            f'/rounds/round/{round_id}/mp3',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 400
        assert response.get_json()['success'] is False
        assert 'no songs' in response.get_json()['error']

    def test_empty_round_pdf_returns_clear_error(self, app, client):
        """Test PDF generation does not crash for empty legacy rounds."""
        _login(app, client)
        round_id = _create_round(app, [])

        response = client.post(
            f'/rounds/{round_id}/pdf',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 400
        assert response.get_json()['success'] is False
        assert 'no songs' in response.get_json()['error']

    def test_empty_round_dropbox_export_returns_clear_error(self, app, client):
        """Test Dropbox export does not crash for empty legacy rounds."""
        _login(app, client)
        round_id = _create_round(app, [])
        with app.app_context():
            user = User.query.filter_by(username='roundsuser').one()
            user.dropbox_token = 'dropbox-access-token'
            user.dropbox_refresh_token = 'dropbox-refresh-token'
            db.session.commit()

        with patch(
            'musicround.helpers.dropbox_helper.refresh_dropbox_token_if_needed',
            return_value={'success': True, 'message': 'ok'},
        ), patch('musicround.helpers.dropbox_helper.upload_to_dropbox') as mock_upload:
            response = client.post(
                f'/rounds/{round_id}/export-to-dropbox',
                data={'include_mp3s': 'false', 'include_pdf': 'false'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is False
        assert 'no songs' in response.get_json()['message']
        mock_upload.assert_not_called()


class TestRoundEmailRoute:
    """Tests for POST /rounds/<id>/mail."""

    def test_mail_route_returns_mp3_error_without_sending(self, app, client):
        """Test failed MP3 generation blocks email instead of crashing later."""
        _login(app, client)
        round_id = _create_round(app, [])

        def failed_mp3(_round_id):
            return jsonify({'success': False, 'error': 'Audio boom'}), 400

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.round_mp3', side_effect=failed_mp3), \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['error'] == 'Audio boom'
        mock_send.assert_not_called()

    def test_mail_route_uses_shared_email_helper_with_attachments(self, app, client):
        """Test email delivery is delegated to the shared helper."""
        _login(app, client)
        song_id = _create_song(app, title='Mailable Song')
        round_id = _create_round(app, [song_id], name='Mailable Round')
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch('builtins.open', mock_open(read_data=b'ID3 test mp3')), \
                patch(
                    'musicround.routes.rounds.send_quiz_email',
                    return_value=(True, 'sent'),
                ) as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json() == {'success': True, 'message': 'sent'}
        mock_send.assert_called_once()
        recipient, subject, body, attachments = mock_send.call_args.args
        assert recipient == 'rounds@example.com'
        assert subject == 'Mailable Round'
        assert 'Attached please find' in body
        assert attachments == [
            {
                'data': b'%PDF',
                'filename': f'round_{round_id}.pdf',
                'mimetype': 'application/pdf',
            },
            {
                'data': b'ID3 test mp3',
                'filename': f'round_{round_id}.mp3',
                'mimetype': 'audio/mpeg',
            },
        ]

    def test_mail_route_returns_pdf_error_without_sending(self, app, client):
        """Test PDF generation errors block email before attachment creation."""
        _login(app, client)
        song_id = _create_song(app, title='PDF Error Song')
        round_id = _create_round(app, [song_id], name='PDF Error Round')

        with patch(
            'musicround.routes.rounds.generate_pdf',
            return_value='Round contains no songs',
        ), patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['error'] == 'Round contains no songs'
        mock_send.assert_not_called()

    def test_mail_route_blocks_unhealthy_storage_before_generation(self, app, client):
        """Test artifact storage health blocks email before render or send."""
        _login(app, client)
        song_id = _create_song(app, title='Storage Gate Song')
        round_id = _create_round(app, [song_id], name='Storage Gate Round')
        app.config['ROUND_MP3_DIR'] = f"{app.instance_path}/missing-rounds-route-test"

        with patch('musicround.routes.rounds.generate_pdf') as mock_pdf, \
                patch('musicround.routes.rounds.round_mp3') as mock_mp3, \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 503
        payload = response.get_json()
        assert payload['success'] is False
        assert 'storage' in payload['error'].lower()
        assert payload['storage']['ok'] is False
        mock_pdf.assert_not_called()
        mock_mp3.assert_not_called()
        mock_send.assert_not_called()

    def test_mail_route_regenerates_stale_mp3_before_sending(self, app, client):
        """Test stale MP3 database state triggers regeneration before email."""
        _login(app, client)
        song_id = _create_song(app, title='Stale MP3 Song')
        round_id = _create_round(app, [song_id], name='Stale MP3 Round')

        def regenerate_mp3(_round_id):
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()
            return jsonify({'success': True, 'message': 'MP3 file successfully generated'})

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch('builtins.open', mock_open(read_data=b'ID3 refreshed mp3')), \
                patch(
                    'musicround.routes.rounds.round_mp3',
                    side_effect=regenerate_mp3,
                ) as mock_round_mp3, \
                patch(
                    'musicround.routes.rounds.send_quiz_email',
                    return_value=(True, 'sent'),
                ) as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json() == {'success': True, 'message': 'sent'}
        mock_round_mp3.assert_called_once_with(round_id)
        mock_send.assert_called_once()

    def test_mail_route_hides_email_helper_failure_details(self, app, client):
        """Test SMTP/config details are logged but not exposed to the user."""
        _login(app, client)
        song_id = _create_song(app, title='SMTP Error Song')
        round_id = _create_round(app, [song_id], name='SMTP Error Round')
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch('builtins.open', mock_open(read_data=b'ID3 test mp3')), \
                patch(
                    'musicround.routes.rounds.send_quiz_email',
                    return_value=(False, 'Missing parameters: MAIL_PASSWORD'),
                ):
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['error'] == (
            'Unable to send the email. Please try again later or contact an administrator.'
        )
