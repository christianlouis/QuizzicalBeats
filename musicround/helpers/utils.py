"""
General utility functions used throughout the application.
"""
import secrets
import string
import os
import shutil
from flask import current_app
from werkzeug.utils import secure_filename
import uuid
import requests
import json

def generate_token(length=32):
    """
    Generate a secure random token for authentication or validation purposes.
    
    Args:
        length (int): The length of the token to generate (default: 32)
        
    Returns:
        str: A secure random token string
    """
    # Use secrets module for cryptographically strong random numbers
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token

def get_user_mp3_directory(username):
    """
    Get the directory path for a user's custom MP3 files
    Creates the directory if it doesn't exist
    
    Args:
        username (str): Username
        
    Returns:
        str: Path to the user's MP3 directory
    """
    base_dir = os.path.join('/data', 'custommp3')
    user_dir = os.path.join(base_dir, secure_filename(username))
    
    # Create directories if they don't exist
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        
    return user_dir

def save_user_mp3(file, username, mp3_type):
    """
    Save a user's uploaded MP3 file
    
    Args:
        file: FileStorage object from Flask request.files
        username (str): Username
        mp3_type (str): Type of MP3 (intro, outro, or replay)
        
    Returns:
        str: Path to the saved file relative to data directory
    """
    if not file or not allowed_file(file.filename):
        return None
        
    # Get user directory and create if needed
    user_dir = get_user_mp3_directory(username)
    
    # Generate a unique filename to avoid overwriting
    original_filename = secure_filename(file.filename)
    file_extension = os.path.splitext(original_filename)[1]  # Should be .mp3
    unique_filename = f"{mp3_type}{file_extension}"
    
    # Full path to save the file
    filepath = os.path.join(user_dir, unique_filename)
    
    # Save the file
    file.save(filepath)
    
    # Return the relative path for database storage
    return os.path.join('custommp3', secure_filename(username), unique_filename)

def allowed_file(filename):
    """
    Check if the file has an allowed extension
    
    Args:
        filename (str): Name of the file
        
    Returns:
        bool: True if extension is allowed, False otherwise
    """
    allowed_extensions = {'mp3'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def get_mp3_path(user, mp3_type):
    """
    Get the path to a user's custom MP3 file or the default if not set
    
    Args:
        user: User object from database
        mp3_type (str): Type of MP3 (intro, outro, or replay)
    
    Returns:
        str: Path to the MP3 file
    """
    user_setting_attr = f"{mp3_type}_mp3"
    user_mp3_path = getattr(user, user_setting_attr)
    
    if user_mp3_path and os.path.exists(os.path.join('/data', user_mp3_path)):
        return os.path.join('/data', user_mp3_path)
    
    # Fall back to the default MP3
    return os.path.join(current_app.root_path, 'static', 'audio', f'{mp3_type}.mp3')

def get_available_voices(service='polly'):
    """
    Get a list of available voices for the specified TTS service
    
    Args:
        service (str): TTS service ('polly', 'openai', or 'elevenlabs')
        
    Returns:
        list: List of available voice options
    """
    if service == 'polly':
        # Standard AWS Polly voices - subset of most natural ones
        return [
            {'id': 'Joanna', 'name': 'Joanna (Female, US)', 'gender': 'Female', 'language': 'en-US'},
            {'id': 'Matthew', 'name': 'Matthew (Male, US)', 'gender': 'Male', 'language': 'en-US'},
            {'id': 'Amy', 'name': 'Amy (Female, UK)', 'gender': 'Female', 'language': 'en-GB'},
            {'id': 'Brian', 'name': 'Brian (Male, UK)', 'gender': 'Male', 'language': 'en-GB'},
            {'id': 'Kendra', 'name': 'Kendra (Female, US)', 'gender': 'Female', 'language': 'en-US'},
            {'id': 'Kimberly', 'name': 'Kimberly (Female, US)', 'gender': 'Female', 'language': 'en-US'},
            {'id': 'Salli', 'name': 'Salli (Female, US)', 'gender': 'Female', 'language': 'en-US'},
            {'id': 'Joey', 'name': 'Joey (Male, US)', 'gender': 'Male', 'language': 'en-US'},
        ]
    elif service == 'openai':
        return [
            {'id': 'alloy', 'name': 'Alloy (Neutral)', 'gender': 'Neutral', 'language': 'en'},
            {'id': 'echo', 'name': 'Echo (Male)', 'gender': 'Male', 'language': 'en'},
            {'id': 'fable', 'name': 'Fable (Male)', 'gender': 'Male', 'language': 'en'},
            {'id': 'onyx', 'name': 'Onyx (Male)', 'gender': 'Male', 'language': 'en'},
            {'id': 'nova', 'name': 'Nova (Female)', 'gender': 'Female', 'language': 'en'},
            {'id': 'shimmer', 'name': 'Shimmer (Female)', 'gender': 'Female', 'language': 'en'},
        ]
    elif service == 'elevenlabs':
        # Check if we have a valid API key
        api_key = current_app.config.get('ELEVENLABS_API_KEY')
        if not api_key:
            return []
            
        try:
            # Call the ElevenLabs API to get available voices
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json"
            }
            response = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers)
            
            if response.status_code == 200:
                voices_data = response.json()
                voices = []
                for voice in voices_data.get('voices', []):
                    voice_info = {
                        'id': voice.get('voice_id'),
                        'name': voice.get('name', 'Unknown'),
                        'gender': voice.get('labels', {}).get('gender', 'Unknown'),
                        'language': 'en'  # Default to English
                    }
                    voices.append(voice_info)
                return voices
            else:
                current_app.logger.error(f"Error fetching ElevenLabs voices: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            current_app.logger.error(f"Exception fetching ElevenLabs voices: {str(e)}")
            return []
    
    # Default fallback
    return []

def generate_tts_mp3(text, username, mp3_type, service='polly', voice=None, model=None, stability=None, similarity=None):
    """
    Generate a text-to-speech MP3 file
    
    Args:
        text (str): The text to convert to speech
        username (str): Username
        mp3_type (str): Type of MP3 (intro, outro, or replay)
        service (str): TTS service to use ('polly', 'openai', or 'elevenlabs')
        voice (str): Voice ID to use (defaults to service-specific default if None)
        model (str): Model to use for OpenAI or ElevenLabs (defaults to service-specific default if None)
        stability (float): Voice stability parameter for ElevenLabs (0.0-1.0)
        similarity (float): Voice similarity parameter for ElevenLabs (0.0-1.0)
    
    Returns:
        str: Path to the generated file relative to data directory
    """
    try:
        user_dir = get_user_mp3_directory(username)
        output_filename = f"{mp3_type}.mp3"
        output_path = os.path.join(user_dir, output_filename)
        
        if service == 'polly':
            # AWS Polly implementation
            import boto3
            
            polly_client = boto3.client('polly', 
                region_name=current_app.config.get('AWS_REGION', 'us-east-1'),
                aws_access_key_id=current_app.config.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=current_app.config.get('AWS_SECRET_ACCESS_KEY')
            )
            
            # Use provided voice or default
            voice_id = voice or current_app.config.get('AWS_POLLY_VOICE', 'Joanna')
            
            # Use neural engine if available
            engine = 'neural' if voice_id in ['Joanna', 'Matthew', 'Amy', 'Emma', 'Brian', 'Kendra'] else 'standard'
            
            response = polly_client.synthesize_speech(
                Text=text,
                OutputFormat='mp3',
                VoiceId=voice_id,
                Engine=engine
            )
            
            # Write the audio stream to a file
            if "AudioStream" in response:
                with open(output_path, 'wb') as file:
                    file.write(response["AudioStream"].read())
                
                current_app.logger.info(f"Generated AWS Polly TTS with voice {voice_id} for {username}/{mp3_type}")
        
        elif service == 'openai':
            # OpenAI TTS implementation
            import openai
            
            openai.api_key = current_app.config.get('OPENAI_API_KEY')
            openai.base_url = current_app.config.get('OPENAI_URL', 'https://api.openai.com/v1')
            
            # Use provided voice or default
            voice_id = voice or 'alloy'
            # Use provided model or default
            tts_model = model or 'tts-1'  # Options: tts-1, tts-1-hd
            
            response = openai.audio.speech.create(
                model=tts_model,
                voice=voice_id,
                input=text
            )
            
            response.stream_to_file(output_path)
            current_app.logger.info(f"Generated OpenAI TTS with voice {voice_id} for {username}/{mp3_type}")
        
        elif service == 'elevenlabs':
            # ElevenLabs implementation
            api_key = current_app.config.get('ELEVENLABS_API_KEY')
            if not api_key:
                current_app.logger.error("ElevenLabs API key not configured")
                return None
                
            # Use provided voice or default
            voice_id = voice or "21m00Tcm4TlvDq8ikWAM"  # Default to "Rachel" voice
            
            # Set default values for stability and similarity if not provided
            stability_value = stability if stability is not None else 0.5
            similarity_value = similarity if similarity is not None else 0.75
            
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "text": text,
                "model_id": model or "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": stability_value,
                    "similarity_boost": similarity_value
                }
            }
            
            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                data=json.dumps(payload)
            )
            
            if response.status_code == 200:
                with open(output_path, 'wb') as file:
                    file.write(response.content)
                current_app.logger.info(f"Generated ElevenLabs TTS with voice {voice_id} for {username}/{mp3_type}")
            else:
                current_app.logger.error(f"ElevenLabs API error: {response.status_code} - {response.text}")
                return None
                
        # Return the relative path for database storage
        return os.path.join('custommp3', secure_filename(username), output_filename)
        
    except Exception as e:
        current_app.logger.error(f"Error generating TTS MP3: {str(e)}")
        return None
