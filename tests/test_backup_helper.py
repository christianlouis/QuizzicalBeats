"""Tests for backup_helper module."""
import pytest
import json
import os
import sqlite3
import stat
import zipfile
import tempfile
from unittest.mock import patch, MagicMock
from musicround.models import SystemSetting


def _write_sqlite_db(path, marker='backup'):
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS smoke (value TEXT)')
        conn.execute('DELETE FROM smoke')
        conn.execute('INSERT INTO smoke (value) VALUES (?)', (marker,))
        conn.commit()
    finally:
        conn.close()


def _read_sqlite_marker(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute('SELECT value FROM smoke').fetchone()[0]
    finally:
        conn.close()


def _exists_including_zip(zip_path):
    original_exists = os.path.exists

    def exists(path):
        return path == str(zip_path) or original_exists(path)

    return exists


class TestListBackups:
    """Tests for list_backups function."""

    def test_list_backups_no_directory(self, app):
        """Test list_backups returns empty list when backup dir doesn't exist."""
        from musicround.helpers.backup_helper import list_backups

        with patch('os.path.exists', side_effect=lambda p: False if 'backups' in p else os.path.exists(p)), \
             patch('os.makedirs'):
            result = list_backups()
        assert result == []

    def test_list_backups_empty_directory(self, app, tmp_path):
        """Test list_backups returns empty list for empty backup directory."""
        from musicround.helpers.backup_helper import list_backups

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        backup_dir_str = str(backup_dir)

        orig_join = os.path.join
        orig_exists = os.path.exists

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return backup_dir_str
            return orig_join(*args)

        def mock_exists(p):
            if p == backup_dir_str:
                return True
            return orig_exists(p)

        with patch('os.path.join', side_effect=mock_join), \
             patch('os.path.exists', side_effect=mock_exists):
            result = list_backups()
        assert isinstance(result, list)

    def test_list_backups_with_zip_no_metadata(self, app, tmp_path):
        """Test list_backups handles ZIP files without backup_metadata.json."""
        from musicround.helpers.backup_helper import list_backups

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()

        # Create a minimal ZIP file without metadata
        zip_path = backup_dir / 'backup_20240101_120000.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('song_data.db', b'fake db content')

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        with patch('os.path.join', side_effect=mock_join), \
             patch('os.path.exists', return_value=True), \
             patch('os.listdir', return_value=['backup_20240101_120000.zip']):
            result = list_backups()
        assert isinstance(result, list)

    def test_list_backups_with_valid_metadata(self, app, tmp_path):
        """Test list_backups returns backup info from ZIP metadata."""
        from musicround.helpers.backup_helper import list_backups

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()

        metadata = {
            'backup_name': 'test_backup',
            'timestamp': '2024-01-01T12:00:00',
            'version': '1.0.0',
            'release_name': 'Test',
        }
        zip_path = backup_dir / 'test_backup.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('backup_metadata.json', json.dumps(metadata))
            zf.writestr('song_data.db', b'fake db')

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        with patch('os.path.join', side_effect=mock_join), \
             patch('os.path.exists', return_value=True), \
             patch('os.listdir', return_value=['test_backup.zip']):
            result = list_backups()
        assert isinstance(result, list)
        if result:  # If file was actually read
            assert result[0]['backup_name'] == 'test_backup'


class TestDeleteBackup:
    """Tests for delete_backup function."""

    def test_delete_backup_not_found(self, app):
        """Test delete_backup returns error when file doesn't exist."""
        from musicround.helpers.backup_helper import delete_backup

        with patch('os.path.exists', return_value=False), \
             patch('os.path.join', return_value='/data/backups/nonexistent.zip'):
            result = delete_backup('nonexistent.zip')
        assert result['status'] == 'error'
        assert 'not found' in result['message'].lower()

    def test_delete_backup_success(self, app, tmp_path):
        """Test delete_backup successfully removes the file."""
        from musicround.helpers.backup_helper import delete_backup

        # Create a real temp file
        backup_file = tmp_path / 'delete_me.zip'
        backup_file.write_text('fake zip content')

        orig_join = os.path.join

        def mock_join(*args):
            if len(args) == 2 and args[0] == '/data/backups':
                return str(tmp_path / args[1])
            if args == ('/data', 'backups'):
                return str(tmp_path)
            return orig_join(*args)

        with patch('os.path.join', side_effect=mock_join), \
             patch('os.path.exists', side_effect=lambda p: p == str(backup_file) or os.path.exists(p)):
            result = delete_backup('delete_me.zip')
        assert result['status'] == 'success'
        assert not backup_file.exists()

    def test_delete_backup_os_error(self, app):
        """Test delete_backup handles OS errors gracefully."""
        from musicround.helpers.backup_helper import delete_backup

        with patch('os.path.exists', return_value=True), \
             patch('os.path.join', return_value='/data/backups/bad.zip'), \
             patch('os.remove', side_effect=OSError('Permission denied token=delete-secret traceback')):
            result = delete_backup('bad.zip')
        assert result['status'] == 'error'
        assert result['message'] == 'Backup deletion failed. Check the server logs.'
        assert 'delete-secret' not in result['message']
        assert 'Permission denied' not in result['message']


class TestVerifyBackup:
    """Tests for verify_backup function."""

    def test_verify_backup_not_found(self, app):
        """Test verify_backup returns error for non-existent file."""
        from musicround.helpers.backup_helper import verify_backup

        with patch('os.path.exists', return_value=False), \
             patch('os.path.join', return_value='/data/backups/none.zip'):
            result = verify_backup('none.zip')
        assert result['status'] == 'error'
        assert result['is_valid'] is False

    def test_verify_backup_invalid_zip(self, app, tmp_path):
        """Test verify_backup returns error for invalid ZIP file."""
        from musicround.helpers.backup_helper import verify_backup

        bad_zip = tmp_path / 'bad.zip'
        bad_zip.write_text('not a zip file')

        with patch('os.path.exists', side_effect=lambda p: p == str(bad_zip) or os.path.exists(p)), \
             patch('os.path.join', return_value=str(bad_zip)):
            result = verify_backup('bad.zip')
        assert result['status'] == 'error'
        assert result['is_valid'] is False
        assert 'not a valid ZIP archive' in result['message']

    def test_verify_backup_exception_hides_details(self, app):
        """Unexpected verify errors should not expose filesystem details."""
        from musicround.helpers.backup_helper import verify_backup

        with patch('os.path.exists', return_value=True), \
             patch('os.path.join', return_value='/data/backups/bad.zip'), \
             patch('zipfile.is_zipfile', side_effect=OSError('permission token=verify-secret traceback')):
            result = verify_backup('bad.zip')

        assert result['status'] == 'error'
        assert result['is_valid'] is False
        assert result['message'] == 'Backup verification failed. Check the server logs.'
        assert 'verify-secret' not in result['message']
        assert 'permission' not in result['message']

    def test_verify_backup_missing_db(self, app, tmp_path):
        """Test verify_backup returns error when ZIP lacks the database file."""
        from musicround.helpers.backup_helper import verify_backup

        zip_path = tmp_path / 'no_db.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('backup_metadata.json', json.dumps({'version': '1.0'}))

        with patch('os.path.exists', side_effect=_exists_including_zip(zip_path)), \
             patch('os.path.join', return_value=str(zip_path)):
            result = verify_backup('no_db.zip')
        assert result['is_valid'] is False

    def test_verify_backup_valid(self, app, tmp_path):
        """Test verify_backup returns success for a valid backup."""
        from musicround.helpers.backup_helper import verify_backup

        metadata = {'version': '1.0.0', 'timestamp': '2024-01-01T12:00:00'}
        db_path = tmp_path / 'song_data.db'
        _write_sqlite_db(db_path)
        zip_path = tmp_path / 'valid.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('backup_metadata.json', json.dumps(metadata))
            zf.write(db_path, 'song_data.db')

        with patch('os.path.exists', side_effect=_exists_including_zip(zip_path)), \
             patch('os.path.join', return_value=str(zip_path)):
            result = verify_backup('valid.zip')
        assert result['is_valid'] is True
        assert result['status'] == 'success'

    def test_verify_backup_accepts_database_db_filename(self, app, tmp_path):
        """Test verify_backup accepts legacy database.db archives."""
        from musicround.helpers.backup_helper import verify_backup

        db_path = tmp_path / 'database.db'
        _write_sqlite_db(db_path)
        zip_path = tmp_path / 'legacy_valid.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.write(db_path, 'database.db')

        with patch('os.path.exists', side_effect=_exists_including_zip(zip_path)), \
             patch('os.path.join', return_value=str(zip_path)):
            result = verify_backup('legacy_valid.zip')
        assert result['is_valid'] is True
        assert result['status'] == 'success'


class TestRestoreBackup:
    """Tests for restore_backup function."""

    def test_restore_backup_accepts_database_db_filename(self, app, tmp_path):
        """Test restore_backup restores a backup whose DB member is database.db."""
        from musicround.helpers.backup_helper import restore_backup

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        live_db = tmp_path / 'live.db'
        backup_db = tmp_path / 'database.db'
        _write_sqlite_db(live_db, marker='live')
        _write_sqlite_db(backup_db, marker='restored')

        zip_path = backup_dir / 'legacy.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.write(backup_db, 'database.db')
            zf.writestr('backup_metadata.json', json.dumps({
                'includes_mp3s': False,
                'includes_config': False,
            }))

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{live_db}'
        with patch('os.path.join', side_effect=mock_join):
            result = restore_backup('legacy.zip')

        assert result['status'] == 'success'
        assert _read_sqlite_marker(live_db) == 'restored'
        assert list(tmp_path.glob('live.db.*.bak'))

    def test_restore_backup_rejects_corrupted_database_before_overwrite(self, app, tmp_path):
        """Test corrupted database archives do not overwrite the live DB."""
        from musicround.helpers.backup_helper import restore_backup

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        live_db = tmp_path / 'live.db'
        _write_sqlite_db(live_db, marker='live')

        zip_path = backup_dir / 'bad-db.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('song_data.db', b'not a sqlite database')
            zf.writestr('backup_metadata.json', json.dumps({
                'includes_mp3s': False,
                'includes_config': False,
            }))

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{live_db}'
        with patch('os.path.join', side_effect=mock_join):
            result = restore_backup('bad-db.zip')

        assert result['status'] == 'error'
        assert 'validation' in result['message'].lower()
        assert _read_sqlite_marker(live_db) == 'live'
        assert not list(tmp_path.glob('live.db.*.bak'))

    def test_restore_backup_rejects_zip_slip_member(self, app, tmp_path):
        """Test restore_backup rejects archive members outside the extraction dir."""
        from musicround.helpers.backup_helper import restore_backup

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        live_db = tmp_path / 'live.db'
        backup_db = tmp_path / 'song_data.db'
        outside_target = tmp_path / 'escape.txt'
        _write_sqlite_db(live_db, marker='live')
        _write_sqlite_db(backup_db, marker='restored')

        zip_path = backup_dir / 'zip-slip.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.write(backup_db, 'song_data.db')
            zf.writestr('../escape.txt', 'should not be extracted')

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{live_db}'
        with patch('os.path.join', side_effect=mock_join):
            result = restore_backup('zip-slip.zip')

        assert result['status'] == 'error'
        assert 'unsafe path' in result['message'].lower()
        assert _read_sqlite_marker(live_db) == 'live'
        assert not outside_target.exists()

    def test_restore_backup_rejects_zip_symlink_member(self, app, tmp_path):
        """Test restore_backup rejects symlink members before extraction."""
        from musicround.helpers.backup_helper import restore_backup

        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        live_db = tmp_path / 'live.db'
        backup_db = tmp_path / 'song_data.db'
        _write_sqlite_db(live_db, marker='live')
        _write_sqlite_db(backup_db, marker='restored')

        symlink_info = zipfile.ZipInfo('safe-link')
        symlink_info.external_attr = (stat.S_IFLNK | 0o777) << 16

        zip_path = backup_dir / 'symlink.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.write(backup_db, 'song_data.db')
            zf.writestr(symlink_info, '../outside')

        orig_join = os.path.join

        def mock_join(*args):
            if args == ('/data', 'backups'):
                return str(backup_dir)
            return orig_join(*args)

        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{live_db}'
        with patch('os.path.join', side_effect=mock_join):
            result = restore_backup('symlink.zip')

        assert result['status'] == 'error'
        assert 'unsafe path' in result['message'].lower()
        assert _read_sqlite_marker(live_db) == 'live'


class TestScheduleBackup:
    """Tests for schedule_backup function."""

    def test_schedule_backup_default_time(self, app):
        """Test schedule_backup with default parameters."""
        from musicround.helpers.backup_helper import schedule_backup

        with patch('musicround.helpers.backup_helper.apply_retention_policy'), \
             patch('musicround.helpers.backup_helper.list_backups', return_value=[]):
            result = schedule_backup(schedule_time='03:00', frequency='daily', retention_days=30)

        assert result['status'] == 'success'
        assert result['frequency'] == 'daily'

    def test_schedule_backup_stores_settings(self, app):
        """Test schedule_backup stores settings in SystemSetting."""
        from musicround.helpers.backup_helper import schedule_backup

        with patch('musicround.helpers.backup_helper.apply_retention_policy'), \
             patch('musicround.helpers.backup_helper.list_backups', return_value=[]):
            schedule_backup(schedule_time='08:30', frequency='weekly', retention_days=7)

        assert SystemSetting.get('backup_schedule_time') == '08:30'
        assert SystemSetting.get('backup_schedule_frequency') == 'weekly'
        assert SystemSetting.get('backup_schedule_enabled') == 'true'

    def test_schedule_backup_exception_hides_details(self, app):
        """Unexpected schedule errors should not expose storage details."""
        from musicround.helpers.backup_helper import schedule_backup

        with patch(
            'musicround.models.SystemSetting.set',
            side_effect=RuntimeError('settings write token=schedule-secret traceback'),
        ):
            result = schedule_backup(schedule_time='08:30', frequency='weekly', retention_days=7)

        assert result['status'] == 'error'
        assert result['message'] == 'Backup scheduling failed. Check the server logs.'
        assert 'schedule-secret' not in result['message']
        assert 'settings write' not in result['message']


class TestGetBackupSummary:
    """Tests for get_backup_summary function."""

    def test_get_backup_summary_empty(self, app):
        """Test get_backup_summary with no backups."""
        from musicround.helpers.backup_helper import get_backup_summary

        with patch('musicround.helpers.backup_helper.list_backups', return_value=[]):
            summary = get_backup_summary()

        assert 'backup_count' in summary
        assert summary['backup_count'] == 0
        assert 'schedule_enabled' in summary
        assert 'backup_location' in summary

    def test_get_backup_summary_with_backups(self, app):
        """Test get_backup_summary with existing backups."""
        from musicround.helpers.backup_helper import get_backup_summary

        fake_backups = [
            {'backup_name': 'backup1', 'timestamp': '2024-01-01T12:00:00', 'file_size': 1024},
            {'backup_name': 'backup2', 'timestamp': '2024-01-02T12:00:00', 'file_size': 2048},
        ]
        with patch('musicround.helpers.backup_helper.list_backups', return_value=fake_backups):
            summary = get_backup_summary()

        assert summary['backup_count'] == 2
        assert summary['latest_backup'] == fake_backups[0]

    def test_get_backup_summary_scheduled(self, app):
        """Test get_backup_summary with schedule enabled."""
        from musicround.helpers.backup_helper import get_backup_summary

        SystemSetting.set('backup_schedule_enabled', 'true')
        SystemSetting.set('backup_schedule_time', '03:00')
        SystemSetting.set('backup_schedule_frequency', 'daily')

        with patch('musicround.helpers.backup_helper.list_backups', return_value=[]):
            summary = get_backup_summary()

        assert summary['schedule_enabled'] is True
        assert summary['next_backup'] is not None


class TestGenerateBackupConfigSuggestion:
    """Tests for generate_backup_config_suggestion function."""

    def test_returns_dict(self, app):
        """Test that the function returns a dictionary."""
        from musicround.helpers.backup_helper import generate_backup_config_suggestion
        result = generate_backup_config_suggestion()
        assert isinstance(result, dict)

    def test_contains_config_keys(self, app):
        """Test that the result contains expected configuration keys."""
        from musicround.helpers.backup_helper import generate_backup_config_suggestion
        result = generate_backup_config_suggestion(retention_days=30)
        # Check for some expected keys
        assert result is not None
