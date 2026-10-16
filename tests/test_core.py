import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from music.queue_manager import GuildQueue
from music.resolver import Resolver
from providers.licensed_audio import LicensedAudio

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'a.wav').touch()
        self.data = {'tracks': [{'id': 'a', 'title': 'Song', 'artist': 'Artist', 'file': 'a.wav', 'authorized': True}],
                     'playlists': {'list': ['a', 'a']}}

    def provider(self):
        catalog = self.root / 'catalog.json'
        catalog.write_text(json.dumps(self.data))
        return LicensedAudio(catalog, self.root)

    def test_playlist_order_and_requester(self):
        tracks = Resolver(self.provider()).resolve('playlist:list', 42)
        self.assertEqual([t.title for t in tracks], ['Song', 'Song'])
        self.assertEqual(tracks[0].requested_by, 42)

    def test_unavailable_and_spotify(self):
        resolver = Resolver(self.provider())
        for query in ['missing', 'https://open.spotify.com/track/123', 'https://example.com/a.mp3', '']:
            with self.assertRaises(ValueError):
                resolver.resolve(query, 1)

    def test_path_escape_and_authorization(self):
        for field, value in [('file', '../outside.wav'), ('authorized', False)]:
            original = self.data['tracks'][0][field]
            self.data['tracks'][0][field] = value
            with self.assertRaises(ValueError):
                self.provider()
            self.data['tracks'][0][field] = original

    def test_queue_indices_and_isolation(self):
        first, second = GuildQueue(), GuildQueue()
        first.current = 'playing'
        first.upcoming.extend(['a', 'b', 'c'])
        self.assertEqual(first.remove(2), 'b')
        with self.assertRaises(ValueError):
            first.remove(0)
        first.upcoming.clear()
        self.assertEqual(first.current, 'playing')
        self.assertEqual(list(second.upcoming), [])

    def test_concurrent_mutations(self):
        async def scenario():
            q = GuildQueue()
            async def append(n):
                async with q.lock:
                    q.upcoming.extend([n, n])
            await asyncio.gather(*(append(n) for n in range(100)))
            self.assertEqual(len(q.upcoming), 200)
            items = list(q.upcoming)
            self.assertTrue(all(items[i] == items[i + 1] for i in range(0, 200, 2)))
        asyncio.run(scenario())
