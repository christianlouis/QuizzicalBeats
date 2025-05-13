from flask import Blueprint, session, redirect, url_for, jsonify, request, current_app
import base64

process_bp = Blueprint('process', __name__, url_prefix='/process')

@process_bp.route('/base64', methods=['POST'])
def base64_encode_data():
    """
    Return base64-encoded string from data provided in request body.
    """
    if 'access_token' not in session:
        return redirect(url_for('users.login'))  # Assuming 'users.login' is the correct endpoint
    
    # Get binary data from request
    data = request.get_data()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    return jsonify({
        'encoded': base64.b64encode(data).decode('utf-8')
    })