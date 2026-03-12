"""Tests for database models."""
import pytest
from datetime import datetime, timedelta
from musicround.models import (
    db, User, Role, UserPreferences, Tag, SongTag, Song,
    Round, RoundExport, SystemSetting, ImportJobRecord,
)


class TestRoleModel:
    """Tests for the Role model."""

    def test_role_creation(self, app):
        """Test basic role creation and persistence."""
        role = Role(name='admin', description='Administrator role')
        db.session.add(role)
        db.session.commit()

        fetched = Role.query.filter_by(name='admin').first()
        assert fetched is not None
        assert fetched.name == 'admin'
        assert fetched.description == 'Administrator role'

    def test_role_repr(self, app):
        """Test Role __repr__."""
        role = Role(name='editor', description='Editor')
        db.session.add(role)
        db.session.commit()
        assert 'editor' in repr(role)
        assert 'Role' in repr(role)

    def test_role_unique_name(self, app):
        """Test that role names must be unique."""
        from sqlalchemy.exc import IntegrityError
        role1 = Role(name='unique_role')
        role2 = Role(name='unique_role')
        db.session.add(role1)
        db.session.commit()
        db.session.add(role2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestUserModel:
    """Tests for the User model."""

    def test_user_creation(self, app):
        """Test basic user creation."""
        user = User(username='john', email='john@example.com')
        user.password = 'SecurePass123!'
        db.session.add(user)
        db.session.commit()

        fetched = User.query.filter_by(username='john').first()
        assert fetched is not None
        assert fetched.email == 'john@example.com'
        assert fetched.active is True
        assert fetched.is_admin is False

    def test_password_hashing(self, app):
        """Test that passwords are hashed on assignment."""
        user = User(username='hashtest', email='hash@example.com')
        user.password = 'MySecret!'
        assert user.password_hash is not None
        assert user.password_hash != 'MySecret!'

    def test_password_check_correct(self, app):
        """Test check_password returns True for correct password."""
        user = User(username='passtest', email='pass@example.com')
        user.password = 'CorrectPassword!'
        assert user.check_password('CorrectPassword!') is True

    def test_password_check_incorrect(self, app):
        """Test check_password returns False for wrong password."""
        user = User(username='wrongpass', email='wrong@example.com')
        user.password = 'CorrectPassword!'
        assert user.check_password('WrongPassword') is False

    def test_password_check_no_hash(self, app):
        """Test check_password returns False when no hash is set."""
        user = User(username='nohash', email='nohash@example.com')
        user.password_hash = None
        assert user.check_password('anything') is False

    def test_password_getter_raises(self, app):
        """Test that reading the password attribute raises AttributeError."""
        user = User(username='readonly', email='read@example.com')
        user.password = 'secret'
        with pytest.raises(AttributeError):
            _ = user.password

    def test_set_token(self, app):
        """Test that set_token generates a unique reset token."""
        user = User(username='tokentest', email='token@example.com')
        token = user.set_token()
        assert token is not None
        assert len(token) > 0
        assert user.reset_token == token

    def test_set_token_is_unique(self, app):
        """Test that two consecutive tokens are different."""
        user = User(username='uniquetoken', email='unique@example.com')
        token1 = user.set_token()
        token2 = user.set_token()
        assert token1 != token2

    def test_has_role_true(self, app):
        """Test has_role returns True when user has the role."""
        role = Role(name='moderator')
        user = User(username='modrole', email='mod@example.com')
        user.roles.append(role)
        db.session.add_all([role, user])
        db.session.commit()
        assert user.has_role('moderator') is True

    def test_has_role_false(self, app):
        """Test has_role returns False when user does not have the role."""
        user = User(username='norole', email='norole@example.com')
        db.session.add(user)
        db.session.commit()
        assert user.has_role('admin') is False

    def test_is_admin_by_role(self, app):
        """Test is_admin_by_role checks roles correctly."""
        admin_role = Role(name='admin')
        admin_user = User(username='roleadmin', email='roleadmin@example.com')
        admin_user.roles.append(admin_role)
        normal_user = User(username='normalrole', email='normalrole@example.com')
        db.session.add_all([admin_role, admin_user, normal_user])
        db.session.commit()

        assert admin_user.is_admin_by_role() is True
        assert normal_user.is_admin_by_role() is False

    def test_user_repr(self, app):
        """Test User __repr__."""
        user = User(username='reprtest', email='repr@example.com')
        db.session.add(user)
        db.session.commit()
        assert 'reprtest' in repr(user)
        assert 'User' in repr(user)

    def test_user_defaults(self, app):
        """Test that User model defaults are applied correctly."""
        user = User(username='defaults', email='defaults@example.com')
        db.session.add(user)
        db.session.commit()
        assert user.active is True
        assert user.is_admin is False
        assert user.auth_provider == 'local'
        assert user.dropbox_export_path == '/QuizzicalBeats'


class TestUserPreferencesModel:
    """Tests for the UserPreferences model."""

    def test_preferences_creation(self, app):
        """Test UserPreferences creation with defaults."""
        user = User(username='prefuser', email='pref@example.com')
        db.session.add(user)
        db.session.commit()

        prefs = UserPreferences(user_id=user.id)
        db.session.add(prefs)
        db.session.commit()

        fetched = UserPreferences.query.filter_by(user_id=user.id).first()
        assert fetched is not None
        assert fetched.default_tts_service == 'polly'
        assert fetched.enable_intro is True
        assert fetched.theme == 'light'

    def test_preferences_relationship(self, app):
        """Test that User.preferences relationship works."""
        user = User(username='reluser', email='rel@example.com')
        db.session.add(user)
        db.session.commit()

        prefs = UserPreferences(user_id=user.id, theme='dark')
        db.session.add(prefs)
        db.session.commit()

        db.session.refresh(user)
        assert user.preferences is not None
        assert user.preferences.theme == 'dark'


class TestTagModel:
    """Tests for the Tag model."""

    def test_tag_creation(self, app):
        """Test basic Tag creation."""
        tag = Tag(name='rock')
        db.session.add(tag)
        db.session.commit()

        fetched = Tag.query.filter_by(name='rock').first()
        assert fetched is not None
        assert fetched.name == 'rock'

    def test_tag_repr(self, app):
        """Test Tag __repr__."""
        tag = Tag(name='pop')
        db.session.add(tag)
        db.session.commit()
        assert 'pop' in repr(tag)
        assert 'Tag' in repr(tag)

    def test_tag_unique_name(self, app):
        """Test that tag names must be unique."""
        from sqlalchemy.exc import IntegrityError
        tag1 = Tag(name='unique_tag')
        tag2 = Tag(name='unique_tag')
        db.session.add(tag1)
        db.session.commit()
        db.session.add(tag2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestSongModel:
    """Tests for the Song model."""

    def _make_song(self, **kwargs):
        """Helper to create a valid Song instance."""
        defaults = {
            'title': 'Test Song',
            'artist': 'Test Artist',
            'genre': 'Rock',
            'year': 2000,
        }
        defaults.update(kwargs)
        return Song(**defaults)

    def test_song_creation(self, app):
        """Test basic Song creation."""
        song = self._make_song(
            title='Bohemian Rhapsody',
            artist='Queen',
            spotify_id='abc123',
        )
        db.session.add(song)
        db.session.commit()

        fetched = Song.query.filter_by(title='Bohemian Rhapsody').first()
        assert fetched is not None
        assert fetched.artist == 'Queen'

    def test_song_repr(self, app):
        """Test Song __repr__."""
        song = self._make_song(title='Repr Song', artist='Repr Artist')
        db.session.add(song)
        db.session.commit()
        r = repr(song)
        assert 'Repr Song' in r
        assert 'Repr Artist' in r

    def test_song_to_dict(self, app):
        """Test Song.to_dict() returns expected keys."""
        song = self._make_song(
            title='Dict Song',
            artist='Dict Artist',
            album_name='Dict Album',
            cover_url='http://example.com/cover.jpg',
            preview_url='http://example.com/preview.mp3',
            spotify_id='spotify123',
            deezer_id=456,
            isrc='TEST1234567',
            year=1995,
            genre='Jazz',
            popularity=75,
        )
        db.session.add(song)
        db.session.commit()

        d = song.to_dict()
        assert d['title'] == 'Dict Song'
        assert d['artist'] == 'Dict Artist'
        assert d['album_name'] == 'Dict Album'
        assert d['cover_url'] == 'http://example.com/cover.jpg'
        assert d['preview_url'] == 'http://example.com/preview.mp3'
        assert d['spotify_id'] == 'spotify123'
        assert d['isrc'] == 'TEST1234567'
        assert d['year'] == 1995
        assert d['genre'] == 'Jazz'
        assert d['popularity'] == 75
        assert d['last_used'] is None
        # Audio feature keys present
        for key in ('acousticness', 'danceability', 'energy', 'tempo', 'valence'):
            assert key in d

    def test_song_to_dict_with_last_used(self, app):
        """Test Song.to_dict() formats last_used correctly."""
        song = self._make_song(title='LastUsed Song', artist='Artist')
        song.last_used = datetime(2024, 6, 15, 12, 0, 0)
        db.session.add(song)
        db.session.commit()

        d = song.to_dict()
        assert d['last_used'] == '2024-06-15 12:00:00'

    def test_song_tags_relationship(self, app):
        """Test Song-Tag many-to-many relationship."""
        song = self._make_song(title='Tagged Song', artist='Artist')
        tag = Tag(name='tagged_rock')
        db.session.add_all([song, tag])
        db.session.commit()

        song.tags.append(tag)
        db.session.commit()

        fetched = Song.query.filter_by(title='Tagged Song').first()
        assert len(fetched.tags) == 1
        assert fetched.tags[0].name == 'tagged_rock'

        d = fetched.to_dict()
        assert len(d['tags']) == 1
        assert d['tags'][0]['name'] == 'tagged_rock'

    def test_song_defaults(self, app):
        """Test Song model default values."""
        song = self._make_song()
        db.session.add(song)
        db.session.commit()
        assert song.used_count == 0
        assert song.source == 'spotify'


class TestRoundModel:
    """Tests for the Round model."""

    def _make_songs(self, count=3):
        """Helper to create and persist Song objects."""
        songs = []
        for i in range(count):
            song = Song(title=f'Round Song {i}', artist='Band', genre='Pop')
            db.session.add(song)
            songs.append(song)
        db.session.commit()
        return songs

    def test_round_creation(self, app):
        """Test Round creation with required fields."""
        songs = self._make_songs()
        song_ids = ','.join(str(s.id) for s in songs)

        round_ = Round(
            name='My Quiz Round',
            round_type='genre',
            round_criteria_used='Rock',
            songs=song_ids,
            genre='Rock',
        )
        db.session.add(round_)
        db.session.commit()

        fetched = Round.query.filter_by(name='My Quiz Round').first()
        assert fetched is not None
        assert fetched.round_type == 'genre'

    def test_round_repr(self, app):
        """Test Round __repr__."""
        songs = self._make_songs(1)
        round_ = Round(
            name='Repr Round',
            round_type='decade',
            round_criteria_used='1980s',
            songs=str(songs[0].id),
        )
        db.session.add(round_)
        db.session.commit()
        assert 'Repr Round' in repr(round_)

    def test_round_reset_generated_status(self, app):
        """Test reset_generated_status sets mp3_generated and pdf_generated to False."""
        songs = self._make_songs(1)
        round_ = Round(
            round_type='genre',
            round_criteria_used='Pop',
            songs=str(songs[0].id),
            mp3_generated=True,
            pdf_generated=True,
        )
        db.session.add(round_)
        db.session.commit()

        round_.reset_generated_status()
        assert round_.mp3_generated is False
        assert round_.pdf_generated is False

    def test_round_song_list(self, app):
        """Test Round.song_list property returns the correct Song objects."""
        songs = self._make_songs(2)
        song_ids = ','.join(str(s.id) for s in songs)
        round_ = Round(
            round_type='genre',
            round_criteria_used='Pop',
            songs=song_ids,
        )
        db.session.add(round_)
        db.session.commit()

        result = round_.song_list
        assert len(result) == 2
        result_ids = {s.id for s in result}
        assert result_ids == {s.id for s in songs}

    def test_round_defaults(self, app):
        """Test Round model default values."""
        songs = self._make_songs(1)
        round_ = Round(
            round_type='genre',
            round_criteria_used='Rock',
            songs=str(songs[0].id),
        )
        db.session.add(round_)
        db.session.commit()
        assert round_.mp3_generated is False
        assert round_.pdf_generated is False


class TestRoundExportModel:
    """Tests for the RoundExport model."""

    def test_round_export_creation(self, app):
        """Test RoundExport creation."""
        songs = [Song(title='Export Song', artist='Artist', genre='Pop')]
        db.session.add_all(songs)
        db.session.commit()

        round_ = Round(
            round_type='genre', round_criteria_used='Pop',
            songs=str(songs[0].id),
        )
        user = User(username='exportuser', email='export@example.com')
        db.session.add_all([round_, user])
        db.session.commit()

        export = RoundExport(
            round_id=round_.id,
            user_id=user.id,
            export_type='dropbox',
            destination='/QuizzicalBeats',
            status='success',
        )
        db.session.add(export)
        db.session.commit()

        fetched = RoundExport.query.filter_by(round_id=round_.id).first()
        assert fetched is not None
        assert fetched.export_type == 'dropbox'
        assert fetched.status == 'success'

    def test_round_export_repr(self, app):
        """Test RoundExport __repr__."""
        songs = [Song(title='Repr Export Song', artist='Artist', genre='Pop')]
        db.session.add_all(songs)
        db.session.commit()
        round_ = Round(round_type='genre', round_criteria_used='Pop', songs=str(songs[0].id))
        db.session.add(round_)
        db.session.commit()
        export = RoundExport(round_id=round_.id, export_type='email', status='failed')
        db.session.add(export)
        db.session.commit()
        assert 'RoundExport' in repr(export)


class TestSystemSettingModel:
    """Tests for the SystemSetting model."""

    def test_set_and_get(self, app):
        """Test SystemSetting.set() and SystemSetting.get()."""
        SystemSetting.set('site_title', 'Quizzical Beats')
        value = SystemSetting.get('site_title')
        assert value == 'Quizzical Beats'

    def test_get_missing_key(self, app):
        """Test SystemSetting.get() returns default for missing key."""
        value = SystemSetting.get('nonexistent_key', default='fallback')
        assert value == 'fallback'

    def test_get_missing_key_none_default(self, app):
        """Test SystemSetting.get() returns None by default for missing key."""
        value = SystemSetting.get('another_missing_key')
        assert value is None

    def test_update_existing_setting(self, app):
        """Test that SystemSetting.set() updates an existing setting."""
        SystemSetting.set('update_key', 'initial_value')
        SystemSetting.set('update_key', 'updated_value')
        assert SystemSetting.get('update_key') == 'updated_value'

    def test_all_settings(self, app):
        """Test SystemSetting.all_settings() returns all key-value pairs."""
        SystemSetting.set('key_a', 'value_a')
        SystemSetting.set('key_b', 'value_b')
        settings = SystemSetting.all_settings()
        assert settings.get('key_a') == 'value_a'
        assert settings.get('key_b') == 'value_b'


class TestImportJobRecordModel:
    """Tests for the ImportJobRecord model."""

    def _make_user(self):
        user = User(username='importuser', email='importjob@example.com')
        db.session.add(user)
        db.session.commit()
        return user

    def test_import_job_creation(self, app):
        """Test ImportJobRecord creation."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='spotify',
            item_type='playlist',
            item_id='playlist123',
            user_id=user.id,
            priority=5,
        )
        db.session.add(job)
        db.session.commit()

        fetched = ImportJobRecord.query.filter_by(item_id='playlist123').first()
        assert fetched is not None
        assert fetched.status == 'pending'
        assert fetched.imported_count == 0

    def test_import_job_repr(self, app):
        """Test ImportJobRecord __repr__."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='deezer', item_type='album',
            item_id='album456', user_id=user.id, priority=10,
        )
        db.session.add(job)
        db.session.commit()
        r = repr(job)
        assert 'deezer' in r
        assert 'album456' in r

    def test_duration_none_when_incomplete(self, app):
        """Test duration property returns None when job is not completed."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='spotify', item_type='track',
            item_id='track789', user_id=user.id, priority=10,
        )
        db.session.add(job)
        db.session.commit()
        assert job.duration is None

    def test_duration_calculated(self, app):
        """Test duration property calculates seconds correctly."""
        user = self._make_user()
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 45)
        job = ImportJobRecord(
            service_name='spotify', item_type='track',
            item_id='track_dur', user_id=user.id, priority=10,
            started_at=start, completed_at=end,
        )
        db.session.add(job)
        db.session.commit()
        assert job.duration == 45.0

    def test_item_url_spotify_playlist(self, app):
        """Test item_url for Spotify playlist."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='spotify', item_type='playlist',
            item_id='myplaylist', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://open.spotify.com/playlist/myplaylist'

    def test_item_url_spotify_album(self, app):
        """Test item_url for Spotify album."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='spotify', item_type='album',
            item_id='myalbum', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://open.spotify.com/album/myalbum'

    def test_item_url_spotify_track(self, app):
        """Test item_url for Spotify track."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='spotify', item_type='track',
            item_id='mytrack', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://open.spotify.com/track/mytrack'

    def test_item_url_deezer_playlist(self, app):
        """Test item_url for Deezer playlist."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='deezer', item_type='playlist',
            item_id='deezerplist', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://www.deezer.com/playlist/deezerplist'

    def test_item_url_deezer_album(self, app):
        """Test item_url for Deezer album."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='deezer', item_type='album',
            item_id='deezeralbum', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://www.deezer.com/album/deezeralbum'

    def test_item_url_deezer_track(self, app):
        """Test item_url for Deezer track."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='deezer', item_type='track',
            item_id='deezertrack', user_id=user.id, priority=10,
        )
        assert job.item_url == 'https://www.deezer.com/track/deezertrack'

    def test_item_url_unknown_service(self, app):
        """Test item_url returns None for unknown service."""
        user = self._make_user()
        job = ImportJobRecord(
            service_name='unknown', item_type='playlist',
            item_id='something', user_id=user.id, priority=10,
        )
        assert job.item_url is None
