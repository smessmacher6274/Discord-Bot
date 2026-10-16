import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from music.playlist_import import import_playlist
from music.player import Player
from music.track import Track
from providers.youtube import choose_match

class SearchTests(unittest.TestCase):
    def test_matches_typo_and_reversed_order(self):
        entries = [{'id': 'dQw4w9WgXcQ', 'title': 'Rick Astley - Never Gonna Give You Up (Official Music Video)', 'uploader': 'Rick Astley'}]
        entry, title, artist = choose_match(entries, 'ric hastley', 'Never going to give you up', True)
        self.assertEqual(entry['id'], 'dQw4w9WgXcQ')
        self.assertEqual(artist, 'ric hastley')

    def test_artist_punctuation_and_official_preference(self):
        entries = [{'id': 'aaaaaaaaaaa', 'title': 'AC/DC - T.N.T.', 'uploader': 'Fan'},
                   {'id': 'bbbbbbbbbbb', 'title': 'AC/DC - T.N.T. (Official Audio)', 'uploader': 'AC/DC'}]
        entry, _, _ = choose_match(entries, 'TNT', 'ACDC')
        self.assertEqual(entry['id'], 'bbbbbbbbbbb')

    def test_rejects_unrelated_recordings_and_unrequested_versions(self):
        for title in ['Other Artist - Different Song', 'Artist - Song (Karaoke)', 'Artist - Song (Remix)']:
            with self.subTest(title=title), self.assertRaises(ValueError):
                choose_match([{'id': 'aaaaaaaaaaa', 'title': title}], 'Song', 'Artist')

    def test_collaborators_and_featured_artist(self):
        entries = [{'id': 'EkrxMfCKrGY', 'title': 'Black Tiger Sex Machine x Hairitage - Cheatcode ft. Hyro The Hero (Lyric Video)',
                    'uploader': 'Kannibalen Records'}]
        entry, _, _ = choose_match(entries, 'Cheatcode', 'Black Tiger Sex Machine')
        self.assertEqual(entry['id'], 'EkrxMfCKrGY')

    def test_import_queues_search_without_network_and_preserves_duplicates(self):
        provider = MagicMock(tracks={})
        result = import_playlist(b'Song - Artist\nSong - Artist', 'playlist.txt', provider, 42, youtube_fallback=True)
        self.assertEqual(len(result.tracks), 2)
        self.assertEqual(result.tracks[0].provider, 'youtube_search')
        self.assertTrue(json.loads(result.tracks[0].source_url)['allow_reverse'])
        self.assertEqual(result.tracks[0].requested_by, 42)
        provider.search.assert_not_called()

    def test_explicit_json_order(self):
        result = import_playlist(b'[{"title":"Song","artist":"Artist"}]', 'list.json',
                                 MagicMock(tracks={}), 1, youtube_fallback=True)
        self.assertFalse(json.loads(result.tracks[0].source_url)['allow_reverse'])

class SearchPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_match_advances_to_next_track(self):
        provider = MagicMock()
        provider.prepare_track.side_effect = ValueError('No confident match')
        player = Player(provider, 'ffmpeg')
        player.voice = MagicMock()
        player.voice.is_connected.return_value = True
        player.voice.play.side_effect = lambda source, after: after(None)
        player.upcoming.extend([
            Track('Missing', 'Artist', None, '{}', '', provider='youtube_search'),
            Track('Found', 'Artist', 1, 'local:a', 'a.wav')])
        notify = AsyncMock()
        with self.assertLogs(level='ERROR'), patch('music.player.discord.FFmpegPCMAudio'), patch('music.player.discord.PCMVolumeTransformer'):
            await player.run(notify)
        self.assertIn('No confident match', notify.call_args.args[0])
        player.voice.play.assert_called_once()
        self.assertIsNone(player.current)
