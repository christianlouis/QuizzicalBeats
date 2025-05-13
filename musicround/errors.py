import traceback
from flask import render_template, session, request, current_app, jsonify
from flask_wtf.csrf import CSRFError
from flask_login import current_user
import json
import openai

# Import the csrf instance from the package
from musicround import csrf

def generate_friendly_error_message(error_info, app=None):
    """
    Generate a user-friendly error message using OpenAI
    
    Args:
        error_info (dict): Information about the error
        app: Flask application instance
    
    Returns:
        str: User-friendly error message or None if generation fails
    """
    if not app:
        app = current_app
    
    try:
        # Get OpenAI API details
        openai_api_key = app.config.get('OPENAI_API_KEY')
        openai_url = app.config.get('OPENAI_URL')
        openai_model = app.config.get('OPENAI_MODEL')
        
        if not openai_api_key or not openai_model:
            app.logger.warning("OpenAI credentials not configured for error messages")
            return None
        
        # Configure OpenAI API
        openai.api_key = openai_api_key
        if openai_url:
            if hasattr(openai, 'base_url'):  # New OpenAI API client (>= 1.0.0)
                openai.base_url = openai_url
            else:  # Old OpenAI API client (< 1.0.0)
                openai.api_base = openai_url
        
        # Create a meaningful prompt with the error information
        prompt = f"""
        Generate a user-friendly, helpful explanation for this technical error:
        Error Type: {error_info.get('error_type', 'Unknown Error')}
        Error Message: {error_info.get('error_message', 'No specific message available')}
        Error Code: {error_info.get('code', 'Unknown')}
        
        The explanation should:
        1. Be written in simple, non-technical language
        2. Explain what might have happened
        3. Suggest possible solutions or next steps
        4. Be concise (max 2-3 sentences)
        5. Be friendly and reassuring
        
        Return just the friendly explanation without any additional text.
        """
        
        app.logger.info(f"Requesting friendly error message from OpenAI")
        content = None
        
        # Call OpenAI based on library version
        if hasattr(openai, 'chat') and hasattr(openai.chat, 'completions'):
            # New OpenAI API client (>= 1.0.0)
            try:
                response = openai.chat.completions.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150,
                    temperature=0.7
                )
                
                if response and hasattr(response, 'choices') and response.choices:
                    content = response.choices[0].message.content
                    app.logger.info(f"Received friendly error message from OpenAI")
            except Exception as e:
                app.logger.error(f"OpenAI chat completions error: {e}")
        else:
            # Old OpenAI API client (< 1.0.0)
            try:
                response = openai.Completion.create(
                    engine=openai_model,
                    prompt=prompt,
                    max_tokens=150,
                    temperature=0.7
                )
                
                if response and hasattr(response, 'choices') and len(response.choices) > 0:
                    content = response.choices[0].text.strip()
                    app.logger.info(f"Received friendly error message from OpenAI")
            except Exception as e:
                app.logger.error(f"OpenAI completion error: {e}")
        
        # Return the friendly message if available
        if content:
            return content.strip()
            
    except Exception as e:
        app.logger.error(f"Error generating friendly error message: {e}")
    
    return None

def register_error_handlers(app):
    """Register error handlers with the Flask application."""
    
    # Add endpoint to get friendly error message asynchronously
    @app.route('/api/friendly-error', methods=['POST'])
    @csrf.exempt  # Exempt this endpoint from CSRF protection
    def get_friendly_error_message():
        try:
            data = request.get_json()
            error_info = {
                'error_type': data.get('error_type', 'Unknown Error'),
                'error_message': data.get('error_message', 'No specific message available'),
                'code': data.get('code', 'Unknown')
            }
            
            friendly_message = generate_friendly_error_message(error_info, app)
            
            if friendly_message:
                return jsonify({'success': True, 'message': friendly_message})
            else:
                return jsonify({'success': False, 'message': 'Could not generate a friendly message'}), 500
        except Exception as e:
            app.logger.error(f"Error in friendly error API: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.errorhandler(400)
    def bad_request_error(error):
        return handle_error(error, 400, "Bad Request")
    
    @app.errorhandler(401)
    def unauthorized_error(error):
        return handle_error(error, 401, "Unauthorized")
    
    @app.errorhandler(403)
    def forbidden_error(error):
        return handle_error(error, 403, "Forbidden")
    
    @app.errorhandler(404)
    def not_found_error(error):
        return handle_error(error, 404, "Page Not Found")
    
    @app.errorhandler(405)
    def method_not_allowed_error(error):
        return handle_error(error, 405, "Method Not Allowed")
    
    @app.errorhandler(429)
    def too_many_requests_error(error):
        return handle_error(error, 429, "Too Many Requests")
    
    @app.errorhandler(500)
    def internal_server_error(error):
        return handle_error(error, 500, "Internal Server Error")
    
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return handle_error(error, 400, "CSRF Error")
    
    # Add this to ensure other errors are also captured
    @app.errorhandler(Exception)
    def unhandled_exception(error):
        app.logger.error(f"Unhandled Exception: {error}")
        return handle_error(error, 500, "Internal Server Error")


def handle_error(error, code, default_message):
    """
    Common error handler that renders the error.html template with appropriate context
    """
    # Get the error message
    message = getattr(error, 'description', str(error)) or default_message
    
    # Prepare debug info for logged-in users
    debug_info = None
    tb = None
    
    # Use Flask-Login instead of checking for access_token in session
    if current_user.is_authenticated:
        # Include request details in debug info
        debug_info = {
            'error_type': error.__class__.__name__,
            'request_path': request.path,
            'request_method': request.method,
            'request_headers': {k: v for k, v in request.headers.items() if k.lower() not in ('cookie', 'authorization')},
            'request_args': request.args.to_dict(),
        }
        
        # Include POST data if it's form data (not for file uploads)
        if request.form and 'multipart/form-data' not in request.content_type:
            debug_info['request_form'] = request.form.to_dict()
            
        # Include JSON data if applicable
        if request.is_json:
            try:
                debug_info['request_json'] = request.get_json()
            except:
                debug_info['request_json'] = 'Invalid JSON'
        
        # Get traceback for more detailed debugging
        tb = traceback.format_exc() if code == 500 else None
        
        # Convert debug_info to formatted string for template
        debug_info_str = json.dumps(debug_info, indent=2)
    
    # We'll pass the error info to the template so JavaScript can request a friendly message
    error_info_for_js = json.dumps({
        'error_type': error.__class__.__name__,
        'error_message': str(error),
        'code': code
    })
    
    # Render the template with all necessary information
    return render_template(
        'error.html',
        message=message,  # Original technical message
        code=code,
        debug_info=debug_info_str if 'debug_info_str' in locals() else None,
        traceback=tb,
        error_info_for_js=error_info_for_js  # Error info for JavaScript to use
    ), code