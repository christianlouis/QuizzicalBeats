"""
Helpers for Dropbox API integration
"""
from flask import current_app, url_for, redirect, session
from musicround.helpers.auth_helpers import get_oauth_redirect_uri
import requests
import json
import os
from datetime import datetime, timedelta
from flask_login import current_user

def get_dropbox_auth_url():
    """Get the authorization URL for Dropbox OAuth flow"""
    app_key = current_app.config.get('DROPBOX_APP_KEY')
    redirect_uri = get_oauth_redirect_uri('users.dropbox_callback')
    
    # Add the required scopes for our application
    scopes = ["files.content.read", "files.content.write", "sharing.write","account_info.read"]
    
    auth_url = f'https://www.dropbox.com/oauth2/authorize?client_id={app_key}&response_type=code&redirect_uri={redirect_uri}&scope={" ".join(scopes)}&token_access_type=offline'
    return auth_url

def exchange_code_for_token(code):
    """Exchange the authorization code for an access token"""
    app_key = current_app.config.get('DROPBOX_APP_KEY')
    app_secret = current_app.config.get('DROPBOX_APP_SECRET')
    redirect_uri = get_oauth_redirect_uri('users.dropbox_callback')
    
    data = {
        'code': code,
        'grant_type': 'authorization_code',
        'client_id': app_key,
        'client_secret': app_secret,
        'redirect_uri': redirect_uri
    }
    
    response = requests.post('https://api.dropboxapi.com/oauth2/token', data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        current_app.logger.error(f"Error exchanging code for token: {response.text}")
        return None

def refresh_dropbox_token(refresh_token):
    """Refresh an expired Dropbox access token"""
    app_key = current_app.config.get('DROPBOX_APP_KEY')
    app_secret = current_app.config.get('DROPBOX_APP_SECRET')
    
    data = {
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
        'client_id': app_key,
        'client_secret': app_secret
    }
    
    response = requests.post('https://api.dropboxapi.com/oauth2/token', data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        current_app.logger.error(f"Error refreshing token: {response.text}")
        return None

def get_dropbox_user_info(access_token):
    """Get user info from Dropbox API"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.post('https://api.dropboxapi.com/2/users/get_current_account', headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        current_app.logger.error(f"Error getting user info: {response.text}")
        return None

def get_current_user_dropbox_token():
    """Get a valid Dropbox access token for the current user, refreshing if needed"""
    if not current_user or not current_user.is_authenticated:
        current_app.logger.error("No authenticated user")
        return None
    
    # Check if token exists and is valid
    if (current_user.dropbox_token and 
        current_user.dropbox_token_expiry and 
        current_user.dropbox_token_expiry > datetime.now() + timedelta(minutes=5)):
        # Token is valid and not about to expire
        return current_user.dropbox_token
    
    # Token is missing or about to expire - try to refresh
    if current_user.dropbox_refresh_token:
        from musicround.models import db
        
        # Try to refresh the token
        token_info = refresh_dropbox_token(current_user.dropbox_refresh_token)
        
        if token_info and 'access_token' in token_info:
            # Update token in database
            current_user.dropbox_token = token_info['access_token']
            expires_in = token_info.get('expires_in', 14400)  # Default to 4 hours if not specified
            current_user.dropbox_token_expiry = datetime.now() + timedelta(seconds=expires_in)
            
            db.session.commit()
            
            return current_user.dropbox_token
    
    # If we get here, we couldn't refresh the token
    current_app.logger.error("Failed to get valid Dropbox token")
    return None

def upload_and_share(file_path, dropbox_path):
    """
    Upload a file to Dropbox and create a shared link
    
    Args:
        file_path: Local path to the file to upload
        dropbox_path: Destination path in Dropbox (including filename)
        
    Returns:
        Shared link URL or None if upload failed
    """
    token = get_current_user_dropbox_token()
    if not token:
        current_app.logger.error("No valid Dropbox token available")
        return None
    
    # Make sure dropbox_path starts with /
    if not dropbox_path.startswith('/'):
        dropbox_path = '/' + dropbox_path
    
    # First, upload the file
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            current_app.logger.error(f"File not found: {file_path}")
            return None
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # For small files (< 150 MB), use simple upload
        if file_size < 150 * 1024 * 1024:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Dropbox-API-Arg': json.dumps({
                    'path': dropbox_path,
                    'mode': 'overwrite',
                    'autorename': True,
                    'mute': False
                }),
                'Content-Type': 'application/octet-stream'
            }
            
            response = requests.post(
                'https://content.dropboxapi.com/2/files/upload',
                headers=headers,
                data=file_data
            )
            
            if response.status_code != 200:
                current_app.logger.error(f"Error uploading file: {response.text}")
                return None
            
            file_metadata = response.json()
            current_app.logger.info(f"File uploaded successfully: {file_metadata.get('path_display')}")
        else:
            # For larger files, we'd implement chunked upload here
            current_app.logger.error(f"File too large for simple upload: {file_size} bytes")
            return None
        
        # Now create a shared link
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'path': file_metadata.get('path_lower', dropbox_path),
            'settings': {
                'requested_visibility': 'public'  # Make link publicly accessible
            }
        }
        
        response = requests.post(
            'https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings',
            headers=headers,
            json=data
        )
        
        # If the link already exists, we'll get a 409 error with "shared_link_already_exists"
        if response.status_code == 409 and "shared_link_already_exists" in response.text:
            # Get existing links
            list_data = {
                'path': file_metadata.get('path_lower', dropbox_path)
            }
            
            list_response = requests.post(
                'https://api.dropboxapi.com/2/sharing/list_shared_links',
                headers=headers,
                json=list_data
            )
            
            if list_response.status_code == 200:
                links_data = list_response.json()
                if links_data.get('links') and len(links_data['links']) > 0:
                    # Return the first link's URL
                    return links_data['links'][0].get('url')
        
        elif response.status_code == 200:
            share_data = response.json()
            current_app.logger.info(f"Created shared link: {share_data.get('url')}")
            return share_data.get('url')
        
        current_app.logger.error(f"Error creating shared link: {response.text}")
        return None
        
    except Exception as e:
        current_app.logger.error(f"Exception in upload_and_share: {str(e)}")
        return None

def refresh_dropbox_token_if_needed(user):
    """
    Check if user's Dropbox token needs refreshing and refresh it if needed
    
    Args:
        user: The User object with Dropbox token information
        
    Returns:
        dict: {'success': True/False, 'message': 'success or error message'}
    """
    if not user.dropbox_token or not user.dropbox_refresh_token:
        return {'success': False, 'message': 'No Dropbox token available'}
    
    # If token is still valid, return success
    if user.dropbox_token_expiry and user.dropbox_token_expiry > datetime.now() + timedelta(minutes=5):
        return {'success': True, 'message': 'Token is still valid'}
    
    # Token needs refreshing
    from musicround.models import db
    
    try:
        token_info = refresh_dropbox_token(user.dropbox_refresh_token)
        
        if token_info and 'access_token' in token_info:
            # Update token in database
            user.dropbox_token = token_info['access_token']
            expires_in = token_info.get('expires_in', 14400)  # Default to 4 hours if not specified
            user.dropbox_token_expiry = datetime.now() + timedelta(seconds=expires_in)
            
            # If we got a new refresh token, update that too
            if token_info.get('refresh_token'):
                user.dropbox_refresh_token = token_info['refresh_token']
            
            db.session.commit()
            
            return {'success': True, 'message': 'Token refreshed successfully'}
        else:
            return {'success': False, 'message': 'Failed to refresh token'}
            
    except Exception as e:
        current_app.logger.error(f"Error refreshing Dropbox token: {str(e)}")
        return {'success': False, 'message': f'Error refreshing token: {str(e)}'}

def upload_to_dropbox(access_token, dropbox_path, data, mode='binary'):
    """
    Upload data to Dropbox
    
    Args:
        access_token: Dropbox access token
        dropbox_path: Destination path in Dropbox (including filename)
        data: The data to upload (bytes for binary mode, string for text mode)
        mode: 'binary' or 'text'
        
    Returns:
        dict: {'success': True/False, 'message': 'success or error message', 'metadata': file metadata if successful}
    """
    # Make sure dropbox_path starts with /
    if not dropbox_path.startswith('/'):
        dropbox_path = '/' + dropbox_path
    
    try:
        # Convert string data to bytes if text mode
        if mode == 'text' and isinstance(data, str):
            data = data.encode('utf-8')
        
        # Debug token information
        token_preview = access_token[:10] + '...' if access_token else 'None'
        current_app.logger.debug(f"Upload to Dropbox - Path: {dropbox_path}, Token preview: {token_preview}, Data size: {len(data) if data else 0} bytes")
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Dropbox-API-Arg': json.dumps({
                'path': dropbox_path,
                'mode': 'overwrite',
                'autorename': True,
                'mute': False
            }),
            'Content-Type': 'application/octet-stream'
        }
        
        current_app.logger.debug(f"Dropbox API headers: {headers}")
        
        response = requests.post(
            'https://content.dropboxapi.com/2/files/upload',
            headers=headers,
            data=data
        )
        
        current_app.logger.debug(f"Dropbox upload response code: {response.status_code}")
        
        if response.status_code != 200:
            current_app.logger.error(f"Error uploading to Dropbox: Status code {response.status_code}")
            current_app.logger.error(f"Response headers: {response.headers}")
            
            # Try to parse response body
            try:
                error_json = response.json()
                current_app.logger.error(f"Error details: {json.dumps(error_json, indent=2)}")
                error_message = error_json.get('error_summary', 'Unknown error')
            except:
                error_message = response.text[:500]  # Limit to first 500 chars
                current_app.logger.error(f"Raw error response: {error_message}")
            
            return {
                'success': False, 
                'message': f"Error uploading file: {response.status_code} - {error_message}",
                'status_code': response.status_code
            }
        
        file_metadata = response.json()
        current_app.logger.info(f"File uploaded successfully: {file_metadata.get('path_display')}")
        current_app.logger.debug(f"Upload metadata: {json.dumps(file_metadata, indent=2)}")
        
        return {
            'success': True,
            'message': 'File uploaded successfully',
            'metadata': file_metadata
        }
        
    except Exception as e:
        import traceback
        current_app.logger.error(f"Exception in upload_to_dropbox: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return {
            'success': False,
            'message': f"Error uploading file: {str(e)}"
        }

def create_shared_link(access_token, dropbox_path):
    """
    Create a shared link for a file in Dropbox
    
    Args:
        access_token: Dropbox access token
        dropbox_path: Path to the file in Dropbox
        
    Returns:
        dict: {'success': True/False, 'message': 'success or error message', 'url': shared link URL if successful}
    """
    # Make sure dropbox_path starts with /
    if not dropbox_path.startswith('/'):
        dropbox_path = '/' + dropbox_path
    
    try:
        # Debug token information
        token_preview = access_token[:10] + '...' if access_token else 'None'
        current_app.logger.debug(f"Creating shared link - Path: {dropbox_path}, Token preview: {token_preview}")
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'path': dropbox_path,
            'settings': {
                'requested_visibility': 'public'  # Make link publicly accessible
            }
        }
        
        current_app.logger.debug(f"Sharing API request data: {json.dumps(data, indent=2)}")
        
        response = requests.post(
            'https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings',
            headers=headers,
            json=data
        )
        
        current_app.logger.debug(f"Sharing API response code: {response.status_code}")
        
        # If the link already exists, we'll get a 409 error with "shared_link_already_exists"
        if response.status_code == 409 and "shared_link_already_exists" in response.text:
            current_app.logger.debug("Shared link already exists, retrieving existing link")
            
            # Get existing links
            list_data = {
                'path': dropbox_path
            }
            
            list_response = requests.post(
                'https://api.dropboxapi.com/2/sharing/list_shared_links',
                headers=headers,
                json=list_data
            )
            
            current_app.logger.debug(f"List shared links response code: {list_response.status_code}")
            
            if list_response.status_code == 200:
                links_data = list_response.json()
                current_app.logger.debug(f"Existing links data: {json.dumps(links_data, indent=2)}")
                
                if links_data.get('links') and len(links_data['links']) > 0:
                    # Return the first link's URL
                    url = links_data['links'][0].get('url')
                    current_app.logger.info(f"Retrieved existing shared link: {url}")
                    return {
                        'success': True,
                        'message': 'Existing shared link retrieved',
                        'url': url
                    }
                else:
                    current_app.logger.error("No links found despite 'shared_link_already_exists' error")
            else:
                current_app.logger.error(f"Error listing shared links: {list_response.text}")
        
        elif response.status_code == 200:
            share_data = response.json()
            current_app.logger.info(f"Created shared link: {share_data.get('url')}")
            current_app.logger.debug(f"Shared link data: {json.dumps(share_data, indent=2)}")
            return {
                'success': True,
                'message': 'Shared link created successfully',
                'url': share_data.get('url')
            }
        
        # Try to parse error response
        try:
            error_json = response.json()
            current_app.logger.error(f"Sharing API error details: {json.dumps(error_json, indent=2)}")
            error_message = error_json.get('error_summary', 'Unknown error')
        except:
            error_message = response.text[:500]  # Limit to first 500 chars
            current_app.logger.error(f"Raw sharing API error response: {error_message}")
        
        current_app.logger.error(f"Error creating shared link: {response.status_code} - {error_message}")
        return {
            'success': False,
            'message': f"Error creating shared link: {response.status_code} - {error_message}",
            'status_code': response.status_code
        }
        
    except Exception as e:
        import traceback
        current_app.logger.error(f"Exception in create_shared_link: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return {
            'success': False,
            'message': f"Error creating shared link: {str(e)}"
        }

def get_dropbox_account_info(access_token):
    """
    Get account information for a Dropbox user
    
    Args:
        access_token: Dropbox access token
        
    Returns:
        dict: Account information or None if failed
    """
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        # According to the API documentation, this endpoint requires no request body
        response = requests.post(
            'https://api.dropboxapi.com/2/users/get_current_account',
            headers=headers
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            current_app.logger.error(f"Error getting Dropbox account info: {response.text}")
            return None
            
    except Exception as e:
        current_app.logger.error(f"Exception in get_dropbox_account_info: {str(e)}")
        return None