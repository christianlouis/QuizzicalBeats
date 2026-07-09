"""Tests for rounds blueprint routes."""
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch, mock_open
from flask import jsonify
from pydub import AudioSegment
from musicround.helpers.paths import app_data_path
from musicround.models import db, PlannedQuizRound, User, Song, Round, RoundAccessEvent, RoundAudioScript, RoundExport, RoundShare, SystemSetting
from musicround.routes.rounds import ROUND_QUALITY_SESSION_REPORT_MAX_CHARS, _session_quality_report
from musicround.services.automation import AutomationError


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


def _approve_round(app, round_id):
    """Mark a round as approved so delivery-specific route tests reach delivery gates."""
    with app.app_context():
        round_ = db.session.get(Round, round_id)
        round_.review_status = 'approved'
        round_.approved_at = datetime.utcnow()
        db.session.commit()


def _passing_round_quality():
    return {
        'ok': True,
        'status': 'ok',
        'hints': [],
        'report': {'headline': 'Round is ready to send.', 'markdown': '# Ready'},
    }


class _PreviewResponse:
    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield b'ID3 preview'


class _DeezerPreviewStub:
    def __init__(self, preview_url='https://example.test/preview.mp3'):
        self.preview_url = preview_url

    def get_track(self, deezer_id):
        return {'id': deezer_id, 'preview': self.preview_url}


def _user_id(app, username):
    with app.app_context():
        return User.query.filter_by(username=username).one().id


def _set_song_deezer_id(app, song_id, deezer_id='123'):
    with app.app_context():
        song = db.session.get(Song, song_id)
        song.deezer_id = deezer_id
        db.session.commit()


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
                    due_at=datetime.utcnow() + timedelta(hours=12),
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
        assert b'Deliverables' in response.data
        assert b'Approved round' in response.data
        assert b'Due soon' in response.data
        assert b'Hidden other quizmaster' not in response.data

    def test_round_analytics_page_renders_summary(self, app, client):
        """Round analytics should render catalog health signals."""
        _login(app, client)
        _create_song(app, title='Analytics Song')

        response = client.get('/rounds/analytics?months=6&limit=5&repeat_threshold=2')

        assert response.status_code == 200
        assert b'Round Analytics' in response.data
        assert b'Missing Previews' in response.data
        assert b'Repeat Alert' in response.data
        assert b'Artists' in response.data
        assert b'Decades' in response.data
        assert b'Themes' in response.data
        assert b'/view-songs?has_preview=false' in response.data
        assert b'/view-songs?genre=__missing__' in response.data
        assert b'Create planning brief' in response.data

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

    def test_round_detail_lazy_loads_named_preview_controls(self, app, client):
        """Round detail should keep previews lazy and label the play control."""
        _login(app, client)
        with app.app_context():
            song = Song(
                title='Round Preview',
                artist='Round Artist',
                genre='Pop',
                preview_url='https://example.com/round-preview.mp3',
            )
            db.session.add(song)
            db.session.commit()
            song_id = song.id
        round_id = _create_round(app, [song_id], name='Preview Round')

        response = client.get(f'/rounds/{round_id}')

        assert response.status_code == 200
        assert b'round-preview-load-btn' in response.data
        assert b'data-preview-url="https://example.com/round-preview.mp3"' in response.data
        assert b'aria-label="Load preview for Round Preview by Round Artist"' in response.data
        assert b'<audio controls class="w-full max-w-[200px]"' not in response.data

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
        assert f'/rounds/{round_id}/bundle-review'.encode() in response.data

    def test_round_bundle_review_shows_assets_quality_songs_and_scripts(self, app, client):
        """Bundle review should collect generated files and review context."""
        _login(app, client)
        song_id = _create_song(app, title='Bundle Song', artist='Bundle Artist')
        round_id = _create_round(app, [song_id], name='Bundle Review Round')
        with app.app_context():
            db.session.add(RoundAudioScript(
                round_id=round_id,
                script_type='intro',
                text='Bundle intro text',
                status='approved',
            ))
            db.session.add(RoundExport(
                round_id=round_id,
                user_id=_user_id(app, 'roundsuser'),
                export_type='email',
                destination='quizmaster@example.test',
                include_mp3s=True,
                status='scheduled',
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            ))
            db.session.commit()
            with open(os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3'), 'wb') as handle:
                handle.write(b'fake mp3')
            with open(os.path.join(app.config['ROUND_PDF_DIR'], f'round_{round_id}.pdf'), 'wb') as handle:
                handle.write(b'%PDF-1.4 fake pdf')

        quality = {
            'quality': {'status': 'ok'},
            'report': {
                'ok': True,
                'status': 'ok',
                'headline': 'Bundle Review Round is ready.',
                'blockers': [],
                'warnings': ['Minor timing drift.'],
                'failed_positions': [],
            },
        }
        with patch('musicround.routes.rounds.automation.round_repair_report', return_value=quality):
            response = client.get(f'/rounds/{round_id}/bundle-review')

        assert response.status_code == 200
        assert b'Bundle Review' in response.data
        assert b'Bundle Review Round is ready.' in response.data
        assert b'Minor timing drift.' in response.data
        assert b'Bundle Artist - Bundle Song' in response.data
        assert b'Bundle intro text' in response.data
        assert b'Send to My Inbox Now' in response.data
        assert b'Schedule Email' in response.data
        assert b'Local timezone: Europe/Berlin' in response.data
        assert b'Cancel Scheduled Email' in response.data
        assert f'/rounds/download/mp3/round_{round_id}?inline=1'.encode() in response.data
        assert f'/rounds/download/pdf/round_{round_id}?inline=1'.encode() in response.data

    def test_round_bundle_review_can_schedule_email_delivery(self, app, client):
        """Bundle review schedule form should call the robust scheduler service."""
        _login(app, client)
        song_id = _create_song(app, title='Scheduled Bundle Song')
        round_id = _create_round(app, [song_id], name='Scheduled Bundle Round')
        _approve_round(app, round_id)

        scheduled = {
            'scheduled': True,
            'export': {
                'id': 42,
                'scheduled_for': '2026-07-09T17:00:00Z',
            },
        }
        with patch('musicround.routes.rounds.automation.schedule_round_email', return_value=scheduled) as mock_schedule:
            response = client.post(
                f'/rounds/{round_id}/schedule-email',
                data={
                    'scheduled_for': '2026-07-09T19:00',
                    'recipient': 'quizmaster@example.test',
                    'subject': 'Thursday Round',
                    'body_text': 'Here comes the round.',
                },
            )

        assert response.status_code == 302
        assert response.headers['Location'].endswith(f'/rounds/{round_id}/bundle-review')
        mock_schedule.assert_called_once_with(
            round_id=round_id,
            scheduled_for='2026-07-09T19:00:00+02:00',
            recipient='quizmaster@example.test',
            user_id=_user_id(app, 'roundsuser'),
            subject='Thursday Round',
            body_text='Here comes the round.',
            replace_existing=True,
        )

    def test_round_bundle_review_rejects_invalid_schedule_time(self, app, client):
        """Invalid schedule form values should not reach the scheduler service."""
        _login(app, client)
        song_id = _create_song(app, title='Invalid Schedule Song')
        round_id = _create_round(app, [song_id], name='Invalid Schedule Round')

        with patch('musicround.routes.rounds.automation.schedule_round_email') as mock_schedule:
            response = client.post(
                f'/rounds/{round_id}/schedule-email',
                data={'scheduled_for': 'not-a-date'},
            )

        assert response.status_code == 302
        assert response.headers['Location'].endswith(f'/rounds/{round_id}/bundle-review')
        mock_schedule.assert_not_called()

    def test_round_bundle_review_schedule_returns_to_review_on_quality_failure(self, app, client):
        """Schedule failures should keep the user in the review workflow."""
        _login(app, client)
        song_id = _create_song(app, title='Blocked Bundle Song')
        round_id = _create_round(app, [song_id], name='Blocked Bundle Round')
        error = AutomationError(
            'Round quality gate failed: Missing preview.',
            details={'report': {'headline': 'Missing preview.', 'markdown': '# Missing'}},
        )

        with patch('musicround.routes.rounds.automation.schedule_round_email', side_effect=error):
            response = client.post(
                f'/rounds/{round_id}/schedule-email',
                data={'scheduled_for': '2026-07-09T19:00'},
            )

        assert response.status_code == 302
        assert response.headers['Location'].endswith(f'/rounds/{round_id}/bundle-review')
        with client.session_transaction() as flask_session:
            assert '# Missing' in flask_session['round_quality_report']
        quality = {
            'quality': {'status': 'needs_substitution'},
            'report': {
                'ok': False,
                'status': 'needs_substitution',
                'headline': 'Blocked Bundle Round is blocked.',
                'blockers': [],
                'warnings': [],
                'failed_positions': [],
            },
        }
        with patch('musicround.routes.rounds.automation.round_repair_report', return_value=quality):
            review_response = client.get(f'/rounds/{round_id}/bundle-review')

        assert review_response.status_code == 200
        assert b'# Missing' in review_response.data
        with client.session_transaction() as flask_session:
            assert 'round_quality_report' not in flask_session

    def test_round_bundle_review_can_cancel_scheduled_email(self, app, client):
        """Bundle review should let a producer cancel a pending scheduled email."""
        _login(app, client)
        song_id = _create_song(app, title='Cancel Schedule Song')
        round_id = _create_round(app, [song_id], name='Cancel Schedule Round')
        with app.app_context():
            export = RoundExport(
                round_id=round_id,
                user_id=_user_id(app, 'roundsuser'),
                export_type='email',
                destination='quizmaster@example.test',
                include_mp3s=True,
                status='scheduled',
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()
            export_id = export.id

        response = client.post(f'/rounds/{round_id}/scheduled-emails/{export_id}/cancel')

        assert response.status_code == 302
        assert response.headers['Location'].endswith(f'/rounds/{round_id}/bundle-review')
        with app.app_context():
            export = db.session.get(RoundExport, export_id)
            assert export.status == 'cancelled'
            assert export.error_message == 'Cancelled from bundle review.'

    def test_round_bundle_review_cancel_blocks_other_user_export(self, app, client):
        """Cancel route should not cancel another user's pending export."""
        _login(app, client)
        song_id = _create_song(app, title='Other Export Song')
        round_id = _create_round(app, [song_id], name='Other Export Round')
        _login(app, client, username='other_scheduler', email='other@example.test')
        other_user_id = _user_id(app, 'other_scheduler')
        _login(app, client)
        with app.app_context():
            export = RoundExport(
                round_id=round_id,
                user_id=other_user_id,
                export_type='email',
                destination='other@example.test',
                include_mp3s=True,
                status='scheduled',
                scheduled_for=datetime(2026, 7, 9, 17, 0),
            )
            db.session.add(export)
            db.session.commit()
            export_id = export.id

        response = client.post(f'/rounds/{round_id}/scheduled-emails/{export_id}/cancel')

        assert response.status_code == 302
        with app.app_context():
            export = db.session.get(RoundExport, export_id)
            assert export.status == 'scheduled'

    def test_round_bundle_review_hides_private_round_owned_by_other_user(self, app, client):
        """Bundle review should use the same visibility boundary as detail view."""
        _login(app, client, username='bundle_viewer', email='bundle_viewer@example.com')
        _login(app, client, username='bundle_owner', email='bundle_owner@example.com')
        song_id = _create_song(app, title='Hidden Bundle Song')
        owner_id = _user_id(app, 'bundle_owner')
        _login(app, client, username='bundle_viewer', email='bundle_viewer@example.com')
        round_id = _create_round(app, [song_id], name='Hidden Bundle Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'private'
            db.session.commit()

        response = client.get(f'/rounds/{round_id}/bundle-review')

        assert response.status_code == 404

    def test_round_pdf_inline_preview_is_not_attachment(self, app, client):
        """PDF preview mode should be embeddable by the bundle review page."""
        _login(app, client)
        song_id = _create_song(app, title='Inline PDF Song')
        round_id = _create_round(app, [song_id], name='Inline PDF Round')
        with app.app_context():
            with open(os.path.join(app.config['ROUND_PDF_DIR'], f'round_{round_id}.pdf'), 'wb') as handle:
                handle.write(b'%PDF-1.4 inline')

        response = client.get(f'/rounds/download/pdf/round_{round_id}?inline=1')

        assert response.status_code == 200
        assert not response.headers.get('Content-Disposition', '').startswith('attachment')

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
        assert b'text-red-700 mt-1' in response.data

    def test_round_detail_styles_success_email_export_message_as_neutral(self, app, client):
        """Successful delivery messages should not be shown as red errors."""
        _login(app, client)
        song_id = _create_song(app, title='Success Export Detail Song')
        round_id = _create_round(app, [song_id], name='Success Export Detail Round')
        with app.app_context():
            db.session.add(RoundExport(
                round_id=round_id,
                export_type='email',
                destination='rounds@example.com',
                status='success',
                error_message='Email delivered to rounds@example.com.',
            ))
            db.session.commit()

        response = client.get(f'/rounds/{round_id}')

        assert response.status_code == 200
        assert b'Email delivered to rounds@example.com.' in response.data
        assert b'text-gray-500 mt-1' in response.data

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

    def test_shared_commenter_can_review_but_not_edit_or_produce(self, app, client):
        """Comment shares can leave review feedback without production rights."""
        _login(app, client, username='comment_owner', email='comment_owner@example.com')
        _login(app, client, username='comment_user', email='comment_user@example.com')
        song_id = _create_song(app, title='Comment Role Song')
        owner_id = _user_id(app, 'comment_owner')
        commenter_id = _user_id(app, 'comment_user')
        client.get('/users/logout')
        _login(app, client, username='comment_user', email='comment_user@example.com')
        round_id = _create_round(app, [song_id], name='Comment Shared Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=commenter_id, role='comment'))
            db.session.commit()

        detail = client.get(f'/rounds/{round_id}')
        review = client.post(
            f'/rounds/{round_id}/review',
            data={'review_status': 'blocked', 'review_notes': 'Preview missing.'},
        )
        edit = client.post(f'/rounds/{round_id}/update-name', data={'round_name': 'Blocked Edit'})
        mp3 = client.post(
            f'/rounds/round/{round_id}/mp3',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        schedule = client.post(f'/rounds/{round_id}/schedule-email')

        assert detail.status_code == 200
        assert review.status_code == 302
        assert edit.status_code == 403
        assert mp3.status_code == 403
        assert schedule.status_code == 403
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            assert round_.name == 'Comment Shared Round'
            assert round_.review_status == 'blocked'
            assert round_.review_notes == 'Preview missing.'

    def test_shared_editor_cannot_produce_assets_or_delete_round(self, app, client):
        """Editor shares should not grant production, delivery, export, or delete rights."""
        _login(app, client, username='producer_block_owner', email='producer_block_owner@example.com')
        _login(app, client, username='producer_block_editor', email='producer_block_editor@example.com')
        song_id = _create_song(app, title='Editor Block Song')
        owner_id = _user_id(app, 'producer_block_owner')
        editor_id = _user_id(app, 'producer_block_editor')
        client.get('/users/logout')
        _login(app, client, username='producer_block_editor', email='producer_block_editor@example.com')
        round_id = _create_round(app, [song_id], name='Editor Production Block Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=editor_id, role='editor'))
            db.session.commit()

        update = client.post(
            f'/rounds/{round_id}/update-name',
            data={'round_name': 'Editor Still Can Edit'},
        )
        mp3 = client.post(
            f'/rounds/round/{round_id}/mp3',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        pdf = client.post(
            f'/rounds/{round_id}/pdf',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        mail = client.post(
            f'/rounds/{round_id}/mail',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        dropbox = client.post(f'/rounds/{round_id}/export-to-dropbox')
        delete = client.post(f'/rounds/{round_id}/delete')

        assert update.status_code == 302
        assert mp3.status_code == 403
        assert mp3.is_json
        assert mp3.get_json() == {
            'success': False,
            'error': 'You do not have permission to produce assets for this round.',
        }
        assert pdf.status_code == 403
        assert pdf.is_json
        assert pdf.get_json() == {
            'success': False,
            'error': 'You do not have permission to produce assets for this round.',
        }
        assert mail.status_code == 403
        assert mail.is_json
        assert mail.get_json() == {
            'success': False,
            'error': 'You do not have permission to produce assets for this round.',
        }
        assert dropbox.status_code == 403
        assert dropbox.is_json
        assert dropbox.get_json() == {
            'success': False,
            'error': 'You do not have permission to produce assets for this round.',
        }
        assert delete.status_code == 403
        with app.app_context():
            assert db.session.get(Round, round_id).name == 'Editor Still Can Edit'

    def test_shared_producer_can_generate_pdf_but_not_manage_or_delete(self, app, client):
        """Producer shares can create artifacts without owner-level administration."""
        _login(app, client, username='producer_owner', email='producer_owner@example.com')
        _login(app, client, username='producer_user', email='producer_user@example.com')
        _login(app, client, username='producer_target', email='producer_target@example.com')
        song_id = _create_song(app, title='Producer Song')
        owner_id = _user_id(app, 'producer_owner')
        producer_id = _user_id(app, 'producer_user')
        client.get('/users/logout')
        _login(app, client, username='producer_user', email='producer_user@example.com')
        round_id = _create_round(app, [song_id], name='Producer Shared Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=producer_id, role='producer'))
            db.session.commit()

        update = client.post(
            f'/rounds/{round_id}/update-name',
            data={'round_name': 'Producer Updated Round'},
        )
        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF-1.4 test'):
            pdf = client.post(
                f'/rounds/{round_id}/pdf',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )
        share = client.post(
            f'/rounds/{round_id}/shares',
            data={'user_query': 'producer_target', 'role': 'viewer'},
        )
        delete = client.post(f'/rounds/{round_id}/delete')

        assert update.status_code == 302
        assert pdf.status_code == 200
        assert pdf.get_json()['success'] is True
        assert share.status_code == 403
        assert delete.status_code == 403
        with app.app_context():
            assert db.session.get(Round, round_id).name == 'Producer Updated Round'
            assert db.session.get(Round, round_id).pdf_generated is True

    def test_private_round_pdf_generation_requires_visibility(self, app, client):
        """A logged-in user should not generate PDFs for another user's private round."""
        _login(app, client, username='private_pdf_owner', email='private_pdf_owner@example.com')
        _login(app, client, username='private_pdf_other', email='private_pdf_other@example.com')
        song_id = _create_song(app, title='Private PDF Song')
        owner_id = _user_id(app, 'private_pdf_owner')
        client.get('/users/logout')
        _login(app, client, username='private_pdf_owner', email='private_pdf_owner@example.com')
        round_id = _create_round(app, [song_id], name='Private PDF Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'private'
            db.session.commit()

        client.get('/users/logout')
        _login(app, client, username='private_pdf_other', email='private_pdf_other@example.com')
        response = client.post(
            f'/rounds/{round_id}/pdf',
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

        assert response.status_code == 404

    def test_round_owner_can_share_and_revoke_from_detail(self, app, client):
        """Owners should be able to manage explicit round shares in the browser."""
        _login(app, client, username='share_owner_ui', email='share_owner_ui@example.com')
        _login(app, client, username='share_target_ui', email='share_target_ui@example.com')
        song_id = _create_song(app, title='Share UI Song')
        owner_id = _user_id(app, 'share_owner_ui')
        target_id = _user_id(app, 'share_target_ui')
        _login(app, client, username='share_owner_ui', email='share_owner_ui@example.com')
        round_id = _create_round(app, [song_id], name='Owner Share UI Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'private'
            db.session.commit()

        add_response = client.post(
            f'/rounds/{round_id}/shares',
            data={'user_query': 'share_target_ui', 'role': 'editor'},
            follow_redirects=True,
        )

        assert add_response.status_code == 200
        assert b'share_target_ui' in add_response.data
        assert b'share_target_ui@example.com' in add_response.data
        assert b'Editor' in add_response.data
        assert b'Access History' in add_response.data
        assert b'Share Created' in add_response.data
        assert b'by share_owner_ui' in add_response.data
        with app.app_context():
            share = RoundShare.query.filter_by(round_id=round_id, user_id=target_id).one()
            share_event = RoundAccessEvent.query.filter_by(
                round_id=round_id,
                target_user_id=target_id,
                action='share_created',
            ).one()
            assert share.role == 'editor'
            assert share_event.actor_user_id == owner_id
            assert share_event.role == 'editor'
            assert db.session.get(Round, round_id).visibility == 'shared'

        delete_response = client.post(
            f'/rounds/{round_id}/shares/{target_id}/delete',
            follow_redirects=True,
        )

        assert delete_response.status_code == 200
        assert b'This round is not shared with other quizmasters.' in delete_response.data
        assert b'Share Revoked' in delete_response.data
        with app.app_context():
            assert RoundShare.query.filter_by(round_id=round_id, user_id=target_id).count() == 0
            revoke_event = RoundAccessEvent.query.filter_by(
                round_id=round_id,
                target_user_id=target_id,
                action='share_revoked',
            ).one()
            assert revoke_event.actor_user_id == owner_id
            assert revoke_event.role == 'editor'
            assert db.session.get(Round, round_id).visibility == 'private'

    def test_shared_editor_cannot_manage_round_shares(self, app, client):
        """Edit access should not grant share administration."""
        _login(app, client, username='share_admin_owner', email='share_admin_owner@example.com')
        _login(app, client, username='share_admin_editor', email='share_admin_editor@example.com')
        _login(app, client, username='share_admin_target', email='share_admin_target@example.com')
        song_id = _create_song(app, title='Share Admin Song')
        owner_id = _user_id(app, 'share_admin_owner')
        editor_id = _user_id(app, 'share_admin_editor')
        client.get('/users/logout')
        _login(app, client, username='share_admin_editor', email='share_admin_editor@example.com')
        round_id = _create_round(app, [song_id], name='Editor No Share Admin Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'shared'
            db.session.add(RoundShare(round_id=round_id, user_id=editor_id, role='editor'))
            db.session.commit()

        detail = client.get(f'/rounds/{round_id}')
        blocked = client.post(
            f'/rounds/{round_id}/shares',
            data={'user_query': 'share_admin_target', 'role': 'viewer'},
        )

        assert detail.status_code == 200
        assert b'id="round-share-form"' not in detail.data
        assert b'Access History' not in detail.data
        assert b'share_admin_editor' in detail.data
        assert b'share_admin_editor@example.com' not in detail.data
        assert blocked.status_code == 403

    def test_round_owner_can_enable_and_disable_public_readonly_link(self, app, client):
        """Owners can publish and revoke a token-based read-only round link."""
        _login(app, client, username='public_owner', email='public_owner@example.com')
        song_id = _create_song(app, title='Public Route Song', artist='Public Artist')
        owner_id = _user_id(app, 'public_owner')
        round_id = _create_round(app, [song_id], name='Public Route Round')
        with app.app_context():
            SystemSetting.set('enable_public_rounds', 'true')
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            round_.visibility = 'private'
            db.session.commit()
        expires_on = (datetime.utcnow() + timedelta(days=3)).date().isoformat()

        enable_response = client.post(
            f'/rounds/{round_id}/public-link',
            data={'action': 'enable', 'expires_at': expires_on},
            follow_redirects=True,
        )

        assert enable_response.status_code == 200
        assert b'Public round link enabled.' in enable_response.data
        assert b'Public Read-only Link' in enable_response.data
        assert b'Disable Link' in enable_response.data
        assert f'Expires {expires_on}'.encode() in enable_response.data
        with app.app_context():
            round_obj = db.session.get(Round, round_id)
            public_token = round_obj.public_token
            assert public_token
            assert round_obj.public_token_expires_at is not None
            assert RoundAccessEvent.query.filter_by(
                round_id=round_id,
                action='public_link_enabled',
                actor_user_id=owner_id,
            ).count() == 1

        client.get('/users/logout')
        public_response = client.get(f'/rounds/public/{public_token}')

        assert public_response.status_code == 200
        assert b'Public Route Round' in public_response.data
        assert b'Public Route Song' in public_response.data
        assert b'Read-only' in public_response.data
        assert b'Delete Quiz' not in public_response.data

        _login(app, client, username='public_owner', email='public_owner@example.com')
        disable_response = client.post(
            f'/rounds/{round_id}/public-link',
            data={'action': 'disable'},
            follow_redirects=True,
        )
        disabled_public_response = client.get(f'/rounds/public/{public_token}')

        assert disable_response.status_code == 200
        assert b'Public round link disabled.' in disable_response.data
        assert disabled_public_response.status_code == 404

    def test_public_round_link_honors_admin_setting_and_permissions(self, app, client):
        """Public link management should require both the system flag and ownership."""
        _login(app, client, username='public_owner_two', email='public_owner_two@example.com')
        _login(app, client, username='public_other', email='public_other@example.com')
        song_id = _create_song(app, title='Public Disabled Song')
        owner_id = _user_id(app, 'public_owner_two')
        _login(app, client, username='public_owner_two', email='public_owner_two@example.com')
        round_id = _create_round(app, [song_id], name='Public Disabled Round')
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            round_.user_id = owner_id
            db.session.commit()

        disabled_response = client.post(
            f'/rounds/{round_id}/public-link',
            data={'action': 'enable'},
            follow_redirects=True,
        )

        assert disabled_response.status_code == 200
        assert b'Public round links are disabled' in disabled_response.data

        with app.app_context():
            SystemSetting.set('enable_public_rounds', 'true')
        client.get('/users/logout')
        _login(app, client, username='public_other', email='public_other@example.com')

        forbidden_response = client.post(
            f'/rounds/{round_id}/public-link',
            data={'action': 'enable'},
        )

        assert forbidden_response.status_code == 404

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

    def test_update_round_review_rejects_manual_sent(self, app, client):
        """Sent is system-managed and cannot be selected manually."""
        _login(app, client)
        song_id = _create_song(app, title='Manual Sent Route Song')
        round_id = _create_round(app, [song_id], name='Manual Sent Route Round')

        response = client.post(
            f'/rounds/{round_id}/review',
            data={'review_status': 'sent', 'review_notes': 'Nope'},
        )

        assert response.status_code == 400
        with app.app_context():
            round_ = db.session.get(Round, round_id)
            assert round_.review_status == 'draft'

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

    def test_round_quality_endpoint_reports_numeric_parameter_errors(self, app, client):
        """Quality endpoint should describe all numeric parameter parse failures."""
        _login(app, client)
        song_id = _create_song(app, title='Quality Parameter Song')
        round_id = _create_round(app, [song_id], name='Quality Parameter Round')

        response = client.get(
            f'/rounds/{round_id}/quality'
            '?expected_song_count=many'
            '&min_preview_seconds=short'
            '&duration_tolerance_seconds=wide'
            '&max_preview_seconds=-1'
        )

        assert response.status_code == 400
        assert response.get_json() == {
            'success': False,
            'error': 'Quality parameter values must be numeric and within allowed ranges.',
            'details': {
                'invalid_parameters': [
                    {'name': 'expected_song_count', 'value': 'many'},
                    {'name': 'min_preview_seconds', 'value': 'short'},
                    {'name': 'max_preview_seconds', 'value': '-1'},
                    {'name': 'duration_tolerance_seconds', 'value': 'wide'},
                ],
            },
        }

    def test_round_quality_endpoint_rejects_out_of_range_parameters(self, app, client):
        """Quality endpoint should reject bounds instead of silently clamping them."""
        _login(app, client)
        song_id = _create_song(app, title='Quality Bounds Song')
        round_id = _create_round(app, [song_id], name='Quality Bounds Round')

        response = client.get(
            f'/rounds/{round_id}/quality'
            '?expected_song_count=0'
            '&duration_tolerance_seconds=-5'
        )

        assert response.status_code == 400
        assert response.get_json()['details']['invalid_parameters'] == [
            {'name': 'expected_song_count', 'value': '0'},
            {'name': 'duration_tolerance_seconds', 'value': '-5'},
        ]

    def test_round_quality_endpoint_rejects_inverted_preview_bounds(self, app, client):
        """Preview min/max limits should fail fast before package inspection."""
        _login(app, client)
        song_id = _create_song(app, title='Quality Inverted Song')
        round_id = _create_round(app, [song_id], name='Quality Inverted Round')

        with patch('musicround.routes.rounds.automation.round_repair_report') as mock_report:
            response = client.get(
                f'/rounds/{round_id}/quality'
                '?min_preview_seconds=35'
                '&max_preview_seconds=20'
            )

        assert response.status_code == 400
        assert response.get_json()['details']['invalid_parameters'] == [
            {'name': 'min_preview_seconds', 'value': '35'},
            {'name': 'max_preview_seconds', 'value': '20'},
        ]
        mock_report.assert_not_called()

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
        _approve_round(app, round_id)

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

    def test_round_mp3_existing_file_does_not_regenerate_by_default(self, app, client):
        """Existing generated MP3s should be reused unless force=true is posted."""
        _login(app, client)
        song_id = _create_song(app, title='Existing MP3 Song')
        round_id = _create_round(app, [song_id], name='Existing MP3 Round')
        mp3_path = os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3')
        with open(mp3_path, 'wb') as handle:
            handle.write(b'ID3')

        with app.app_context():
            round_obj = db.session.get(Round, round_id)
            round_obj.mp3_generated = True
            db.session.commit()

        with patch('musicround.routes.rounds.AudioSegment.from_mp3') as mock_from_mp3:
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is True
        assert response.get_json()['message'] == 'MP3 file already exists'
        assert response.get_json()['mp3_status'] == 'exists'
        mock_from_mp3.assert_not_called()

    def test_round_mp3_first_generation_reports_generated_status(self, app, client):
        """First-time MP3 generation should report the generated machine status."""
        _login(app, client)
        song_id = _create_song(app, title='Generated MP3 Song')
        _set_song_deezer_id(app, song_id)
        round_id = _create_round(app, [song_id], name='Generated MP3 Round')
        mp3_path = os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3')

        def fake_export(segment, path, format='mp3'):
            with open(path, 'wb') as handle:
                handle.write(b'NEW')
            return None

        app.config['deezer'] = _DeezerPreviewStub()
        with patch(
            'musicround.routes.rounds.AudioSegment.from_mp3',
            return_value=AudioSegment.silent(duration=100),
        ) as mock_from_mp3, patch(
            'musicround.routes.rounds.requests.get',
            return_value=_PreviewResponse(),
        ), patch('pydub.audio_segment.AudioSegment.export', fake_export):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is True
        assert response.get_json()['message'] == 'MP3 file successfully generated'
        assert response.get_json()['mp3_status'] == 'generated'
        assert mock_from_mp3.called
        with open(mp3_path, 'rb') as handle:
            assert handle.read() == b'NEW'

    def test_round_mp3_force_regenerates_existing_file(self, app, client):
        """force=true should bypass the existing-file shortcut and render again."""
        _login(app, client)
        song_id = _create_song(app, title='Force MP3 Song')
        _set_song_deezer_id(app, song_id)
        round_id = _create_round(app, [song_id], name='Force MP3 Round')
        mp3_path = os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3')
        with open(mp3_path, 'wb') as handle:
            handle.write(b'OLD')

        with app.app_context():
            round_obj = db.session.get(Round, round_id)
            round_obj.mp3_generated = True
            db.session.commit()

        def fake_export(segment, path, format='mp3'):
            with open(path, 'wb') as handle:
                handle.write(b'NEW')
            return None

        app.config['deezer'] = _DeezerPreviewStub()
        with patch(
            'musicround.routes.rounds.AudioSegment.from_mp3',
            return_value=AudioSegment.silent(duration=100),
        ) as mock_from_mp3, patch(
            'musicround.routes.rounds.requests.get',
            return_value=_PreviewResponse(),
        ), patch('pydub.audio_segment.AudioSegment.export', fake_export):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                data={'force': 'true'},
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is True
        assert response.get_json()['message'] == 'MP3 file successfully regenerated'
        assert response.get_json()['mp3_status'] == 'regenerated'
        assert mock_from_mp3.called
        with open(mp3_path, 'rb') as handle:
            assert handle.read() == b'NEW'

    def test_round_mp3_fails_when_song_has_no_deezer_preview_identity(self, app, client):
        """MP3 generation must not silently export rounds with skipped songs."""
        _login(app, client)
        song_id = _create_song(app, title='No Deezer ID Song')
        round_id = _create_round(app, [song_id], name='No Deezer ID Round')
        mp3_path = os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3')

        with (
            patch(
                'musicround.routes.rounds.AudioSegment.from_mp3',
                return_value=AudioSegment.silent(duration=100),
            ),
            patch('pydub.audio_segment.AudioSegment.export') as mock_export,
        ):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        payload = response.get_json()
        assert response.status_code == 422
        assert payload['success'] is False
        assert payload['error'] == 'Song preview audio is missing. Replace the song and try again.'
        assert not os.path.exists(mp3_path)
        mock_export.assert_not_called()
        with app.app_context():
            assert db.session.get(Round, round_id).mp3_generated is False

    def test_round_mp3_fails_when_deezer_track_has_no_preview(self, app, client):
        """Provider tracks without preview URLs should force replacement before export."""
        _login(app, client)
        song_id = _create_song(app, title='No Preview Song')
        _set_song_deezer_id(app, song_id)
        round_id = _create_round(app, [song_id], name='No Preview Round')
        mp3_path = os.path.join(app.config['ROUND_MP3_DIR'], f'round_{round_id}.mp3')
        app.config['deezer'] = _DeezerPreviewStub(preview_url=None)

        with (
            patch(
                'musicround.routes.rounds.AudioSegment.from_mp3',
                return_value=AudioSegment.silent(duration=100),
            ),
            patch('musicround.routes.rounds.requests.get') as mock_get,
            patch('pydub.audio_segment.AudioSegment.export') as mock_export,
        ):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        payload = response.get_json()
        assert response.status_code == 422
        assert payload['success'] is False
        assert payload['error'] == 'Song preview audio is missing. Replace the song and try again.'
        assert not os.path.exists(mp3_path)
        mock_get.assert_not_called()
        mock_export.assert_not_called()
        with app.app_context():
            assert db.session.get(Round, round_id).mp3_generated is False

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

    def test_round_mp3_uses_selected_round_intro_before_user_default(self, app, client, tmp_path):
        """Round-specific generated intro audio should override the user/default intro."""
        _login(app, client)
        song_id = _create_song(app, title='Round Intro Song')
        round_id = _create_round(app, [song_id], name='Round Intro Round')
        intro_rel_path = 'custommp3/roundsuser/round_intro.mp3'
        with app.app_context():
            app.config['DATA_DIR'] = str(tmp_path / 'data')
            song = db.session.get(Song, song_id)
            song.deezer_id = 123
            intro_path = app_data_path(intro_rel_path)
            os.makedirs(os.path.dirname(intro_path), exist_ok=True)
            with open(intro_path, 'wb') as handle:
                handle.write(b'ID3')
            db.session.add(RoundAudioScript(
                round_id=round_id,
                script_type='intro',
                text='A round-specific opener.',
                status='used',
                selected=True,
                generated_mp3_path=intro_rel_path,
            ))
            db.session.commit()
            app.config['ROUND_MP3_DIR'] = str(tmp_path)
            app.config['deezer'] = _DeezerPreviewStub()

        exported_lengths = []

        def fake_from_mp3(path):
            path = str(path)
            if path.endswith('round_intro.mp3'):
                return AudioSegment.silent(duration=5000)
            if path.endswith('intro.mp3') or path.endswith('replay.mp3') or path.endswith('outro.mp3'):
                return AudioSegment.silent(duration=1000)
            if 'song_' in path:
                return AudioSegment.silent(duration=30000)
            if path.endswith('1.mp3'):
                return AudioSegment.silent(duration=100)
            return AudioSegment.silent(duration=1)

        def fake_export(segment, path, format='mp3'):
            exported_lengths.append(len(segment))
            with open(path, 'wb') as handle:
                handle.write(b'ID3')
            return None

        with patch('musicround.routes.rounds.AudioSegment.from_mp3', side_effect=fake_from_mp3), \
                patch('musicround.routes.rounds.requests.get', return_value=_PreviewResponse()), \
                patch('pydub.audio_segment.AudioSegment.export', fake_export):
            response = client.post(
                f'/rounds/round/{round_id}/mp3',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 200
        assert response.get_json()['success'] is True
        assert exported_lengths == [67200]

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
        _approve_round(app, round_id)

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
        _approve_round(app, round_id)
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
        _approve_round(app, round_id)

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
        _approve_round(app, round_id)
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
        _approve_round(app, round_id)

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
        _approve_round(app, round_id)
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
        _approve_round(app, round_id)
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
                patch(
                    'musicround.routes.rounds.round_notifications.send_round_blocked_notification',
                ) as mock_notify, \
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
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs['round_id'] == round_id
        assert mock_notify.call_args.kwargs['quality'] == quality
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
        _approve_round(app, round_id)
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

    def test_mail_route_redirect_truncates_quality_report_session_payload(self, app, client):
        """Large repair reports should not exceed Flask session cookie limits."""
        _login(app, client)
        song_id = _create_song(app, title='Large Redirect Quality Song')
        round_id = _create_round(app, [song_id], name='Large Redirect Quality Round')
        _approve_round(app, round_id)
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        large_tail = 'TAIL_SHOULD_NOT_RENDER'
        quality = {
            'ok': False,
            'status': 'needs_substitution',
            'hints': ['Large Redirect Quality Song has no preview.'],
            'report': {
                'headline': 'Large Redirect Quality Round is blocked: needs_substitution.',
                'markdown': '# Large Redirect Quality Round is blocked\n\n' + ('x' * 5000) + large_tail,
            },
        }

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch(
                    'musicround.routes.rounds.automation.inspect_round_package',
                    return_value=quality,
                ), \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(f'/rounds/{round_id}/mail', follow_redirects=True)

        assert response.status_code == 200
        assert b'Large Redirect Quality Round is blocked' in response.data
        assert b'Report truncated' in response.data
        assert large_tail.encode() not in response.data
        assert len(_session_quality_report(quality['report'])) <= ROUND_QUALITY_SESSION_REPORT_MAX_CHARS
        mock_send.assert_not_called()

    def test_mail_route_handles_unexpected_quality_gate_exception(self, app, client):
        """Unexpected inspection failures should return a controlled safe response."""
        _login(app, client)
        song_id = _create_song(app, title='Unexpected Quality Error Song')
        round_id = _create_round(app, [song_id], name='Unexpected Quality Error Round')
        _approve_round(app, round_id)
        with app.app_context():
            round_ = Round.query.get(round_id)
            round_.mp3_generated = True
            db.session.commit()

        with patch('musicround.routes.rounds.generate_pdf', return_value=b'%PDF'), \
                patch('musicround.routes.rounds.os.path.exists', return_value=True), \
                patch(
                    'musicround.routes.rounds.automation.inspect_round_package',
                    side_effect=RuntimeError('database exploded'),
                ), \
                patch('musicround.routes.rounds.send_quiz_email') as mock_send:
            response = client.post(
                f'/rounds/{round_id}/mail',
                headers={'X-Requested-With': 'XMLHttpRequest'},
            )

        assert response.status_code == 500
        assert response.get_json() == {
            'success': False,
            'error': 'Round quality gate could not run. Please try again later or contact an administrator.',
        }
        mock_send.assert_not_called()
