"""Tests for browser text playlist review and round creation."""

from musicround.models import Round, Song, User, db


def _login(app, client, username='textimporter', email='textimporter@example.test'):
    with app.app_context():
        if not User.query.filter_by(username=username).first():
            user = User(username=username, email=email)
            user.password = 'TextImportPass123!'
            db.session.add(user)
            db.session.commit()
    client.post('/users/login', data={'username': username, 'password': 'TextImportPass123!'})


def _create_song(title, artist):
    song = Song(title=title, artist=artist, preview_url=f'https://example.test/{title}.mp3')
    db.session.add(song)
    db.session.commit()
    return song


def test_text_playlist_review_requires_login(client):
    response = client.get('/import-text-playlist')

    assert response.status_code == 302
    assert 'login' in response.headers['Location'].lower()


def test_text_playlist_review_shows_unresolved_rows(app, client):
    _login(app, client)
    with app.app_context():
        _create_song('Known Song', 'Known Artist')

    response = client.post(
        '/import-text-playlist',
        data={
            'action': 'review',
            'round_name': 'Needs Review',
            'playlist_text': 'Known Artist - Known Song\nMissing Artist - Missing Song',
        },
    )

    assert response.status_code == 200
    assert b'1 resolved' in response.data
    assert b'1 unresolved' in response.data
    assert b'Review required before this can become a round.' in response.data
    assert b'Missing Artist - Missing Song' in response.data
    assert b'name="action" value="create"' not in response.data


def test_text_playlist_review_blocks_wrong_song_count(app, client):
    _login(app, client)
    with app.app_context():
        _create_song('One', 'A')
        _create_song('Two', 'B')

    response = client.post(
        '/import-text-playlist',
        data={
            'action': 'create',
            'round_name': 'Too Short',
            'playlist_text': 'A - One\nB - Two',
        },
    )

    assert response.status_code == 200
    assert b'Text playlist resolved 2 songs; expected exactly 8.' in response.data
    with app.app_context():
        assert Round.query.count() == 0


def test_text_playlist_create_redirects_to_round_detail(app, client):
    _login(app, client)
    with app.app_context():
        for index in range(8):
            _create_song(f'Title {index}', f'Artist {index}')

    playlist_text = '\n'.join(f'Artist {index} - Title {index}' for index in range(8))
    response = client.post(
        '/import-text-playlist',
        data={
            'action': 'create',
            'round_name': 'Text Import Round',
            'playlist_text': playlist_text,
        },
    )

    assert response.status_code == 302
    assert '/rounds/' in response.headers['Location']
    with app.app_context():
        round_ = Round.query.one()
        assert round_.name == 'Text Import Round'
        assert round_.user_id is not None
        assert round_.visibility == 'private'
        assert len(round_.song_id_list) == 8
