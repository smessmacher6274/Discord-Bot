import unittest
from types import SimpleNamespace
from music.track import Track
from music.playlist_import import import_playlist, MAX_BYTES

class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.provider = SimpleNamespace(tracks={
            'a': Track('Song A', 'Artist', 5, 'local:a', 'a.wav'),
            'b': Track('Song B', 'Artist', 5, 'local:b', 'b.wav')})

    def test_order_duplicates_and_unavailable(self):
        result = import_playlist(b'Artist - Song B\nArtist - Missing\nartist - song a\nArtist - Song B',
                                 'list.txt', self.provider, 42)
        self.assertEqual([t.title for t in result.tracks], ['Song B', 'Song A', 'Song B'])
        self.assertEqual(result.tracks[0].requested_by, 42)
        self.assertEqual(len(result.unavailable), 1)

    def test_exact_matching_and_ambiguity(self):
        self.provider.tracks['duplicate'] = self.provider.tracks['a']
        result = import_playlist(b'Artist - Song A\nArtist - Song', 'list.txt', self.provider, 1)
        self.assertEqual(result.tracks, [])
        self.assertIn('ambiguous', result.unavailable[0])
        self.assertIn('unavailable', result.unavailable[1])

    def test_json_and_utf8_bom(self):
        result = import_playlist(b'\xef\xbb\xbf[{"title":"Song A","artist":"Artist"}]', 'list.json', self.provider, 1)
        self.assertEqual(len(result.tracks), 1)

    def test_invalid_inputs(self):
        for data, name in [(b'bad', 'a.txt'), (b'{}', 'a.json'), (b'[{}]', 'a.json'),
                           (b'[]', 'a.json'), (b'\xff', 'a.txt'), (b'bad', 'a.exe'),
                           (b'x' * (MAX_BYTES + 1), 'a.txt'),
                           (b'Artist - Song A\n' * 501, 'a.txt')]:
            with self.subTest(name=name, length=len(data)), self.assertRaises(ValueError):
                import_playlist(data, name, self.provider, 1)
