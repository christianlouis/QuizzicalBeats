import os
import shutil
import base64
import tempfile
import requests
import logging
from datetime import datetime
from io import BytesIO
import re
import zipfile
import io
import json

from flask import Blueprint, session, redirect, request, render_template, url_for, current_app, send_file, jsonify, flash, abort
from flask_login import current_user, login_required
from sqlalchemy import or_
from musicround.models import PlannedQuizRound, Round, RoundAudioScript, RoundExport, RoundShare, Song, db
from pydub import AudioSegment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from musicround.helpers.auth_helpers import oauth
from musicround.helpers.email_helper import send_email as send_quiz_email
from musicround.helpers.storage_health import (
    check_round_artifact_storage,
    round_mp3_dir,
    round_pdf_dir,
)
from musicround.services import automation
from musicround.services.automation import AutomationError

rounds_bp = Blueprint('rounds', __name__, url_prefix='/rounds')

ROUND_MP3_BASE_AUDIO_ERROR = "Required round audio could not be loaded. Check the server logs."
ROUND_MP3_NUMBER_AUDIO_ERROR = "Round number audio could not be loaded. Check the server logs."
ROUND_MP3_PREVIEW_DOWNLOAD_ERROR = "Song preview audio could not be downloaded. Check the server logs."
ROUND_MP3_PREVIEW_PROCESSING_ERROR = "Song preview audio could not be processed. Check the server logs."
ROUND_MP3_EXPORT_ERROR = "MP3 generation failed. Check the server logs."
ROUND_PDF_GENERATION_ERROR = "PDF generation failed. Check the server logs."
ROUND_QUALITY_SESSION_REPORT_MAX_CHARS = 2000


def _int_arg(name, default=None, minimum=None, maximum=None):
    raw_value = request.args.get(name)
    if raw_value in (None, ''):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _rounds_list_statuses(rounds):
    """Build compact readiness and schedule metadata for the rounds list."""
    round_ids = [round_.id for round_ in rounds]
    scheduled_by_round = {}
    latest_email_by_round = {}
    if round_ids:
        scheduled_exports = (
            RoundExport.query
            .filter(
                RoundExport.round_id.in_(round_ids),
                RoundExport.export_type == 'email',
                RoundExport.status == 'scheduled',
                RoundExport.scheduled_for.isnot(None),
            )
            .order_by(RoundExport.scheduled_for.asc(), RoundExport.id.asc())
            .all()
        )
        for export in scheduled_exports:
            scheduled_by_round.setdefault(export.round_id, export)
        latest_email_exports = (
            RoundExport.query
            .filter(
                RoundExport.round_id.in_(round_ids),
                RoundExport.export_type == 'email',
            )
            .order_by(RoundExport.timestamp.desc(), RoundExport.id.desc())
            .all()
        )
        for export in latest_email_exports:
            latest_email_by_round.setdefault(export.round_id, export)

    statuses = {}
    for round_ in rounds:
        stored_song_count = len(round_.song_id_list)
        resolved_song_count = len(round_.song_list)
        if stored_song_count != 8:
            readiness = {
                'label': f'Songs {stored_song_count}/8',
                'color': 'red',
                'hint': 'Rounds should contain exactly eight stored songs before delivery.',
                'stored_song_count': stored_song_count,
                'resolved_song_count': resolved_song_count,
            }
        elif resolved_song_count != stored_song_count:
            readiness = {
                'label': f'Resolves {resolved_song_count}/8',
                'color': 'red',
                'hint': 'One or more stored song IDs no longer resolve to songs.',
                'stored_song_count': stored_song_count,
                'resolved_song_count': resolved_song_count,
            }
        elif round_.mp3_generated and round_.pdf_generated:
            readiness = {
                'label': 'Assets ready',
                'color': 'green',
                'hint': 'MP3 and PDF have been generated.',
                'stored_song_count': stored_song_count,
                'resolved_song_count': resolved_song_count,
            }
        elif round_.mp3_generated or round_.pdf_generated:
            readiness = {
                'label': 'Partial assets',
                'color': 'yellow',
                'hint': 'Only one of MP3 or PDF has been generated.',
                'stored_song_count': stored_song_count,
                'resolved_song_count': resolved_song_count,
            }
        else:
            readiness = {
                'label': 'Needs assets',
                'color': 'gray',
                'hint': 'Generate MP3 and PDF before delivery.',
                'stored_song_count': stored_song_count,
                'resolved_song_count': resolved_song_count,
            }

        scheduled_export = scheduled_by_round.get(round_.id)
        if scheduled_export:
            schedule = {
                'label': 'Scheduled',
                'color': 'blue',
                'scheduled_for': scheduled_export.scheduled_for,
                'destination': scheduled_export.destination,
            }
        else:
            latest_email_export = latest_email_by_round.get(round_.id)
            if latest_email_export and latest_email_export.status == 'success':
                schedule = {
                    'label': 'Email sent',
                    'color': 'green',
                    'scheduled_for': latest_email_export.processed_at or latest_email_export.timestamp,
                    'destination': latest_email_export.destination,
                }
            elif latest_email_export and latest_email_export.status == 'failed':
                schedule = {
                    'label': 'Email failed',
                    'color': 'red',
                    'scheduled_for': latest_email_export.processed_at or latest_email_export.timestamp,
                    'destination': latest_email_export.destination,
                }
            elif latest_email_export and latest_email_export.status in {'processing', 'pending'}:
                schedule = {
                    'label': latest_email_export.status.capitalize(),
                    'color': 'yellow',
                    'scheduled_for': latest_email_export.processed_at or latest_email_export.timestamp,
                    'destination': latest_email_export.destination,
                }
            else:
                schedule = {
                    'label': 'Not scheduled',
                    'color': 'gray',
                    'scheduled_for': None,
                    'destination': None,
                }

        statuses[round_.id] = {'readiness': readiness, 'schedule': schedule}
    return statuses


def _visible_rounds_query():
    """Return rounds visible to the current authenticated user."""
    query = Round.query
    if current_user.is_admin:
        return query
    return query.filter(
        or_(
            Round.user_id == current_user.id,
            Round.user_id.is_(None),
            Round.visibility == 'public',
            Round.shares.any(RoundShare.user_id == current_user.id),
        )
    )


def _can_view_round(round_obj):
    if current_user.is_admin:
        return True
    if round_obj.user_id is None:
        return True
    if round_obj.user_id == current_user.id:
        return True
    if round_obj.visibility == 'public':
        return True
    return round_obj.shares.filter_by(user_id=current_user.id).first() is not None


def _can_edit_round(round_obj):
    if current_user.is_admin:
        return True
    if round_obj.user_id is None:
        return True
    if round_obj.user_id == current_user.id:
        return True
    share = round_obj.shares.filter_by(user_id=current_user.id).first()
    return bool(share and share.role == 'editor')


def _get_visible_round_or_404(round_id):
    round_obj = Round.query.get_or_404(round_id)
    if not _can_view_round(round_obj):
        abort(404)
    return round_obj


def _get_editable_round_or_404(round_id):
    round_obj = _get_visible_round_or_404(round_id)
    if not _can_edit_round(round_obj):
        abort(403)
    return round_obj


def _storage_failure_response(round_id, storage_health, status_code=503):
    """Return a consistent storage-health failure for route actions."""
    hint = '; '.join(storage_health.get('hints') or [])
    error_msg = "Round artifact storage is not ready."
    if hint:
        error_msg = f"{error_msg} {hint}"
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': False,
            'error': error_msg,
            'hint': hint,
            'storage': storage_health,
        }), status_code
    flash(error_msg, 'error')
    return redirect(url_for('rounds.round_detail', round_id=round_id))


def _automation_error_response(error, status_code=400):
    details = getattr(error, 'details', None)
    payload = {'success': False, 'error': str(error)}
    if details:
        payload['details'] = details
    return jsonify(payload), status_code


def _bool_form_value(name, default=False):
    raw_value = request.form.get(name, request.args.get(name))
    if raw_value is None:
        return default
    return str(raw_value).lower() in {'1', 'true', 'yes', 'on'}


def _round_generation_failure_response(round_id, log_message, user_message, status_code=500):
    """Return safe render-generation errors while preserving details in logs."""
    current_app.logger.error(log_message)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': user_message}), status_code
    flash(user_message, 'error')
    return redirect(url_for('rounds.round_detail', round_id=round_id))


def _session_quality_report(report):
    """Keep repair feedback small enough for Flask's cookie-backed session."""
    markdown = (report or {}).get('markdown') or ''
    if len(markdown) <= ROUND_QUALITY_SESSION_REPORT_MAX_CHARS:
        return markdown
    suffix = "\n\n[Report truncated; rerun Inspect Round for full details.]"
    body_max = max(0, ROUND_QUALITY_SESSION_REPORT_MAX_CHARS - len(suffix))
    return (
        markdown[:body_max].rstrip()
        + suffix
    )


def _round_quality_failure_response(round_id, quality, recipient=None, subject=None, body_text=None):
    """Persist and return repairable package-gate failures before email delivery."""
    report = quality.get('report') or {}
    error_msg = report.get('headline') or 'Round quality gate failed. Repair the round before sending.'
    db.session.add(
        RoundExport(
            round_id=round_id,
            user_id=current_user.id,
            export_type='email',
            destination=recipient,
            include_mp3s=True,
            status='failed',
            subject=subject,
            body_text=body_text,
            error_message=error_msg,
            processed_at=datetime.utcnow(),
        )
    )
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': False,
            'error': error_msg,
            'status': quality.get('status'),
            'hints': quality.get('hints', []),
            'quality': quality,
            'report': report,
        }), 422
    flash(error_msg, 'error')
    session['round_quality_report'] = _session_quality_report(report)
    return redirect(url_for('rounds.round_detail', round_id=round_id))


def _selected_track_hint_audio(round_id):
    """Load selected per-track hint audio keyed by one-based song position."""
    hints = {}
    scripts = (
        RoundAudioScript.query.filter_by(
            round_id=round_id,
            script_type='track_hint',
            selected=True,
        )
        .filter(RoundAudioScript.generated_mp3_path.isnot(None))
        .order_by(RoundAudioScript.cue_position.asc(), RoundAudioScript.id.asc())
        .all()
    )
    for script in scripts:
        if not script.cue_position:
            continue
        path = os.path.join('/data', script.generated_mp3_path)
        try:
            hints[script.cue_position] = AudioSegment.from_mp3(path)
        except Exception as exc:
            current_app.logger.warning(
                "Skipping track hint audio for round %s position %s: %s",
                round_id,
                script.cue_position,
                exc,
            )
    return hints

@rounds_bp.route('/')
@login_required
def rounds_list():
    """Display a paginated list of rounds."""
    page = _int_arg('page', default=1, minimum=1)
    per_page = _int_arg('per_page', default=25, minimum=1, maximum=100)
    query = _visible_rounds_query().order_by(Round.created_at.desc(), Round.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    rounds = pagination.items
    query_args = {'per_page': per_page}
    return render_template(
        'rounds.html',
        rounds=rounds,
        pagination=pagination,
        query_args=query_args,
        filters={'per_page': per_page},
        round_statuses=_rounds_list_statuses(rounds),
    )


@rounds_bp.route('/calendar')
@login_required
def rounds_calendar():
    """Show planned quiz dates and scheduled email exports as a lightweight calendar."""
    visible_round_ids = _visible_rounds_query().with_entities(Round.id)
    planned_query = PlannedQuizRound.query
    if not current_user.is_admin:
        planned_query = planned_query.filter(
            or_(
                PlannedQuizRound.quizmaster_id == current_user.id,
                PlannedQuizRound.quizmaster_id.is_(None),
                PlannedQuizRound.round_id.in_(visible_round_ids),
            )
        )
    planned_rounds = (
        planned_query
        .order_by(PlannedQuizRound.quiz_date.asc(), PlannedQuizRound.id.asc())
        .limit(100)
        .all()
    )
    exports = (
        RoundExport.query.filter(
            RoundExport.round_id.in_(visible_round_ids),
            RoundExport.export_type == 'email',
            RoundExport.scheduled_for.isnot(None),
        )
        .order_by(RoundExport.scheduled_for.asc(), RoundExport.id.asc())
        .limit(100)
        .all()
    )
    return render_template('round_calendar.html', exports=exports, planned_rounds=planned_rounds)


@rounds_bp.route('/analytics')
@login_required
def rounds_analytics():
    """Show catalog and music-round fatigue signals for planning."""
    months = _int_arg('months', default=6, minimum=1, maximum=36)
    limit = _int_arg('limit', default=20, minimum=1, maximum=100)
    try:
        summary = automation.round_analytics_summary(months=months, limit=limit)
    except AutomationError as exc:
        flash(str(exc), 'error')
        summary = None
    return render_template(
        'round_analytics.html',
        summary=summary,
        filters={'months': months, 'limit': limit},
    )


@rounds_bp.route('/planning')
@login_required
def round_planning():
    """Render an agent-readable planning brief for the current quizmaster."""
    months = _int_arg('months', default=3, minimum=1, maximum=24)
    desired_song_count = _int_arg('desired_song_count', default=8, minimum=1, maximum=25)
    theme = request.args.get('theme') or None
    quiz_date = request.args.get('quiz_date') or None
    brief = None
    if theme or quiz_date:
        try:
            brief = automation.round_planning_brief(
                user_id=current_user.id,
                quiz_date=quiz_date,
                theme=theme,
                desired_song_count=desired_song_count,
                months=months,
            )
        except AutomationError as exc:
            flash(str(exc), 'error')
    return render_template(
        'round_planning.html',
        brief=brief,
        filters={
            'theme': theme or '',
            'quiz_date': quiz_date or '',
            'months': months,
            'desired_song_count': desired_song_count,
        },
    )


@rounds_bp.route('/<int:round_id>')
@login_required
def round_detail(round_id):
    """Display details of a specific round"""
    rnd = _get_visible_round_or_404(round_id)
    
    if rnd:
        ordered_songs = rnd.song_list
        
        email_error = session.pop('email_error', None)  # Retrieve and remove the error message from the session
        round_quality_report = session.pop('round_quality_report', None)
        
        # For oauth.spotify, we need to ensure we have a valid token if needed for this view
        user_info = None
        try:
            if current_user.is_authenticated and current_user.spotify_token:
                # Use oauth.spotify to get user info
                # Ensure the token is fresh or handle potential MissingTokenError
                user_info_response = oauth.spotify.get('https://api.spotify.com/v1/me')
                user_info_response.raise_for_status()  # Raise an exception for bad status codes
                user_info = user_info_response.json()
        except Exception as e:  # Catch a broader range of exceptions, including MissingTokenError
            current_app.logger.warning(f"Could not get Spotify user info using Authlib: {str(e)}")
        
        audio_scripts = (
            RoundAudioScript.query.filter_by(round_id=rnd.id)
            .order_by(RoundAudioScript.created_at.desc(), RoundAudioScript.id.desc())
            .limit(25)
            .all()
        )
        scheduled_exports = (
            RoundExport.query.filter_by(round_id=rnd.id, export_type='email')
            .order_by(RoundExport.timestamp.desc(), RoundExport.id.desc())
            .limit(10)
            .all()
        )

        return render_template(
            'round_detail.html',
            round=rnd,
            songs=ordered_songs,
            user_info=user_info,
            email_error=email_error,
            round_quality_report=round_quality_report,
            audio_scripts=audio_scripts,
            scheduled_exports=scheduled_exports,
        )
    else:
        return 'Round not found'

@rounds_bp.route('/<int:round_id>/update-name', methods=['POST'])
@login_required
def update_round_name(round_id):
    """Update the name of a round"""
    rnd = _get_editable_round_or_404(round_id)
    round_name = request.form.get('round_name', '').strip()
    
    # Update the round name
    rnd.name = round_name if round_name else None
    db.session.commit()
    
    flash('Round name updated successfully', 'success')
    return redirect(url_for('rounds.round_detail', round_id=round_id))

@rounds_bp.route('/<int:round_id>/update-songs', methods=['POST'])
@login_required
def update_round_songs(round_id):
    """Update the songs in a round (order, additions, removals)"""
    rnd = _get_editable_round_or_404(round_id)
    song_order = request.form.get('song_order', '')
    
    if song_order:
        # Only reset the flags if the song order has actually changed
        if rnd.songs != song_order:
            rnd.songs = song_order
            # Reset the MP3 and PDF generated flags when the song order changes
            rnd.reset_generated_status()
            db.session.commit()
            flash('Round songs updated successfully', 'success')
        else:
            flash('No changes to save', 'info')
    else:
        flash('No song order provided', 'error')
        
    return redirect(url_for('rounds.round_detail', round_id=round_id))


@rounds_bp.route('/<int:round_id>/review', methods=['POST'])
@login_required
def update_round_review(round_id):
    """Update human review state for a round."""
    rnd = _get_editable_round_or_404(round_id)
    status = (request.form.get('review_status') or '').strip().lower()
    notes = (request.form.get('review_notes') or '').strip() or None
    if status not in {'draft', 'reviewed', 'approved', 'rejected'}:
        return _automation_error_response(AutomationError('Invalid review status.'), 400)

    rnd.review_status = status
    rnd.review_notes = notes
    if status == 'approved':
        rnd.approved_at = datetime.utcnow()
        rnd.approved_by_id = current_user.id
    else:
        rnd.approved_at = None
        rnd.approved_by_id = None
    rnd.updated_at = datetime.utcnow()
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'review_status': rnd.review_status,
            'approved_at': rnd.approved_at.isoformat() if rnd.approved_at else None,
        })
    flash('Round review status updated', 'success')
    return redirect(url_for('rounds.round_detail', round_id=round_id))


@rounds_bp.route('/<int:round_id>/quality', methods=['GET'])
@login_required
def round_quality(round_id):
    """Return package quality and repair guidance for a round."""
    _get_visible_round_or_404(round_id)
    try:
        result = automation.round_repair_report(
            round_id=round_id,
            user_id=current_user.id,
            expected_song_count=_int_arg('expected_song_count', default=8, minimum=1, maximum=25),
            min_preview_seconds=float(request.args.get('min_preview_seconds', 20.0)),
            max_preview_seconds=float(request.args.get('max_preview_seconds', 35.0)),
            duration_tolerance_seconds=float(
                request.args.get(
                    'duration_tolerance_seconds',
                    automation.DEFAULT_MP3_DURATION_TOLERANCE_SECONDS,
                )
            ),
        )
    except ValueError:
        return _automation_error_response(AutomationError('Quality parameter values must be numeric.'), 400)
    except AutomationError as exc:
        return _automation_error_response(exc, 400)
    return jsonify({'success': True, **result})


@rounds_bp.route('/<int:round_id>/replacement-suggestions', methods=['GET'])
@login_required
def replacement_suggestions(round_id):
    """Return replacement candidates for one round position."""
    _get_visible_round_or_404(round_id)
    position = _int_arg('position', default=None, minimum=1, maximum=25)
    if position is None:
        return _automation_error_response(AutomationError('position is required.'), 400)
    try:
        result = automation.suggest_replacement_songs(
            round_id=round_id,
            position=position,
            limit=_int_arg('limit', default=8, minimum=1, maximum=25),
            query=request.args.get('query') or None,
            require_deezer_id=_bool_form_value('require_deezer_id', True),
            verify_previews=False,
        )
    except AutomationError as exc:
        return _automation_error_response(exc, 400)
    return jsonify({'success': True, **result})


@rounds_bp.route('/<int:round_id>/replace-song', methods=['POST'])
@login_required
def replace_round_song(round_id):
    """Replace one song in a round from a reviewed suggestion."""
    _get_editable_round_or_404(round_id)
    position = request.form.get('position')
    replacement_song_id = request.form.get('replacement_song_id')
    try:
        result = automation.replace_round_song(
            round_id=round_id,
            position=int(position),
            replacement_song_id=int(replacement_song_id),
            inspect_after=_bool_form_value('inspect_after', False),
            user_id=current_user.id,
        )
    except (TypeError, ValueError):
        return _automation_error_response(
            AutomationError('position and replacement_song_id are required integers.'),
            400,
        )
    except AutomationError as exc:
        return _automation_error_response(exc, 400)
    return jsonify({'success': True, **result})


@rounds_bp.route('/<int:round_id>/draft-audio-scripts', methods=['POST'])
@login_required
def draft_audio_scripts(round_id):
    """Draft and persist intro/replay/outro scripts for review."""
    _get_editable_round_or_404(round_id)
    try:
        automation.draft_round_audio_scripts(
            round_id=round_id,
            user_id=current_user.id,
            quiz_date=request.form.get('quiz_date') or None,
            theme=request.form.get('theme') or None,
            tone=request.form.get('tone') or 'warm, concise, lightly humorous',
            persist=True,
        )
    except AutomationError as exc:
        flash(str(exc), 'error')
    else:
        flash('Audio script drafts created', 'success')
    return redirect(url_for('rounds.round_detail', round_id=round_id))


@rounds_bp.route('/<int:round_id>/draft-track-hints', methods=['POST'])
@login_required
def draft_track_hints(round_id):
    """Draft and persist per-track hint scripts for review."""
    _get_editable_round_or_404(round_id)
    try:
        automation.draft_round_track_hints(
            round_id=round_id,
            user_id=current_user.id,
            tone=request.form.get('tone') or 'concise, playful, no title or artist spoilers',
            persist=True,
        )
    except AutomationError as exc:
        flash(str(exc), 'error')
    else:
        flash('Track hint drafts created', 'success')
    return redirect(url_for('rounds.round_detail', round_id=round_id))


@rounds_bp.route('/<int:round_id>/audio-scripts/<int:script_id>', methods=['POST'])
@login_required
def update_audio_script(round_id, script_id):
    """Review or edit one stored audio script."""
    _get_editable_round_or_404(round_id)
    script = RoundAudioScript.query.filter_by(id=script_id, round_id=round_id).first_or_404()
    try:
        automation.update_round_audio_script(
            script.id,
            text=request.form.get('text'),
            status=request.form.get('status') or None,
            selected=_bool_form_value('selected', False),
        )
    except AutomationError as exc:
        flash(str(exc), 'error')
    else:
        flash('Audio script updated', 'success')
    return redirect(url_for('rounds.round_detail', round_id=round_id))

@rounds_bp.route('/round/<int:round_id>/mp3', methods=['POST'])
@login_required
def round_mp3(round_id):
    """Generates an MP3 file for a given round with intro, outro, and number announcements."""
    from musicround.helpers.utils import get_mp3_path
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # For AJAX requests, keep the response consistent
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401

    round = _get_editable_round_or_404(round_id)
    song_ids = round.song_id_list
    if not song_ids:
        error_msg = 'Round contains no songs. Please add songs before generating an MP3.'
        current_app.logger.warning(error_msg)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))

    storage = check_round_artifact_storage(include_mp3=True, include_pdf=False)
    if not storage['ok']:
        return _storage_failure_response(round_id, storage)
    
    # Create a dict mapping song_id to Song object for all songs in the round
    songs_dict = {song.id: song for song in Song.query.filter(Song.id.in_(song_ids)).all()}
    
    # Preserve the exact ordering from the round.songs field
    songs = [songs_dict.get(song_id) for song_id in song_ids if songs_dict.get(song_id)]

    # Create a directory for rounds in /data if it doesn't exist
    rounds_dir = round_mp3_dir()

    # Define the path for the MP3 file
    mp3_file_path = os.path.join(rounds_dir, f'round_{round_id}.mp3')
    current_app.logger.info(f"Checking MP3 generation status for round {round_id}")
    force_regenerate = _bool_form_value('force', False)

    # Reuse the existing MP3 unless the caller explicitly requested regeneration.
    if not force_regenerate and round.mp3_generated and os.path.exists(mp3_file_path):
        current_app.logger.info(f"MP3 file already exists and is up to date at: {mp3_file_path}")
        download_url = url_for('rounds.download_mp3', round_id=round_id)
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True, 
                'message': 'MP3 file already exists',
                'mp3_status': 'exists',
                'download_url': download_url
            })
        else:
            # Traditional form submission, send file
            return send_file(mp3_file_path, as_attachment=True)

    # Load intro, outro, and replay audio segments - using user's custom ones if available
    try:
        # Use get_mp3_path helper to get the appropriate path for each MP3 type
        intro_path = get_mp3_path(current_user, 'intro')
        outro_path = get_mp3_path(current_user, 'outro')
        replay_path = get_mp3_path(current_user, 'replay')
        
        intro = AudioSegment.from_mp3(intro_path)
        outro = AudioSegment.from_mp3(outro_path)
        replay = AudioSegment.from_mp3(replay_path)
        
        current_app.logger.info(f"Using MP3 files - Intro: {intro_path}, Outro: {outro_path}, Replay: {replay_path}")
    except Exception as e:
        return _round_generation_failure_response(
            round_id,
            f"Error loading intro/outro/replay audio: {e}",
            ROUND_MP3_BASE_AUDIO_ERROR,
        )

    # Create an empty audio segment
    combined_audio = AudioSegment.empty()
    combined_audio += intro

    # Create temporary directory for number announcements and song previews
    with tempfile.TemporaryDirectory() as temp_dir:
        # Store song audio segments for later replay
        song_segments = []
        number_segments = []
        hint_segments = _selected_track_hint_audio(round_id)

        # First pass - append each song's preview with number announcements
        for i, song in enumerate(songs):
            number_audio_path = os.path.join(current_app.root_path, 'static', 'audio', f'{i+1}.mp3')
            try:
                number_audio = AudioSegment.from_mp3(number_audio_path)
                number_segments.append(number_audio)
            except Exception as e:
                return _round_generation_failure_response(
                    round_id,
                    f"Error loading number audio {i+1}: {e}",
                    ROUND_MP3_NUMBER_AUDIO_ERROR,
                )

            if song.deezer_id:
                try:
                    # Fetch fresh preview URL from Deezer API
                    deezer_client = current_app.config['deezer']
                    track = deezer_client.get_track(song.deezer_id)
                    current_app.logger.info(f"Deezer track info: {track}")  # Log the track info
                    preview_url = track.get('preview')
                    if not preview_url:
                        current_app.logger.warning(f"No preview available for {song.title} (Deezer ID: {song.deezer_id})")
                        song_segments.append(None)
                        continue

                    # Download the song preview to a temporary file
                    response = requests.get(preview_url, stream=True)
                    response.raise_for_status()  # Raise an exception for bad status codes

                    temp_song_path = os.path.join(temp_dir, f'song_{song.id}.mp3')
                    with open(temp_song_path, 'wb') as temp_song_file:
                        for chunk in response.iter_content(chunk_size=8192):
                            temp_song_file.write(chunk)

                    song_audio = AudioSegment.from_mp3(temp_song_path)
                    song_segments.append(song_audio)
                    
                    # Add to the combined audio for first playthrough
                    combined_audio += number_audio
                    if i + 1 in hint_segments:
                        combined_audio += hint_segments[i + 1]
                    combined_audio += song_audio
                except requests.exceptions.RequestException as e:
                    return _round_generation_failure_response(
                        round_id,
                        f"Error downloading {song.title} (Deezer ID: {song.deezer_id}): {e}",
                        ROUND_MP3_PREVIEW_DOWNLOAD_ERROR,
                    )
                except Exception as e:
                    return _round_generation_failure_response(
                        round_id,
                        f"Error processing {song.title} (Deezer ID: {song.deezer_id}): {e}",
                        ROUND_MP3_PREVIEW_PROCESSING_ERROR,
                    )
            else:
                current_app.logger.warning(f"No Deezer ID available for {song.title}")
                song_segments.append(None)

        # Add the replay announcement
        combined_audio += replay
        
        # Second pass - replay all songs
        for i, (song_audio, number_audio) in enumerate(zip(song_segments, number_segments)):
            if song_audio is not None:
                combined_audio += number_audio
                combined_audio += song_audio

        combined_audio += outro

        # Export the combined audio to an MP3 file
        try:
            combined_audio.export(mp3_file_path, format="mp3")
            current_app.logger.info(f"MP3 file successfully generated at: {mp3_file_path}")
            
            # Update the round object to indicate MP3 has been generated and update timestamp
            round.mp3_generated = True
            round.last_generated_at = datetime.utcnow()
            db.session.commit()
            
            # Check if this is an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                download_url = url_for('rounds.download_mp3', round_id=round_id)
                return jsonify({
                    'success': True,
                    'message': 'MP3 file successfully regenerated' if force_regenerate else 'MP3 file successfully generated',
                    'mp3_status': 'regenerated' if force_regenerate else 'generated',
                    'download_url': download_url
                })
            else:
                # Traditional form submission, send file
                flash('MP3 regenerated successfully' if force_regenerate else 'MP3 generated successfully', 'success')
                return send_file(mp3_file_path, as_attachment=True)
            
        except Exception as e:
            return _round_generation_failure_response(
                round_id,
                f"Error generating MP3 file: {e}",
                ROUND_MP3_EXPORT_ERROR,
            )

@rounds_bp.route('/download/mp3/round_<int:round_id>', methods=['GET'])
@login_required
def download_mp3(round_id):
    """Download an MP3 file for a round"""
    _get_visible_round_or_404(round_id)
    mp3_file_path = os.path.join(round_mp3_dir(), f'round_{round_id}.mp3')
    
    if not os.path.exists(mp3_file_path):
        flash('MP3 file not found. Please generate the MP3 first.', 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))
        
    return send_file(mp3_file_path, as_attachment=True)

@rounds_bp.route('/download/pdf/round_<int:round_id>', methods=['GET'])
@login_required
def download_pdf(round_id):
    """Download a PDF file for a round"""
    _get_visible_round_or_404(round_id)
    pdf_file_path = os.path.join(round_pdf_dir(), f'round_{round_id}.pdf')
    
    if not os.path.exists(pdf_file_path):
        flash('PDF file not found. Please generate the PDF first.', 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))
        
    return send_file(pdf_file_path, as_attachment=True)

def generate_pdf(round_id):
    """
    Creates a stylish PDF "round_{id}.pdf" that lists the songs in that round.
    Returns raw PDF data as bytes, for sending or saving.
    """
    rnd = Round.query.get(round_id)
    if not rnd:
        return 'Round not found'

    file_name = f'round_{round_id}.pdf'
    dir_path = round_pdf_dir()
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    file_path = os.path.join(dir_path, file_name)

    # If it exists and the flag indicates it's up-to-date, read from disk
    if os.path.exists(file_path) and rnd.pdf_generated:
        with open(file_path, 'rb') as file:
            return file.read()

    # Get songs data in the correct order
    song_ids = rnd.song_id_list
    if not song_ids:
        return 'Round contains no songs'
    
    # Create a dict mapping song_id to Song object for all songs in the round
    songs_dict = {song.id: song for song in Song.query.filter(Song.id.in_(song_ids)).all()}
    
    # Preserve the exact ordering from the round.songs field
    songs = [songs_dict.get(song_id) for song_id in song_ids if songs_dict.get(song_id)]
    
    # Import reportlab components
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, cm
    
    # Create a buffer
    buffer = BytesIO()
    
    # Set up the PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5*cm,
        rightMargin=1.5*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Create custom styles
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#00ACC1'),  # Teal color for titles
        spaceAfter=24,
        alignment=1  # Center alignment
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#333333'),
        spaceBefore=12,
        spaceAfter=12
    )
    
    info_style = ParagraphStyle(
        'Info',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#666666'),
        spaceBefore=6,
        spaceAfter=12
    )
    
    song_style = ParagraphStyle(
        'Song',
        parent=styles['Normal'],
        fontSize=14,
        spaceBefore=4,
        spaceAfter=4
    )
    
    # Story (container for PDF elements)
    story = []
    
    # Add logo
    logo_path = os.path.join(current_app.root_path, 'static', 'img', 'light', 'logotype.png')
    if os.path.exists(logo_path):
        img = Image(logo_path)
        img.drawHeight = 1.2*cm
        img._restrictSize(5*cm, 5*cm)
        img.hAlign = 'CENTER'
        story.append(img)
        story.append(Spacer(1, 0.5*cm))
    
    # Add title
    title = "Music Quiz Round"
    if rnd.name:
        title = rnd.name
        
    story.append(Paragraph(title, title_style))
    
    # Add subtitle with round type
    round_type_text = f"Round Type: {rnd.round_type}"
    if rnd.round_criteria_used:
        round_type_text += f" - {rnd.round_criteria_used}"
    
    story.append(Paragraph(round_type_text, subtitle_style))
    
    # Add date info
    current_date = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(f"Generated on {current_date}", info_style))
    
    # Add divider
    story.append(Spacer(1, 0.75*cm))
    
    # Create song table data
    data = [["#", "Artist", "Title", "Year", "Genre"]]
    
    for i, song in enumerate(songs):
        if song:
            data.append([
                f"{i+1}",
                f"{song.artist}",  # Artist in separate column
                f"{song.title}",   # Title in separate column
                f"{song.year or ''}", 
                f"{song.genre or ''}"
            ])
    
    # Create and style the table
    table = Table(data, colWidths=[0.7*cm, 6*cm, 6*cm, 2*cm, 2.5*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00ACC1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),     # Center the song numbers
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),     # Center the years
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),  # Make numbers bold
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica-Bold'),  # Make artist names bold
        # Zebra striping for rows
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    
    # Add alternating row colors
    for i in range(1, len(data)):
        if i % 2 == 0:
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F9FAFB'))
            ]))
    
    story.append(table)
    
    # Add spacer
    story.append(Spacer(1, 0.75*cm))
    
    # Add footer
    footer_text = "Quizzical Beats - Music Quiz Generator"
    story.append(Paragraph(footer_text, info_style))
    
    # Build PDF
    doc.build(story)
    
    # Get the value from the buffer
    buffer.seek(0)
    
    # Save to file
    with open(file_path, 'wb') as file:
        file.write(buffer.getvalue())
    
    return buffer.getvalue()

@rounds_bp.route('/<int:round_id>/pdf', methods=['POST'])
@login_required
def round_pdf(round_id):
    """Generate a PDF file for a round"""
    rnd = db.session.get(Round, round_id)
    if not rnd:
        return jsonify({'success': False, 'error': 'Round not found'})
    if not rnd.song_id_list:
        return jsonify({
            'success': False,
            'error': 'Round contains no songs',
        }), 400
    
    # Define path for the PDF file
    storage = check_round_artifact_storage(include_mp3=False, include_pdf=True)
    if not storage['ok']:
        return _storage_failure_response(round_id, storage)

    pdfs_dir = round_pdf_dir()
    pdf_file_path = os.path.join(pdfs_dir, f'round_{rnd.id}.pdf')
    
    # Check if the PDF has already been generated and if the file exists
    # We'll generate a new file if either the flag is False or the file doesn't exist
    if rnd.pdf_generated and os.path.exists(pdf_file_path):
        current_app.logger.info(f"PDF file already exists and is up to date at: {pdf_file_path}")
        download_url = url_for('rounds.download_pdf', round_id=round_id)
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True, 
                'message': 'PDF file already exists', 
                'download_url': download_url
            })
        else:
            # Traditional form submission, send file
            return send_file(pdf_file_path, as_attachment=True)
    
    try:
        pdf_data = generate_pdf(round_id)
        if isinstance(pdf_data, str):
            return jsonify({'success': False, 'error': pdf_data}), 400

        with open(pdf_file_path, 'wb') as f:
            f.write(pdf_data)
        
        # Update the round object to indicate PDF has been generated and update timestamp
        rnd.pdf_generated = True
        rnd.last_generated_at = datetime.utcnow()
        db.session.commit()
            
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            download_url = url_for('rounds.download_pdf', round_id=round_id)
            return jsonify({
                'success': True, 
                'message': 'PDF file successfully generated',
                'download_url': download_url
            })
        else:
            # Traditional form submission, send the file
            return send_file(pdf_file_path, as_attachment=True)
            
    except Exception as e:
        return _round_generation_failure_response(
            round_id,
            f"Error generating PDF file: {e}",
            ROUND_PDF_GENERATION_ERROR,
        )

@rounds_bp.route('/<int:round_id>/mail', methods=['POST'])
@login_required
def send_email(round_id):
    """
    Generate PDF + MP3, attach them to an email, and send via configured SMTP.
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # For AJAX requests, keep the response consistent
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
    
    # Check if the round exists
    rnd = _get_editable_round_or_404(round_id)

    storage = check_round_artifact_storage(include_mp3=True, include_pdf=True)
    if not storage['ok']:
        return _storage_failure_response(round_id, storage)
    
    # Generate PDF
    pdf_data = generate_pdf(round_id)
    if isinstance(pdf_data, str):
        error_msg = pdf_data
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        if pdf_data.startswith('Round not found'):
            flash(error_msg, 'error')
            return redirect(url_for('rounds.rounds_list'))
        flash(error_msg, 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))
    
    # Define the path for the MP3 file
    mp3_file_path = os.path.join(round_mp3_dir(), f'round_{round_id}.mp3')
    
    # Regenerate if the database marks the asset stale or the file is missing.
    if not rnd.mp3_generated or not os.path.exists(mp3_file_path):
        response = round_mp3(round_id)

        response_obj = response
        status_code = getattr(response, 'status_code', 200)
        if isinstance(response, tuple):
            response_obj = response[0]
            if len(response) > 1 and isinstance(response[1], int):
                status_code = response[1]
            else:
                status_code = getattr(response_obj, 'status_code', 200)
        if status_code >= 400 or not os.path.exists(mp3_file_path):
            error_msg = "MP3 generation failed. Please resolve the round audio issues before sending email."
            try:
                response_json = response_obj.get_json(silent=True)
            except Exception:
                response_json = None
            if response_json and response_json.get('error'):
                error_msg = response_json['error']
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg})
            else:
                flash(error_msg, 'error')
                return redirect(url_for('rounds.round_detail', round_id=round_id))
        db.session.refresh(rnd)
        if not rnd.mp3_generated:
            error_msg = "MP3 generation failed. Please resolve the round audio issues before sending email."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg})
            flash(error_msg, 'error')
            return redirect(url_for('rounds.round_detail', round_id=round_id))
    
    # Use the current user's email address as the recipient
    mail_recipient = current_user.email

    if not mail_recipient:
        error_msg = "You don't have an email address in your profile. Please update your profile with an email address."
        current_app.logger.error(error_msg)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        else:
            session['email_error'] = error_msg
            return redirect(url_for('rounds.round_detail', round_id=round_id))

    # Get the round name for the subject
    round_title = f'Pub Quiz Round #{round_id}'
    if rnd and rnd.name:
        round_title = rnd.name

    try:
        quality = automation.inspect_round_package(round_id=round_id, user_id=current_user.id)
    except Exception as exc:
        current_app.logger.error(
            "Round package inspection failed before email for round %s: %s",
            round_id,
            exc,
            exc_info=True,
        )
        error_msg = "Round quality gate could not run. Please try again later or contact an administrator."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': error_msg}), 500
        flash(error_msg, 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))
    if not quality.get('ok'):
        return _round_quality_failure_response(
            round_id,
            quality,
            recipient=mail_recipient,
            subject=round_title,
            body_text='Attached please find the MP3 and PDF files for the quiz round.',
        )

    try:
        with open(mp3_file_path, 'rb') as mp3_file:
            attachments = [
                {
                    'data': pdf_data,
                    'filename': f'round_{round_id}.pdf',
                    'mimetype': 'application/pdf',
                },
                {
                    'data': mp3_file.read(),
                    'filename': f'round_{round_id}.mp3',
                    'mimetype': 'audio/mpeg',
                },
            ]

        success, message = send_quiz_email(
            mail_recipient,
            round_title,
            'Attached please find the MP3 and PDF files for the quiz round.',
            attachments,
        )
        if not success:
            raise RuntimeError(message)

        success_msg = message
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': success_msg})
        else:
            flash(success_msg, 'success')
            return redirect(url_for('rounds.round_detail', round_id=round_id))
            
    except Exception as e:
        current_app.logger.error(f"Email send error: {e}")
        error_msg = "Unable to send the email. Please try again later or contact an administrator."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        else:
            session['email_error'] = error_msg
            return redirect(url_for('rounds.round_detail', round_id=round_id))

@rounds_bp.route('/<int:round_id>/delete', methods=['POST'])
@login_required
def delete_round(round_id):
    """Delete a round and its associated files"""
    rnd = _get_editable_round_or_404(round_id)
    
    try:
        # Delete associated MP3 file if it exists
        mp3_file_path = os.path.join(round_mp3_dir(), f'round_{round_id}.mp3')
        if os.path.exists(mp3_file_path):
            os.remove(mp3_file_path)
            
        # Delete associated PDF file if it exists
        pdf_file_path = os.path.join(round_pdf_dir(), f'round_{round_id}.pdf')
        if os.path.exists(pdf_file_path):
            os.remove(pdf_file_path)
        
        # Delete the round from the database
        db.session.delete(rnd)
        db.session.commit()
        
        flash('Round deleted successfully', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting round {round_id}: {e}", exc_info=True)
        error_msg = "Unable to delete the round. Please try again later or contact an administrator."
        flash(error_msg, 'error')
        return jsonify({'success': False, 'error': error_msg}), 500

@rounds_bp.route('/<int:round_id>/export-to-dropbox', methods=['POST'])
@login_required
def export_to_dropbox(round_id):
    """
    Export a round to the user's Dropbox account, including metadata and optionally MP3 files
    """
    current_app.logger.info(f"Starting Dropbox export for round ID {round_id} by user {current_user.username}")
    round_obj = _get_visible_round_or_404(round_id)
    
    # Properly parse boolean parameters from form data
    include_mp3s = request.form.get('include_mp3s', 'true').lower() == 'true'
    include_pdf = request.form.get('include_pdf', 'true').lower() == 'true'
    custom_folder = request.form.get('custom_folder', '')

    storage = check_round_artifact_storage(include_mp3=include_mp3s, include_pdf=include_pdf)
    if not storage['ok']:
        return _storage_failure_response(round_id, storage)
    
    current_app.logger.debug(f"Export options - Include MP3: {include_mp3s}, Include PDF: {include_pdf}, Custom folder: '{custom_folder}'")
    
    # Default response format
    response_data = {
        'success': False,
        'message': 'Unknown error occurred',
        'shared_links': {
            'mp3': None,
            'pdf': None,
            'text': None  # For metadata JSON
        }
    }
    
    # Validate user has Dropbox connected
    if not current_user.dropbox_token or not current_user.dropbox_refresh_token:
        current_app.logger.error(f"User {current_user.username} attempted Dropbox export without connected account")
        response_data['message'] = 'You need to connect your Dropbox account first'
        flash('Please connect your Dropbox account in your profile settings first.', 'error')
        return jsonify(response_data)
    
    current_app.logger.debug(f"Dropbox token exists: {bool(current_user.dropbox_token)}, token expiry: {current_user.dropbox_token_expiry}")
    
    # Refresh token if needed
    from musicround.helpers.dropbox_helper import refresh_dropbox_token_if_needed
    token_refresh = refresh_dropbox_token_if_needed(current_user)
    current_app.logger.info(f"Token refresh result: {token_refresh}")
    
    if not token_refresh['success']:
        current_app.logger.error(f"Failed to refresh Dropbox token: {token_refresh['message']}")
        response_data['message'] = f"Error with Dropbox authentication: {token_refresh['message']}"
        flash('There was an error with your Dropbox connection. Please reconnect in your profile.', 'error')
        return jsonify(response_data)
    
    # Initialize the round export record
    from musicround.models import RoundExport, db
    round_export = RoundExport(
        round_id=round_id,
        user_id=current_user.id,
        export_type='dropbox',
        include_mp3s=include_mp3s,
        status='in_progress',
        destination=current_user.dropbox_export_path
    )
    db.session.add(round_export)
    db.session.commit()
    current_app.logger.debug(f"Created export record with ID: {round_export.id}")
    
    try:
        # Determine base export path
        base_folder = current_user.dropbox_export_path or '/QuizzicalBeats'
        if custom_folder:
            base_folder = os.path.join(base_folder, custom_folder.strip('/'))
        
        current_app.logger.debug(f"Using base folder: {base_folder}")
        
        # Create a folder for this round
        round_folder_name = f"Round_{round_id}"
        if round_obj.name:
            # Sanitize round name for folder name (remove invalid characters)
            safe_name = re.sub(r'[<>:"/\\|?*]', '', round_obj.name)
            round_folder_name = f"Round_{round_id}_{safe_name}"
        
        round_folder = os.path.join(base_folder, round_folder_name)
        metadata_folder = os.path.join(round_folder, "Metadata")
        
        current_app.logger.debug(f"Round folder path: {round_folder}")
        current_app.logger.debug(f"Metadata folder path: {metadata_folder}")
        
        # Access token for Dropbox API calls
        access_token = current_user.dropbox_token
        current_app.logger.debug("Dropbox access token present for export: %s", bool(access_token))
        
        # Prepare song list - check if the helper method works
        try:
            songs = round_obj.song_list
            current_app.logger.debug(f"Successfully retrieved {len(songs)} songs")
        except Exception as song_err:
            current_app.logger.error(f"Error getting song list: {str(song_err)}")
            # Fallback method to get songs
            song_ids = round_obj.song_id_list
            songs_by_id = {
                song.id: song
                for song in Song.query.filter(Song.id.in_(song_ids)).all()
            }
            songs = [
                songs_by_id[song_id]
                for song_id in song_ids
                if song_id in songs_by_id
            ]
            current_app.logger.debug(f"Fallback method retrieved {len(songs)} songs")

        if not songs:
            raise Exception('Round contains no songs')
        
        # 1. Export song metadata as JSON
        song_data = []
        for song in songs:
            try:
                song_dict = song.to_dict()
                song_data.append(song_dict)
            except Exception as e:
                current_app.logger.error(f"Error converting song {song.id} to dict: {str(e)}")
                # Manual conversion fallback
                song_data.append({
                    'id': song.id,
                    'title': song.title,
                    'artist': song.artist,
                    'year': song.year,
                    'deezer_id': song.deezer_id,
                    'spotify_id': song.spotify_id,
                })
        
        metadata_json = json.dumps({
            'round_id': round_obj.id,
            'round_name': round_obj.name,
            'round_type': round_obj.round_type,
            'round_criteria': round_obj.round_criteria_used,
            'created_at': round_obj.created_at.isoformat() if round_obj.created_at else None,
            'songs': song_data
        }, indent=2)
        
        current_app.logger.debug(f"Created metadata JSON ({len(metadata_json)} bytes)")
        
        # Upload metadata JSON
        from musicround.helpers.dropbox_helper import upload_to_dropbox, create_shared_link
        
        json_path = f"{metadata_folder}/round_{round_id}_metadata.json"
        current_app.logger.info(f"Uploading JSON metadata to {json_path}")
        
        json_upload = upload_to_dropbox(
            access_token, 
            json_path, 
            metadata_json, 
            mode='text'
        )
        
        current_app.logger.debug(f"JSON upload result: {json_upload}")
        
        if not json_upload['success']:
            current_app.logger.error(f"Error uploading JSON metadata: {json_upload}")
            raise Exception(f"Error uploading JSON metadata: {json_upload['message']}")
        
        # Create shared link for JSON
        current_app.logger.info(f"Creating shared link for JSON at {json_path}")
        json_link = create_shared_link(access_token, json_path)
        current_app.logger.debug(f"JSON shared link result: {json_link}")
        
        if json_link['success']:
            response_data['shared_links']['text'] = json_link['url']
        
        # 2. Export PDF if requested
        if include_pdf:
            current_app.logger.info(f"PDF export requested for round {round_id}")
            
            # Generate PDF if not already generated
            if not round_obj.pdf_generated:
                current_app.logger.debug("PDF not generated yet, generating now")
                pdf_data = generate_pdf(round_id)
                if isinstance(pdf_data, str):
                    current_app.logger.error(f"Error generating PDF: {pdf_data}")
                    raise Exception(f"Error generating PDF: {pdf_data}")
            else:
                # PDF already exists, read it
                pdf_file_path = os.path.join(round_pdf_dir(), f'round_{round_id}.pdf')
                current_app.logger.debug(f"Reading existing PDF from {pdf_file_path}")
                
                if not os.path.exists(pdf_file_path):
                    current_app.logger.error(f"PDF file doesn't exist at {pdf_file_path} despite pdf_generated=True")
                    # Generate it anyway
                    pdf_data = generate_pdf(round_id)
                else:
                    with open(pdf_file_path, 'rb') as f:
                        pdf_data = f.read()
                    current_app.logger.debug(f"Read {len(pdf_data)} bytes from PDF file")
            
            # Upload PDF
            pdf_path = f"{round_folder}/round_{round_id}.pdf"
            current_app.logger.info(f"Uploading PDF to {pdf_path}")
            
            pdf_upload = upload_to_dropbox(
                access_token, 
                pdf_path, 
                pdf_data
            )
            
            current_app.logger.debug(f"PDF upload result: {pdf_upload}")
            
            if not pdf_upload['success']:
                current_app.logger.error(f"Error uploading PDF: {pdf_upload}")
                raise Exception(f"Error uploading PDF: {pdf_upload['message']}")
            
            # Create shared link for PDF
            current_app.logger.info(f"Creating shared link for PDF at {pdf_path}")
            pdf_link = create_shared_link(access_token, pdf_path)
            current_app.logger.debug(f"PDF shared link result: {pdf_link}")
            
            if pdf_link['success']:
                response_data['shared_links']['pdf'] = pdf_link['url']
        
        # 3. Export MP3 if requested
        if include_mp3s:
            current_app.logger.info(f"MP3 export requested for round {round_id}")
            
            # Check if MP3 exists, generate if not
            mp3_file_path = os.path.join(round_mp3_dir(), f'round_{round_id}.mp3')
            current_app.logger.debug(f"Checking for MP3 at {mp3_file_path}")
            current_app.logger.debug(f"MP3 generated flag: {round_obj.mp3_generated}")
            
            if not round_obj.mp3_generated or not os.path.exists(mp3_file_path):
                current_app.logger.warning(f"MP3 needs to be generated first. Generated flag: {round_obj.mp3_generated}, File exists: {os.path.exists(mp3_file_path)}")
                # Need to redirect to MP3 generation first
                response_data['success'] = False
                response_data['message'] = 'MP3 needs to be generated first'
                response_data['redirect'] = url_for('rounds.round_mp3', round_id=round_id)
                
                # Update export record
                round_export.status = 'pending_mp3'
                round_export.error_message = 'MP3 needs to be generated first'
                db.session.commit()
                
                return jsonify(response_data)
            
            # MP3 exists, upload it
            current_app.logger.debug(f"Reading MP3 file from {mp3_file_path}")
            with open(mp3_file_path, 'rb') as f:
                mp3_data = f.read()
            
            current_app.logger.debug(f"Read {len(mp3_data)} bytes from MP3 file")
            
            mp3_path = f"{round_folder}/round_{round_id}.mp3"
            current_app.logger.info(f"Uploading MP3 to {mp3_path}")
            
            mp3_upload = upload_to_dropbox(
                access_token, 
                mp3_path, 
                mp3_data
            )
            
            current_app.logger.debug(f"MP3 upload result: {mp3_upload}")
            
            if not mp3_upload['success']:
                current_app.logger.error(f"Error uploading MP3: {mp3_upload}")
                raise Exception(f"Error uploading MP3: {mp3_upload['message']}")
            
            # Create shared link for MP3
            current_app.logger.info(f"Creating shared link for MP3 at {mp3_path}")
            mp3_link = create_shared_link(access_token, mp3_path)
            current_app.logger.debug(f"MP3 shared link result: {mp3_link}")
            
            if mp3_link['success']:
                response_data['shared_links']['mp3'] = mp3_link['url']
        
        # Update export record as success
        round_export.status = 'success'
        db.session.commit()
        current_app.logger.info(f"Export to Dropbox completed successfully for round {round_id}")
        
        # Success response
        response_data['success'] = True
        response_data['message'] = 'Round exported to Dropbox successfully'
        
        return jsonify(response_data)
        
    except Exception as e:
        current_app.logger.error(
            f"Error exporting round {round_id} to Dropbox: {str(e)}",
            exc_info=True,
        )
        if str(e) == 'Round contains no songs':
            error_msg = 'Round contains no songs'
        else:
            error_msg = (
                "Round export to Dropbox failed. "
                "Please try again later or reconnect Dropbox."
            )
        
        # Update export record with error
        round_export.status = 'failed'
        round_export.error_message = error_msg
        db.session.commit()
        
        # Error response
        response_data['success'] = False
        response_data['message'] = error_msg
        
        return jsonify(response_data)

def safe_filename(filename):
    """Convert a string to a safe filename"""
    # Replace problematic characters
    safe_name = re.sub(r'[^\w\s-]', '', filename).strip().replace(' ', '_')
    return safe_name
