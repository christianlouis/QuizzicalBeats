from flask import Blueprint, redirect, url_for, flash, jsonify
from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.contrib.fileadmin import FileAdmin
from flask_admin.menu import MenuLink
from flask_admin.actions import action
from flask_login import current_user, login_required
from musicround.models import Song, Tag, SongTag, Round, User, Role, UserPreferences, SystemSetting, db
from functools import wraps
import os
import json

# Create a basic authentication wrapper
def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        # Check if user is logged in and is an admin
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        
        if not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('core.index'))
            
        return view_func(*args, **kwargs)
    return wrapper

# Create the blueprint
db_admin_bp = Blueprint('db_admin', __name__, url_prefix='/admin')

# Define routes on the blueprint before it gets registered
@db_admin_bp.route('/raw')
@admin_required
def raw_db_access():
    return redirect(url_for('admin.index'))

# Base model view with authentication
class AuthModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin()
    
    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        return redirect(url_for('core.index'))
    
    # Add basic search functionality to all models
    column_searchable_list = []
    column_filters = []
    
    # Enable export to CSV
    can_export = True
    export_types = ['csv', 'json']

# Enhanced Song ModelView
class SongModelView(AuthModelView):
    column_searchable_list = ['title', 'artist', 'spotify_id']
    column_filters = ['title', 'artist', 'year', 'genre', 'used_count']
    column_default_sort = ('id', False)
    
    @action('reset_used_count', 'Reset Used Count', 'Are you sure you want to reset used count to 0?')
    def action_reset_used_count(self, ids):
        try:
            query = Song.query.filter(Song.id.in_(ids))
            
            # Update all songs
            for song in query.all():
                song.used_count = 0
            
            db.session.commit()
            flash(f'Used count reset for {len(ids)} songs.', 'success')
        except Exception as ex:
            db.session.rollback()
            flash(f'Error resetting used count: {str(ex)}', 'danger')

# Enhanced Round ModelView
class RoundModelView(AuthModelView):
    column_searchable_list = ['name', 'round_type', 'round_criteria_used']
    column_filters = ['name', 'round_type', 'round_criteria_used']
    column_list = ['id', 'name', 'round_type', 'round_criteria_used', 'created_at', 'mp3_generated', 'pdf_generated']
    column_default_sort = ('id', False)

# Enhanced Tag ModelView
class TagModelView(AuthModelView):
    column_searchable_list = ['name']
    column_filters = ['name']

# Enhanced SongTag ModelView
class SongTagModelView(AuthModelView):
    column_filters = ['song_id', 'tag_id']

# Enhanced User ModelView
class UserModelView(AuthModelView):
    column_searchable_list = ['username', 'email', 'first_name', 'last_name']
    column_filters = ['username', 'email', 'active', 'created_at', 'last_login']
    column_default_sort = ('id', False)
    
    # Protect password field in forms
    form_excluded_columns = ['password_hash', 'reset_token', 'reset_token_expiry']
    
    @action('activate_users', 'Activate Users', 'Are you sure you want to activate selected users?')
    def action_activate_users(self, ids):
        try:
            query = User.query.filter(User.id.in_(ids))
            
            # Update all selected users
            for user in query.all():
                user.active = True
            
            db.session.commit()
            flash(f'Successfully activated {len(ids)} users.', 'success')
        except Exception as ex:
            db.session.rollback()
            flash(f'Error activating users: {str(ex)}', 'danger')
            
    @action('deactivate_users', 'Deactivate Users', 'Are you sure you want to deactivate selected users?')
    def action_deactivate_users(self, ids):
        try:
            query = User.query.filter(User.id.in_(ids))
            
            # Update all selected users
            for user in query.all():
                user.active = False
            
            db.session.commit()
            flash(f'Successfully deactivated {len(ids)} users.', 'success')
        except Exception as ex:
            db.session.rollback()
            flash(f'Error deactivating users: {str(ex)}', 'danger')

# Enhanced Role ModelView
class RoleModelView(AuthModelView):
    column_searchable_list = ['name', 'description']
    column_filters = ['name']

# Enhanced UserPreferences ModelView
class UserPreferencesModelView(AuthModelView):
    column_filters = ['user_id', 'theme', 'enable_intro']
    
# Enhanced SystemSetting ModelView
class SystemSettingModelView(AuthModelView):
    column_searchable_list = ['key']
    column_filters = ['key']
    column_exclude_list = []  # Ensure any sensitive values are not excluded if needed

# Initialize the admin interface
admin = None

def init_admin(app):
    """Initialize the admin interface with the Flask app."""
    global admin
    
    # Set Flask-Admin configuration
    app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'  # Use a Bootstrap swatch theme
    
    # Create admin interface
    admin = Admin(
        app, 
        name='MusicRound Admin', 
        template_mode='bootstrap3',
        url='/admin'
    )
    
    # Add model views
    # Data models
    admin.add_view(SongModelView(Song, db.session, category="Music Data"))
    admin.add_view(TagModelView(Tag, db.session, category="Music Data"))
    admin.add_view(SongTagModelView(SongTag, db.session, category="Music Data"))
    admin.add_view(RoundModelView(Round, db.session, category="Music Data"))
    
    # User management
    admin.add_view(UserModelView(User, db.session, category="User Management"))
    admin.add_view(RoleModelView(Role, db.session, category="User Management"))
    admin.add_view(UserPreferencesModelView(UserPreferences, db.session, category="User Management"))
    
    # System
    admin.add_view(SystemSettingModelView(SystemSetting, db.session, category="System"))
    
    # Add file admin for audio files
    path = os.path.join(os.path.dirname(__file__), '../static/audio')
    admin.add_view(FileAdmin(path, '/static/audio/', name='Audio Files', category="System", endpoint='static_audio_files'))
    
    # User MP3 files
    user_mp3_path = os.path.join(os.path.dirname(__file__), '../mp3')
    admin.add_view(FileAdmin(user_mp3_path, '/mp3/', name='User MP3 Files', category="System", endpoint='user_mp3_files'))
    
    # Add links
    admin.add_link(MenuLink(name='Back to App', url='/'))
    
    return admin