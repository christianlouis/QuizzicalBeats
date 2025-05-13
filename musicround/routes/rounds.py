import os
import smtplib
import shutil
import base64
import tempfile
import requests
import logging
from datetime import datetime
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import re
import zipfile
import io
import json

from flask import Blueprint, session, redirect, request, render_template, url_for, current_app, send_file, jsonify, flash
from flask_login import current_user, login_required
from musicround.models import Round, Song, db
from pydub import AudioSegment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

rounds_bp = Blueprint('rounds', __name__, url_prefix='/rounds')

@rounds_bp.route('/')
@login_required
def rounds_list():
    """Display a list of all rounds"""
    rounds = Round.query.all()
    return render_template('rounds.html', rounds=rounds)

@rounds_bp.route('/<int:round_id>')
@login_required
def round_detail(round_id):
    """Display details of a specific round"""
    rnd = Round.query.get(round_id)
    sp = current_app.config['sp']
    
    if rnd:
        song_ids = rnd.songs.split(',')
        songs = Song.query.filter(Song.id.in_(song_ids)).all()
        
        # Ensure songs are in the same order as in the round's song list
        song_id_to_obj = {str(song.id): song for song in songs}
        ordered_songs = [song_id_to_obj.get(song_id) for song_id in song_ids if song_id in song_id_to_obj]
        
        email_error = session.pop('email_error', None)  # Retrieve and remove the error message from the session
        
        # For sp.current_user(), we need to ensure we have a valid token if needed for this view
        user_info = None
        try:
            if 'access_token' in session:  # Only try to get user info if we have a token
                user_info = sp.current_user()
        except:
            # If we can't get user info, continue without it
            current_app.logger.warning("Could not get Spotify user info")
        
        return render_template('round_detail.html', round=rnd, songs=ordered_songs, user_info=user_info, email_error=email_error)
    else:
        return 'Round not found'

@rounds_bp.route('/<int:round_id>/update-name', methods=['POST'])
@login_required
def update_round_name(round_id):
    """Update the name of a round"""
    rnd = Round.query.get_or_404(round_id)
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
    rnd = Round.query.get_or_404(round_id)
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

@rounds_bp.route('/round/<int:round_id>/mp3', methods=['POST'])
@login_required
def round_mp3(round_id):
    """Generates an MP3 file for a given round with intro, outro, and number announcements."""
    from musicround.helpers.utils import get_mp3_path
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # For AJAX requests, keep the response consistent
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401

    round = Round.query.get_or_404(round_id)
    song_ids = [int(song_id) for song_id in round.songs.split(',')]
    
    # Create a dict mapping song_id to Song object for all songs in the round
    songs_dict = {song.id: song for song in Song.query.filter(Song.id.in_(song_ids)).all()}
    
    # Preserve the exact ordering from the round.songs field
    songs = [songs_dict.get(song_id) for song_id in song_ids if songs_dict.get(song_id)]

    # Create a directory for rounds in /data if it doesn't exist
    rounds_dir = '/data/rounds'
    if not os.path.exists(rounds_dir):
        os.makedirs(rounds_dir)

    # Define the path for the MP3 file
    mp3_file_path = os.path.join(rounds_dir, f'round_{round_id}.mp3')
    current_app.logger.info(f"Checking MP3 generation status for round {round_id}")

    # Check if the MP3 has already been generated and if the file exists
    # We'll generate a new file if either the flag is False or the file doesn't exist
    if round.mp3_generated and os.path.exists(mp3_file_path):
        current_app.logger.info(f"MP3 file already exists and is up to date at: {mp3_file_path}")
        download_url = url_for('rounds.download_mp3', round_id=round_id)
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': True, 
                'message': 'MP3 file already exists', 
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
        error_msg = f"Error loading intro/outro/replay audio: {e}"
        current_app.logger.error(error_msg)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': error_msg})
        else:
            flash(error_msg, 'error')
            return redirect(url_for('rounds.round_detail', round_id=round_id))

    # Create an empty audio segment
    combined_audio = AudioSegment.empty()
    combined_audio += intro

    # Create temporary directory for number announcements and song previews
    with tempfile.TemporaryDirectory() as temp_dir:
        # Store song audio segments for later replay
        song_segments = []
        number_segments = []

        # First pass - append each song's preview with number announcements
        for i, song in enumerate(songs):
            number_audio_path = os.path.join(current_app.root_path, 'static', 'audio', f'{i+1}.mp3')
            try:
                number_audio = AudioSegment.from_mp3(number_audio_path)
                number_segments.append(number_audio)
            except Exception as e:
                error_msg = f"Error loading number audio {i+1}: {e}"
                current_app.logger.error(error_msg)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'error': error_msg})
                else:
                    flash(error_msg, 'error')
                    return redirect(url_for('rounds.round_detail', round_id=round_id))

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
                    combined_audio += song_audio
                except requests.exceptions.RequestException as e:
                    error_msg = f"Error downloading {song.title} (Deezer ID: {song.deezer_id}): {e}"
                    current_app.logger.error(error_msg)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'error': error_msg})
                    else:
                        flash(error_msg, 'error')
                        return redirect(url_for('rounds.round_detail', round_id=round_id))
                except Exception as e:
                    error_msg = f"Error processing {song.title} (Deezer ID: {song.deezer_id}): {e}"
                    current_app.logger.error(error_msg)
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'error': error_msg})
                    else:
                        flash(error_msg, 'error')
                        return redirect(url_for('rounds.round_detail', round_id=round_id))
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
                    'message': 'MP3 file successfully generated',
                    'download_url': download_url
                })
            else:
                # Traditional form submission, send file
                flash('MP3 generated successfully', 'success')
                return send_file(mp3_file_path, as_attachment=True)
            
        except Exception as e:
            error_msg = f"Error generating MP3 file: {e}"
            current_app.logger.error(error_msg)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': error_msg})
            else:
                flash(error_msg, 'error')
                return redirect(url_for('rounds.round_detail', round_id=round_id))

@rounds_bp.route('/download/mp3/round_<int:round_id>', methods=['GET'])
@login_required
def download_mp3(round_id):
    """Download an MP3 file for a round"""
    mp3_file_path = os.path.join('/data/rounds', f'round_{round_id}.mp3')
    
    if not os.path.exists(mp3_file_path):
        flash('MP3 file not found. Please generate the MP3 first.', 'error')
        return redirect(url_for('rounds.round_detail', round_id=round_id))
        
    return send_file(mp3_file_path, as_attachment=True)

@rounds_bp.route('/download/pdf/round_<int:round_id>', methods=['GET'])
@login_required
def download_pdf(round_id):
    """Download a PDF file for a round"""
    pdf_file_path = os.path.join('/data/pdfs', f'round_{round_id}.pdf')
    
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
    dir_path = '/data/pdfs'  # Use /data/pdfs for storing PDFs
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    file_path = os.path.join(dir_path, file_name)

    # If it exists and the flag indicates it's up-to-date, read from disk
    if os.path.exists(file_path) and rnd.pdf_generated:
        with open(file_path, 'rb') as file:
            return file.read()

    # Get songs data in the correct order
    song_ids = [int(sid) for sid in rnd.songs.split(',')]
    
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
    
    # Define path for the PDF file
    pdfs_dir = '/data/pdfs'
    if not os.path.exists(pdfs_dir):
        os.makedirs(pdfs_dir)
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
        if isinstance(pdf_data, str) and pdf_data.startswith('Round not found'):
            return jsonify({'success': False, 'error': pdf_data})

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
        error_msg = f"Error generating PDF file: {e}"
        current_app.logger.error(error_msg)
        return jsonify({'success': False, 'error': error_msg})

@rounds_bp.route('/<int:round_id>/mail', methods=['POST'])
@login_required
def send_email(round_id):
    """
    Generate PDF + MP3, attach them to an email, and send via Postmark.
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # For AJAX requests, keep the response consistent
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
    
    # Check if the round exists
    rnd = Round.query.get_or_404(round_id)
    
    # Generate PDF
    pdf_data = generate_pdf(round_id)
    if isinstance(pdf_data, str) and pdf_data.startswith('Round not found'):
        error_msg = 'Round not found'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        else:
            flash(error_msg, 'error')
            return redirect(url_for('rounds.rounds_list'))
    
    # Define the path for the MP3 file
    mp3_file_path = os.path.join('/data/rounds', f'round_{round_id}.mp3')
    
    # Check if MP3 exists, if not generate it
    if not os.path.exists(mp3_file_path):
        # Call the round_mp3 function but don't return its result yet
        # This will generate the MP3 file at mp3_file_path
        response = round_mp3(round_id)
        
        if isinstance(response, str) and response.startswith('Error'):
            error_msg = response
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': error_msg})
            else:
                flash(error_msg, 'error')
                return redirect(url_for('rounds.round_detail', round_id=round_id))

    # Get mail configuration from environment variables
    mail_host = current_app.config.get('MAIL_HOST')
    mail_port = current_app.config.get('MAIL_PORT')
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')
    mail_sender = current_app.config.get('MAIL_SENDER')
    
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
    
    # Check if all email configuration parameters are available
    missing_config = []
    if not mail_host:
        missing_config.append("MAIL_HOST")
    if not mail_port:
        missing_config.append("MAIL_PORT")
    if not mail_username:
        missing_config.append("MAIL_USERNAME")
    if not mail_password:
        missing_config.append("MAIL_PASSWORD")
    if not mail_sender:
        missing_config.append("MAIL_SENDER")
    
    if missing_config:
        missing_params = ", ".join(missing_config)
        error_msg = f"Email server configuration is incomplete. Missing parameters: {missing_params}. Please check your .env file."
        current_app.logger.error(f"Email configuration error: {error_msg}")
        current_app.logger.error(f"Current config values - MAIL_HOST: {'set' if mail_host else 'missing'}, "
                               f"MAIL_PORT: {'set' if mail_port else 'missing'}, "
                               f"MAIL_USERNAME: {'set' if mail_username else 'missing'}, "
                               f"MAIL_PASSWORD: {'set' if mail_password else 'missing'}, "
                               f"MAIL_SENDER: {'set' if mail_sender else 'missing'}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        else:
            session['email_error'] = error_msg  # Store the error message in the session
            return redirect(url_for('rounds.round_detail', round_id=round_id))

    msg = MIMEMultipart()
    msg['From'] = mail_sender
    msg['To'] = mail_recipient
    
    # Get the round name for the subject
    round_title = f'Pub Quiz Round #{round_id}'
    if rnd and rnd.name:
        round_title = rnd.name
    
    msg['Subject'] = round_title
    msg.attach(MIMEText('Attached please find the MP3 and PDF files for the quiz round.', 'plain'))

    # Attach PDF
    pdf_attachment = MIMEBase('application', 'pdf')
    pdf_attachment.set_payload(pdf_data)
    encoders.encode_base64(pdf_attachment)
    pdf_attachment.add_header('Content-Disposition', f'attachment; filename=round_{round_id}.pdf')
    msg.attach(pdf_attachment)

    # Attach MP3
    with open(mp3_file_path, 'rb') as mp3_file:
        mp3_data = mp3_file.read()
        mp3_attachment = MIMEBase('audio', 'mpeg')
        mp3_attachment.set_payload(mp3_data)
        encoders.encode_base64(mp3_attachment)
        mp3_attachment.add_header('Content-Disposition', f'attachment; filename=round_{round_id}.mp3')
        msg.attach(mp3_attachment)

    try:
        current_app.logger.info(f"Attempting to send email to {mail_recipient} via {mail_host}:{mail_port}")
        with smtplib.SMTP(mail_host, mail_port) as server:
            server.starttls()
            current_app.logger.debug("STARTTLS established")
            server.login(mail_username, mail_password)
            current_app.logger.debug(f"Login successful for {mail_username}")
            server.sendmail(mail_sender, mail_recipient, msg.as_string())
            current_app.logger.info(f"Email sent successfully from {mail_sender} to {mail_recipient}")
        
        success_msg = f'Email sent successfully to {mail_recipient}!'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': success_msg})
        else:
            flash(success_msg, 'success')
            return redirect(url_for('rounds.round_detail', round_id=round_id))
            
    except smtplib.SMTPException as e:
        error_msg = str(e)
        current_app.logger.error(f"SMTP Error: {error_msg}")
        current_app.logger.error(f"Failed to send email from {mail_sender} to {mail_recipient} via {mail_host}:{mail_port}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': error_msg})
        else:
            session['email_error'] = error_msg
            return redirect(url_for('rounds.round_detail', round_id=round_id))

@rounds_bp.route('/<int:round_id>/delete', methods=['POST'])
@login_required
def delete_round(round_id):
    """Delete a round and its associated files"""
    rnd = Round.query.get_or_404(round_id)
    
    try:
        # Delete associated MP3 file if it exists
        mp3_file_path = os.path.join('/data/rounds', f'round_{round_id}.mp3')
        if os.path.exists(mp3_file_path):
            os.remove(mp3_file_path)
            
        # Delete associated PDF file if it exists
        pdf_file_path = os.path.join('/data/pdfs', f'round_{round_id}.pdf')
        if os.path.exists(pdf_file_path):
            os.remove(pdf_file_path)
        
        # Delete the round from the database
        db.session.delete(rnd)
        db.session.commit()
        
        flash('Round deleted successfully', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting round: {e}")
        flash(f"Error deleting round: {e}", 'error')
        return jsonify({'success': False, 'error': str(e)}), 500

@rounds_bp.route('/<int:round_id>/export-to-dropbox', methods=['POST'])
@login_required
def export_to_dropbox(round_id):
    """
    Export a round to the user's Dropbox account, including metadata and optionally MP3 files
    """
    current_app.logger.info(f"Starting Dropbox export for round ID {round_id} by user {current_user.username}")
    round_obj = Round.query.get_or_404(round_id)
    
    # Properly parse boolean parameters from form data
    include_mp3s = request.form.get('include_mp3s', 'true').lower() == 'true'
    include_pdf = request.form.get('include_pdf', 'true').lower() == 'true'
    custom_folder = request.form.get('custom_folder', '')
    
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
        current_app.logger.debug(f"Access token (first 10 chars): {access_token[:10] if access_token else 'None'}")
        
        # Prepare song list - check if the helper method works
        try:
            songs = round_obj.song_list
            current_app.logger.debug(f"Successfully retrieved {len(songs)} songs")
        except Exception as song_err:
            current_app.logger.error(f"Error getting song list: {str(song_err)}")
            # Fallback method to get songs
            song_ids = [int(sid) for sid in round_obj.songs.split(',')]
            songs = Song.query.filter(Song.id.in_(song_ids)).all()
            current_app.logger.debug(f"Fallback method retrieved {len(songs)} songs")
        
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
                if isinstance(pdf_data, str) and pdf_data.startswith('Round not found'):
                    current_app.logger.error(f"Error generating PDF: {pdf_data}")
                    raise Exception(f"Error generating PDF: {pdf_data}")
            else:
                # PDF already exists, read it
                pdf_file_path = os.path.join('/data/pdfs', f'round_{round_id}.pdf')
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
            mp3_file_path = os.path.join('/data/rounds', f'round_{round_id}.mp3')
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
        current_app.logger.error(f"Error exporting round {round_id} to Dropbox: {str(e)}", exc_info=True)
        
        # Update export record with error
        round_export.status = 'failed'
        round_export.error_message = str(e)
        db.session.commit()
        
        # Error response
        response_data['success'] = False
        response_data['message'] = f"Error exporting to Dropbox: {str(e)}"
        
        return jsonify(response_data)

def generate_round_text(round_obj):
    """Generate a text representation of a round"""
    lines = [
        f"ROUND: {round_obj.title}",
        f"Created: {round_obj.created_at.strftime('%Y-%m-%d')}",
        f"Creator: {round_obj.user.username if round_obj.user else 'Unknown'}",
        "",
        f"Description: {round_obj.description or 'No description'}",
        "",
        "SONGS:",
        ""
    ]
    
    for idx, song in enumerate(round_obj.songs, 1):
        lines.append(f"{idx}. {song.title} - {song.artist}")
        if song.year:
            lines.append(f"   Year: {song.year}")
        if song.album:
            lines.append(f"   Album: {song.album}")
        lines.append("")
    
    return "\n".join(lines)

def generate_round_pdf(round_obj):
    """Generate a PDF representation of a round"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from io import BytesIO
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        
        # Create custom styles
        styles.add(ParagraphStyle(
            name='Title',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=12
        ))
        
        styles.add(ParagraphStyle(
            name='SongTitle',
            parent=styles['Normal'],
            fontSize=12,
            fontName='Helvetica-Bold'
        ))
        
        # Build the document content
        content = []
        
        # Round title
        content.append(Paragraph(f"Round: {round_obj.title}", styles['Title']))
        content.append(Spacer(1, 12))
        
        # Round info
        content.append(Paragraph(f"Created: {round_obj.created_at.strftime('%Y-%m-%d')}", styles['Normal']))
        content.append(Paragraph(f"Creator: {round_obj.user.username if round_obj.user else 'Unknown'}", styles['Normal']))
        content.append(Spacer(1, 12))
        
        # Description
        if round_obj.description:
            content.append(Paragraph("Description:", styles['Heading3']))
            content.append(Paragraph(round_obj.description, styles['Normal']))
            content.append(Spacer(1, 12))
        
        # Songs
        content.append(Paragraph("Songs:", styles['Heading3']))
        content.append(Spacer(1, 6))
        
        for idx, song in enumerate(round_obj.songs, 1):
            content.append(Paragraph(f"{idx}. {song.title} - {song.artist}", styles['SongTitle']))
            
            # Song details
            details = []
            if song.year:
                details.append(f"Year: {song.year}")
            if song.album:
                details.append(f"Album: {song.album}")
                
            if details:
                content.append(Paragraph(", ".join(details), styles['Normal']))
            
            content.append(Spacer(1, 6))
        
        # Build and return the PDF
        doc.build(content)
        pdf_data = buffer.getvalue()
        buffer.close()
        return pdf_data
        
    except ImportError:
        current_app.logger.warning("ReportLab not installed, skipping PDF export")
        return None
    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {str(e)}")
        return None

def safe_filename(filename):
    """Convert a string to a safe filename"""
    # Replace problematic characters
    safe_name = re.sub(r'[^\w\s-]', '', filename).strip().replace(' ', '_')
    return safe_name