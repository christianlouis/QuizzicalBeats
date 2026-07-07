"""Tests for rounds blueprint routes."""
import json
from datetime import datetime
from unittest.mock import patch, mock_open
from flask import jsonify
from pydub import AudioSegment
from musicround.models import db, PlannedQuizRound, User, Song, Round, RoundAudioScript, RoundExport, RoundShare


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


def _create_songs(app, count, title_prefix='Round Test Song'):
    """Helper: create several songs and return their ids."""
    return [
        _create_song(app, title=f'{title_prefix} {index}', artist='Band', genre='Pop')
        for index in range(count)
    ]


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


def _passing_round_quality():
    return {
        'ok': True,
        'status': 'ok',
        'hints': [],
        'report': {'headline': 'Round is ready to send.', 'markdown': '# Ready'},
    }


def _user_id(app, username):
    with app.app_context():
        return User.query.filter_by(username=username).one().id


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

    def test_rounds_list_shows_readiness_and_schedule_status(self, app, client):
        """Round list should show asset readiness and scheduled delivery state."""
        _login(app, client)
        song_ids = _create_songs(app, 8, title_prefix='Ready Song')
        ready_round_id = _create_round(app, song_ids, name='Ready Round')
        partial_round_id = _create_round(app, song_ids, name='Partial Round')

        with app.app_context():
            ready_round = db.session.get(Round, ready_round_id)
            ready_round.mp3_generated = True
            ready_round.pdf_generated = True

            partial_round = db.session.get(Round, partial_round_id)
            partial_round.mp3_generated = True

            export = RoundExport(
                round_id=ready_round_id,
                export_type='email',
                status='scheduled',
                destination='quizmaster@example.test',
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()

        response = client.get('/rounds/')

        assert response.status_code == 200
        assert b'Assets ready' in response.data
        assert b'Partial assets' in response.data
        assert b'Scheduled' in response.data
        assert b'2026-07-09 17:00' in response.data

    def test_rounds_list_flags_incomplete_and_unresolved_rounds(self, app, client):
        """Round list should make non-eight-song and broken-ID rounds obvious."""
        _login(app, client)
        short_song_ids = _create_songs(app, 6, title_prefix='Short Song')
        full_song_ids = _create_songs(app, 8, title_prefix='Full Song')
        _create_round(app, short_song_ids, name='Short Round')
        _create_round(app, full_song_ids, name='Too Full Round')
        _create_round(app, full_song_ids[:7] + [999999], name='Broken Round')

        response = client.get('/rounds/')

        assert response.status_code == 200
        assert b'Songs 6/8' in response.data
        assert b'Resolves 7/8' in response.data
        assert b'7/8 songs resolve' in response.data

    def test_rounds_list_shows_latest_email_failure_when_not_scheduled(self, app, client):
        """Round list should expose failed delivery attempts even without active schedule."""
        _login(app, client)
        song_ids = _create_songs(app, 8, title_prefix='Failed Email Song')
        round_id = _create_round(app, song_ids, name='Failed Email Round')
        with app.app_context():
            export = RoundExport(
                round_id=round_id,
                export_type='email',
                status='failed',
                destination='quizmaster@example.test',
                timestamp=datetime(2026, 7, 9, 18, 0),
                processed_at=datetime(2026, 7, 9, 18, 1),
            )
            db.session.add(export)
            db.session.commit()

        response = client.get('/rounds/')

        assert response.status_code == 200
        assert b'Email failed' in response.data
        assert b'2026-07-09 18:01' in response.data

    def test_rounds_list_is_paginated(self, app, client):
        """Round list should only render the requested page of rounds."""
        _login(app, client)
        song_id = _create_song(app, title='Paged Song')
        for index in range(30):
            _create_round(app, [song_id], name=f'Paged Round {index:02d}')

        first_page = client.get('/rounds/?per_page=25')
        second_page = client.get('/rounds/?per_page=25&page=2')

        assert first_page.status_code == 200
        assert b'Paged Round 29' in first_page.data
        assert b'Paged Round 00' not in first_page.data
        assert b'Page 1 of 2' in first_page.data

        assert second_page.status_code == 200
        assert b'Paged Round 00' in second_page.data
        assert b'Paged Round 29' not in second_page.data
        assert b'Page 2 of 2' in second_page.data

    def test_round_calendar_shows_scheduled_exports(self, app, client):
        """Round calendar should expose scheduled delivery dates."""
        _login(app, client)
        song_ids = _create_songs(app, 8, title_prefix='Calendar Song')
        round_id = _create_round(app, song_ids, name='Calendar Round')
        with app.app_context():
            db.session.add(RoundExport(
                round_id=round_id,
                export_type='email',
                status='scheduled',
                destination='rounds@example.test',
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            ))
            db.session.commit()

        response = client.get('/rounds/calendar')

        assert response.status_code == 200
        assert b'Calendar Round' in response.data
        assert b'2026-07-09 17:00' in response.data

    def test_round_calendar_shows_visible_planned_quiz_dates(self, app, client):
        """Round calendar should expose own and unassigned planned quiz dates."""
        _login(app, client, username='planner', email='planner@example.test')
        planner_id = _user_id(app, 'planner')
        with app.app_context():
            other = User(username='otherplanner', email='otherplanner@example.test')
            other.password = 'RoundsPass123!'
            db.session.add(other)
            db.session.commit()
            db.session.add_all([
                PlannedQuizRound(
                    quiz_date=datetime(2026, 7, 9, 17, 0),
                    quizmaster_id=planner_id,
                    theme='Festival repair night',
                    status='planned',
                ),
                PlannedQuizRound(
                    quiz_date=datetime(2026, 7, 16, 17, 0),
                    theme='Unassigned Thursday',
                    status='blocked',
                ),
                PlannedQuizRound(
                    quiz_date=datetime(2026, 7, 23, 17, 0),
                    quizmaster_id=other.id,
                    theme='Hidden other quizmaster',
                    status='planned',
                ),
            ])
            db.session.commit()

        response = client.get('/rounds/calendar')

        assert response.status_code == 200
        assert b'Planned Quiz Dates' in response.data
        assert b'Festival repair night' in response.data
        assert b'Unassigned Thursday' in response.data
        assert b'Hidden other quizmaster' not in response.data

    def test_round_analytics_page_renders_summary(self, app, client):
        """Round analytics should render catalog health signals."""
        _login(app, client)
        _create_song(app, title='Analytics Song')

        response = client.get('/rounds/analytics?months=6&limit=5')

        assert response.status_code == 200
        assert b'Round Analytics' in response.data
        assert b'Missing Previews' in response.data

    def test_round_planning_page_renders_brief(self, app, client):
        """Planning page should turn quizmaster context into a brief."""
        _login(app, client)

        response = client.get(
            '/rounds/planning?theme=festival&quiz_date=2026-07-09T19:00&desired_song_count=8'
        )

        assert response.status_code == 200
        assert b'Round Planning Brief' in response.data
        assert b'Build exactly 8 songs' in response.data

    def test_rounds_list_only_shows_visible_owned_or_shared_rounds(self, app, client):
        """Round ownership should keep private rounds out of other quizmasters' lists."""
        _login(app, client, username='visible_owner', email='visible_owner@example.com')
        _login(app, client, username='visible_other', email='visible_other@example.com')
        _login(app, client, username='visible_owner', email='visible_owner@example.com')
        song_id = _create_song(app, title='Visible Song')

        with app.app_context():
            owner_id = User.query.filter_by(username='visible_owner').one().id
            other_id = User.query.filter_by(username='visible_other').one().id
            own_round = Round(
                name='Own Visible Round',
                round_type='manual',
                round_criteria_used='own',
                songs=str(song_id),
                user_id=owner_id,
                visibility='private',
            )
            other_private = Round(
                name='Other Private Round',
                round_type='manual',
                round_criteria_used='other',
                songs=str(song_id),
                user_id=other_id,
                visibility='private',
            )
            other_public = Round(
                name='Other Public Round',
                round_type='manual',
                round_criteria_used='public',
                songs=str(song_id),
                user_id=other_id,
                visibility='public',
            )
            shared_round = Round(
                name='Shared Visible Round',
                round_type='manual',
                round_criteria_used='shared',
                songs=str(song_id),
                user_id=other_id,
                visibility='shared',
            )
            legacy_round = Round(
                name='Legacy Visible Round',
                round_type='manual',
                round_criteria_used='legacy',
                songs=str(song_id),
            )
            db.session.add_all([own_round, other_private, other_public, shared_round, legacy_round])
            db.session.flush()
            db.session.add(RoundShare(round_id=shared_round.id, user_id=owner_id, role='viewer'))
            db.session.commit()

        response = client.get('/rounds/')

        assert response.status_code == 200
        assert b'Own Visible Round' in response.data
        assert b'Other Public Round' in response.data
        assert b'Shared Visible Round' in response.data
        assert b'Legacy Visible Round' in response.data
        assert b'Other Private Round' not in response.data
        assert b'visible_owner' in response.data
        assert b'visible_other' in response.data


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

    def test_round_detail_shows_review_and_audio_scripts(self, app, client):
        """Round detail should surface review state and script drafts."""
        _login(app, client)
        song_id = _create_song(app, title='Script Detail Song')
        round_id = _create_round(app, [song_id], name='Script Detail Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.review_status = 'reviewed'
            db.session.add(RoundAudioScript(
                round_id=round_id,
                script_type='intro',
                text='Welcome to the review round',
                status='draft',
            ))
            db.session.commit()

        response = client.get(f'/rounds/{round_id}')

        assert response.status_code == 200
        assert b'Reviewed' in response.data
        assert b'Welcome to the review round' in response.data

    def test_round_detail_shows_failed_email_export_message(self, app, client):
        """Round detail should show persisted delivery/quality failure feedback."""
        _login(app, client)
        song_id = _create_song(app, title='Failed Export Detail Song')
        round_id = _create_round(app, [song_id], name='Failed Export Detail Round')
        with app.app_context():
            db.session.add(RoundExport(
                round_id=round_id,
                export_type='email',
                destination='rounds@example.com',
                status='failed',
                error_message='Failed Export Detail Round is blocked: needs_substitution.',
            ))
            db.session.commit()

        response = client.get(f'/rounds/{round_id}')

        assert response.status_code == 200
        assert b'Failed Export Detail Round is blocked: needs_substitution.' in response.data

    def test_round_detail_hides_private_round_owned_by_other_user(self, app, client):
        """Private owned rounds should not be visible to other quizmasters."""
        _login(app, client, username='viewer_one', email='viewer_one@example.com')
        _login(app, client, username='viewer_two', email='viewer_two@example.com')
        song_id = _create_song(app, title='Hidden Song')
        other_id = _user_id(app, 'viewer_two')
        _login(app, client, username='viewer_one', email='viewer_one@example.com')
        round_id = _create_round(app, [song_id], name='Hidden Private Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = other_id
            round_.visibility = 'private'
            db.session.commit()

        response = client.get(f'/rounds/{round_id}')

        assert response.status_code == 404

    def test_shared_viewer_can_view_but_not_edit_round(self, app, client):
        """Viewer shares are read-only in browser routes."""
        _login(app, client, username='share_viewer', email='share_viewer@example.com')
        _login(app, client, username='share_owner', email='share_owner@example.com')
        song_id = _create_song(app, title='Shared Viewer Song')
        owner_id = _user_id(app, 'share_owner')
        viewer_id = _user_id(app, 'share_viewer')
        _login(app, client, username='share_viewer', email='share_viewer@example.com')
        round_id = _create_round(app, [song_id], name='Viewer Shared Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=viewer_id, role='viewer'))
            db.session.commit()

        detail = client.get(f'/rounds/{round_id}')
        edit = client.post(f'/rounds/{round_id}/update-name', data={'round_name': 'Blocked'})

        assert detail.status_code == 200
        assert edit.status_code == 403

    def test_shared_editor_can_update_round(self, app, client):
        """Editor shares can modify round metadata."""
        _login(app, client, username='share_editor', email='share_editor@example.com')
        _login(app, client, username='editor_owner', email='editor_owner@example.com')
        song_id = _create_song(app, title='Shared Editor Song')
        owner_id = _user_id(app, 'editor_owner')
        editor_id = _user_id(app, 'share_editor')
        _login(app, client, username='share_editor', email='share_editor@example.com')
        round_id = _create_round(app, [song_id], name='Editor Shared Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=editor_id, role='editor'))
            db.session.commit()

        response = client.post(
            f'/rounds/{round_id}/update-name',
            data={'round_name': 'Editor Updated Round'},
            follow_redirects=True,
        )

        assert response.status_code == 200
        with app.app_context():
            assert db.session.get(Round, round_id).name == 'Editor Updated Round'

    def test_update_round_review_marks_approval(self, app, client):
        """Review route should persist approved state and notes."""
        _login(app, client)
        song_id = _create_song(app, title='Approved Song')
        round_id = _create_round(app, [song_id], name='Approval Round')

        response = client.post(
            f'/rounds/{round_id}/review',
            data={'review_status': 'approved', 'review_notes': 'Ready for Thursday'},
        )

        assert response.status_code == 302
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            assert round_.review_status == 'approved'
            assert round_.review_notes == 'Ready for Thursday'
            assert round_.approved_at is not None
            assert round_.approved_by_id is not None

        response = client.post(
            f'/rounds/{round_id}/review',
            data={'review_status': 'reviewed', 'review_notes': 'Needs another pass'},
        )

        assert response.status_code == 302
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            assert round_.review_status == 'reviewed'
            assert round_.review_notes == 'Needs another pass'
            assert round_.approved_at is None
            assert round_.approved_by_id is None

    def test_round_quality_endpoint_returns_repair_report(self, app, client):
        """Quality endpoint should expose automation repair feedback."""
        _login(app, client)
        song_id = _create_song(app, title='Quality Song')
        round_id = _create_round(app, [song_id], name='Quality Round')
        payload = {
            'quality': {'status': 'needs_substitution'},
            'report': {'ok': False, 'summary': 'Needs replacement', 'failed_positions': []},
        }
        with patch('musicround.routes.rounds.automation.round_repair_report', return_value=payload):
            response = client.get(f'/rounds/{round_id}/quality')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['report']['summary'] == 'Needs replacement'

    def test_replacement_endpoints_proxy_automation(self, app, client):
        """Replacement routes should make repair candidates actionable."""
        _login(app, client)
        song_id = _create_song(app, title='Broken Song')
        replacement_id = _create_song(app, title='Replacement Song')
        round_id = _create_round(app, [song_id], name='Repair Round')
        suggestions = {
            'round_id': round_id,
            'position': 1,
            'suggestions': [{'id': replacement_id, 'title': 'Replacement Song'}],
            'count': 1,
        }
        replacement = {
            'round': {'id': round_id},
            'position': 1,
            'replacement_song': {'id': replacement_id},
        }
        with patch('musicround.routes.rounds.automation.suggest_replacement_songs', return_value=suggestions):
            response = client.get(f'/rounds/{round_id}/replacement-suggestions?position=1')
        assert response.status_code == 200
        assert response.get_json()['suggestions'][0]['id'] == replacement_id

        with patch('musicround.routes.rounds.automation.replace_round_song', return_value=replacement):
            response = client.post(
                f'/rounds/{round_id}/replace-song',
                data={'position': '1', 'replacement_song_id': str(replacement_id)},
            )
        assert response.status_code == 200
        assert response.get_json()['success'] is True

    def test_audio_script_routes_create_and_update_review_records(self, app, client):
        """Script routes should connect browser review to automation helpers."""
        _login(app, client)
        song_id = _create_song(app, title='Announcement Song')
        round_id = _create_round(app, [song_id], name='Announcement Round')

        with patch('musicround.routes.rounds.automation.draft_round_audio_scripts') as draft_scripts:
            response = client.post(
                f'/rounds/{round_id}/draft-audio-scripts',
                data={'theme': 'summer', 'tone': 'warm'},
            )
        assert response.status_code == 302
        draft_scripts.assert_called_once()

        with patch('musicround.routes.rounds.automation.draft_round_track_hints') as draft_hints:
            response = client.post(
                f'/rounds/{round_id}/draft-track-hints',
                data={'tone': 'playful'},
            )
        assert response.status_code == 302
        draft_hints.assert_called_once()

        with app.app_context():
            script = RoundAudioScript(
                round_id=round_id,
                script_type='intro',
                text='Draft',
                status='draft',
            )
            db.session.add(script)
            db.session.commit()
            script_id = script.id

        response = client.post(
            f'/rounds/{round_id}/audio-scripts/{script_id}',
            data={'text': 'Approved draft', 'status': 'approved', 'selected': 'on'},
        )

        assert response.status_code == 302
        with app.app_context():
            script = db.session.get(RoundAudioScript, script_id)
            assert script.status == 'approved'
            assert script.selected is True
            assert script.text == 'Approved draft'


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

    def test_delete_round_failure_hides_exception_details(self, app, client):
        """Delete failures should not expose local exception text in JSON or flash."""
        _login(app, client)
        song_id = _create_song(app, title='Delete Failure Song')
        round_id = _create_round(app, [song_id], name='Round Delete Failure')

        with patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch('musicround.routes.rounds.os.remove') as mock_remove:
            mock_remove.side_effect = RuntimeError('filesystem-secret /data/rounds')
            response = client.post(f'/rounds/{round_id}/delete', follow_redirects=True)

        assert response.status_code == 500
        body = response.get_data(as_text=True)
        assert 'filesystem-secret' not in body
        assert '/data/rounds' not in body
        assert response.get_json()['error'] == (
            'Unable to delete the round. Please try again later or contact an administrator.'
        )


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

    def test_round_mp3_hides_base_audio_exception_details(self, app, client):
        """MP3 base-audio failures should not expose filesystem or token details."""
        _login(app, client)
        song_id = _create_song(app, title='Unsafe MP3 Error Song')
        round_id = _create_round(app, [song_id], name='Unsafe MP3 Error Round')

        with patch(
            'musicround.routes.rounds.AudioSegment.from_mp3',
            side_effect=RuntimeError('base audio token=secret path=/srv/private.mp3'),
        ):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        payload = response.get_json()
        assert response.status_code == 500
        assert payload['success'] is False
        assert payload['error'] == 'Required round audio could not be loaded. Check the server logs.'
        body = response.get_data(as_text=True)
        assert 'secret' not in body
        assert '/srv/private.mp3' not in body

    def test_round_pdf_hides_generation_exception_details(self, app, client):
        """PDF generation failures should return a stable safe message."""
        _login(app, client)
        song_id = _create_song(app, title='Unsafe PDF Error Song')
        round_id = _create_round(app, [song_id], name='Unsafe PDF Error Round')

        with patch(
            'musicround.routes.rounds.generate_pdf',
            side_effect=RuntimeError('pdf token=secret template=/srv/private.html'),
        ):
            response = client.post(
                f'/rounds/{round_id}/pdf',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        payload = response.get_json()
        assert response.status_code == 500
        assert payload['success'] is False
        assert payload['error'] == 'PDF generation failed. Check the server logs.'
        body = response.get_data(as_text=True)
        assert 'secret' not in body
        assert '/srv/private.html' not in body

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

    def test_dropbox_export_blocks_unhealthy_storage_before_dropbox_calls(self, app, client):
        """Dropbox export must stop before render or upload when artifact storage is unhealthy."""
        _login(app, client)
        song_id = _create_song(app, title='Dropbox Storage Gate Song')
        round_id = _create_round(app, [song_id], name='Dropbox Storage Gate Round')
        app.config['ROUND_PDF_DIR'] = f"{app.instance_path}/missing-dropbox-export-test"

        with app.app_context():
            user = User.query.filter_by(username='roundsuser').one()
            user.dropbox_token = 'dropbox-access-token'
            user.dropbox_refresh_token = 'dropbox-refresh-token'
            db.session.commit()

        with patch('musicround.helpers.dropbox_helper.refresh_dropbox_token_if_needed') as mock_refresh, \
                patch('musicround.helpers.dropbox_helper.upload_to_dropbox') as mock_upload:
            response = client.post(
                f'/rounds/{round_id}/export-to-dropbox',
                data={'include_mp3s': 'false', 'include_pdf': 'true'},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 503
        payload = response.get_json()
        assert payload['success'] is False
        assert 'storage' in payload['error'].lower()
        assert payload['storage']['ok'] is False
        mock_refresh.assert_not_called()
        mock_upload.assert_not_called()

    def test_dropbox_export_failure_hides_exception_details(self, app, client):
        """Dropbox export failures should not expose provider or token details."""
        _login(app, client)
        song_id = _create_song(app, title='Dropbox Export Failure Song')
        round_id = _create_round(app, [song_id], name='Dropbox Export Failure Round')
        with app.app_context():
            user = User.query.filter_by(username='roundsuser').one()
            user.dropbox_token = 'dropbox-access-token'
            user.dropbox_refresh_token = 'dropbox-refresh-token'
            db.session.commit()

        with patch(
            'musicround.helpers.dropbox_helper.refresh_dropbox_token_if_needed',
            return_value={'success': True, 'message': 'ok'},
        ), patch(
            'musicround.helpers.dropbox_helper.upload_to_dropbox',
            return_value={
                'success': False,
                'message': 'provider-secret old-dropbox-access traceback',
            },
        ), patch('musicround.helpers.dropbox_helper.create_shared_link') as mock_link:
            response = client.post(
                f'/rounds/{round_id}/export-to-dropbox',
                data={'include_mp3s': 'false', 'include_pdf': 'false'},
            )

        payload = response.get_json()
        assert response.status_code == 200
        assert payload['success'] is False
        assert payload['message'] == (
            'Round export to Dropbox failed. Please try again later or reconnect Dropbox.'
        )
        body = response.get_data(as_text=True)
        assert 'provider-secret' not in body
        assert 'old-dropbox-access' not in body
        assert 'traceback' not in body
        mock_link.assert_not_called()
        with app.app_context():
            export = RoundExport.query.filter_by(round_id=round_id, export_type='dropbox').one()
            assert export.status == 'failed'
            assert export.error_message == (
                'Round export to Dropbox failed. Please try again later or reconnect Dropbox.'
            )


class TestRoundMp3Hints:
    """Tests for optional per-track hint audio in generated MP3s."""

    def test_round_mp3_inserts_selected_track_hint_before_first_play(self, app, client, tmp_path):
        """Generated MP3 duration should include selected hint audio once."""
        _login(app, client)
        song_id = _create_song(app, title='Hinted Song')
        round_id = _create_round(app, [song_id], name='Hinted Round')
        with app.app_context():
            song = db.session.get(Song, song_id)
            song.deezer_id = 123
            hint = RoundAudioScript(
                round_id=round_id,
                script_type='track_hint',
                text='A clue before the clip.',
                status='used',
                selected=True,
                cue_position=1,
                generated_mp3_path='custommp3/roundsuser/round_hint.mp3',
            )
            db.session.add(hint)
            db.session.commit()
            app.config['ROUND_MP3_DIR'] = str(tmp_path)
            app.config['deezer'] = type(
                'FakeDeezer',
                (),
                {'get_track': lambda self, deezer_id: {'preview': 'https://example.test/preview.mp3'}},
            )()

        exported_lengths = []

        def fake_from_mp3(path):
            path = str(path)
            if path.endswith('intro.mp3') or path.endswith('replay.mp3') or path.endswith('outro.mp3'):
                return AudioSegment.silent(duration=1000)
            if 'song_' in path:
                return AudioSegment.silent(duration=30000)
            if path.endswith('1.mp3'):
                return AudioSegment.silent(duration=100)
            if path.endswith('round_hint.mp3'):
                return AudioSegment.silent(duration=2000)
            return AudioSegment.silent(duration=1)

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=8192):
                yield b'ID3'

        def fake_export(segment, path, format='mp3'):
            exported_lengths.append(len(segment))
            with open(path, 'wb') as handle:
                handle.write(b'ID3')
            return None

        with patch('musicround.routes.rounds.AudioSegment.from_mp3', side_effect=fake_from_mp3), \
                patch('musicround.routes.rounds.requests.get', return_value=FakeResponse()), \
                patch('pydub.audio_segment.AudioSegment.export', fake_export):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is True
        assert exported_lengths == [65200]


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
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=_passing_round_quality(),
                ), \
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
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=_passing_round_quality(),
                ), \
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
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=_passing_round_quality(),
                ), \
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

    def test_mail_route_blocks_failed_package_quality_before_sending(self, app, client):
        """UI email delivery must not bypass the package quality gate."""
        _login(app, client)
        user_id = _user_id(app, 'roundsuser')
        song_id = _create_song(app, title='Short Preview Song')
        round_id = _create_round(app, [song_id], name='Blocked Quality Round')
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        quality = {
            'ok': False,
            'status': 'needs_substitution',
            'hints': ['Short Preview Song preview is 10.0s; expected at least 20.0s.'],
            'report': {
                'headline': 'Blocked Quality Round is blocked: needs_substitution.',
                'markdown': '# Blocked Quality Round is blocked',
                'failed_positions': [{'position': 1}],
            },
        }

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch('builtins.open', mock_open(read_data=b'ID3 test mp3')) as opened, \
                patch(
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=quality,
                ) as mock_quality, \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 422
        payload = response.get_json()
        assert payload['success'] is False
        assert payload['status'] == 'needs_substitution'
        assert payload['quality'] == quality
        assert payload['report'] == quality['report']
        assert 'Short Preview Song preview' in payload['hints'][0]
        mock_quality.assert_called_once_with(round_id=round_id, user_id=user_id)
        mock_send.assert_not_called()
        opened.assert_not_called()
        with app.app_context():
            export = RoundExport.query.filter_by(round_id=round_id, export_type='email').one()
            assert export.status == 'failed'
            assert export.destination == 'rounds@example.com'
            assert export.error_message == quality['report']['headline']

    def test_mail_route_redirect_shows_quality_report(self, app, client):
        """Non-AJAX email failures should carry repair feedback to round detail."""
        _login(app, client)
        user_id = _user_id(app, 'roundsuser')
        song_id = _create_song(app, title='Redirect Quality Song')
        round_id = _create_round(app, [song_id], name='Redirect Quality Round')
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        quality = {
            'ok': False,
            'status': 'needs_substitution',
            'hints': ['Redirect Quality Song has no preview.'],
            'report': {
                'headline': 'Redirect Quality Round is blocked: needs_substitution.',
                'markdown': '# Redirect Quality Round is blocked\n\nReplace position 1.',
            },
        }

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch(
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=quality,
                ) as mock_quality, \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(f'/rounds/{round_id}/mail', follow_redirects=True)

        assert response.status_code == 200
        assert b'Redirect Quality Round is blocked' in response.data
        assert b'Replace position 1.' in response.data
        mock_quality.assert_called_once_with(round_id=round_id, user_id=user_id)
        mock_send.assert_not_called()
