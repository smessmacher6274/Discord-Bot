import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from spotify_export import (SpotifyClient, ExportError, playlist_id, authorization_url,
                            callback_code, fetch_playlist, write_export, MAX_FILE_BYTES)
from music.playlist_import import import_playlist

ID = 'A' * 22
TRACK_ID = 'B' * 22

def item(name='Song', **extra):
    return {'type': 'track', 'id': TRACK_ID, 'name': name,
            'artists': [{'name': 'Artist'}, {'name': 'Collaborator'}], **extra}

class SpotifyExportTests(unittest.TestCase):
    def test_playlist_url_validation(self):
        for value in [ID, 'spotify:playlist:' + ID, 'https://open.spotify.com/playlist/' + ID + '?si=abc',
                      'https://open.spotify.com/intl-en/playlist/' + ID]:
            self.assertEqual(playlist_id(value), ID)
        for value in ['https://open.spotify.com.evil.test/playlist/' + ID,
                      'https://user@open.spotify.com/playlist/' + ID, 'http://open.spotify.com/playlist/' + ID,
                      'https://open.spotify.com/track/' + ID, 'bad', 'spotify:playlist:../../secret']:
            with self.assertRaises(ExportError):
                playlist_id(value)

    def test_pkce_challenge_and_read_only_scopes(self):
        query = parse_qs(urlsplit(authorization_url('C' * 32,
            'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk', 'state')).query)
        self.assertEqual(query['code_challenge'], ['E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotIn('client_secret', query)
        self.assertEqual(query['scope'], ['playlist-read-private playlist-read-collaborative'])

    def test_callback_state_and_denial(self):
        self.assertEqual(callback_code('/callback?state=right&code=abc', 'right'), 'abc')
        for path in ['/callback?state=wrong&code=abc', '/callback?state=right&error=access_denied',
                     '/callback?state=right', '/else?state=right&code=abc',
                     '/callback?state=right&state=wrong&code=abc']:
            with self.assertRaises(ExportError):
                callback_code(path, 'right')

    def test_paging_order_duplicates_and_skips(self):
        client = MagicMock()
        metadata = {'name': 'My songs', 'snapshot_id': 'stable'}
        client.get.side_effect = [metadata,
            {'items': [{'item': item('First')}, {'item': None}, {'track': item('First')}], 'next': 'https://evil.test'},
            {'items': [{'item': item('Second')}, {'item': {'type': 'episode'}},
                       {'item': item('Local'), 'is_local': True}], 'next': None}, metadata]
        name, rows, skipped, source = fetch_playlist(client, ID)
        self.assertEqual([r['title'] for r in rows], ['First', 'First', 'Second'])
        self.assertEqual([r['playlist_position'] for r in rows], [1, 3, 4])
        self.assertEqual(rows[0]['artists'], ['Artist', 'Collaborator'])
        self.assertEqual(len(skipped), 3)
        self.assertIn('/items?limit=50&offset=3', client.get.call_args_list[2].args[0])

    def test_changed_playlist_rejected(self):
        client = MagicMock()
        client.get.side_effect = [{'snapshot_id': 'before'}, {'items': [], 'next': None}, {'snapshot_id': 'after'}]
        with self.assertRaisesRegex(ExportError, 'changed'):
            fetch_playlist(client, ID)

    @patch('spotify_export.time.sleep')
    @patch('spotify_export.http_json')
    def test_refresh_and_rate_limit(self, request, sleep):
        client = SpotifyClient('id', {'access_token': 'old', 'refresh_token': 'refresh'})
        request.side_effect = [HTTPError('url', 401, 'expired', {}, None),
                              {'access_token': 'new'}, HTTPError('url', 429, 'limited', {'Retry-After': '2'}, None),
                              {'items': []}]
        self.assertEqual(client.get('/playlists/' + ID), {'items': []})
        self.assertEqual(client.tokens['access_token'], 'new')
        sleep.assert_called_once_with(2)
        self.assertEqual(request.call_args.kwargs['token'], 'new')

    @patch('spotify_export.http_json')
    def test_access_failure_is_actionable_and_sanitized(self, request):
        request.side_effect = HTTPError('url', 403, 'token=secret', {}, None)
        with self.assertRaisesRegex(ExportError, 'own or collaborate') as context:
            SpotifyClient('id', {'access_token': 'private'}).get('/playlists/' + ID)
        self.assertNotIn('secret', str(context.exception))

    def test_export_chunks_are_importable(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            rows = [{'title': 'Song', 'artist': 'Artist', 'spotify_url': 'https://open.spotify.com/track/' + TRACK_ID}] * 501
            paths, report = write_export(ID, 'Playlist', rows, [], 'source', directory)
            self.assertEqual(len(paths), 2)
            self.assertEqual([len(json.loads(p.read_text())) for p in paths], [500, 1])
            for path in paths:
                self.assertLessEqual(path.stat().st_size, MAX_FILE_BYTES)
                imported = import_playlist(path.read_bytes(), path.name, MagicMock(tracks={}), 1, youtube_fallback=True)
                self.assertTrue(imported.tracks)
            self.assertTrue(report.exists())

    def test_txt_export_and_empty_playlist(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            paths, _ = write_export(ID, 'Playlist', [{'title': 'Song', 'artist': 'Artist'}], [], 'source', directory, 'txt')
            self.assertEqual(paths[0].read_text(), 'Artist - Song\n')
            with self.assertRaises(ExportError):
                write_export(ID, 'Empty', [], [], 'source', directory)
