import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from music.spotify_session import SpotifySession, PlaylistExport
from spotify_export import ExportError
import main

ID = 'A' * 22
LINK = 'https://open.spotify.com/playlist/' + ID

class SpotifySessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorizes_once_and_forgets_tokens(self):
        client = MagicMock(tokens={'access_token': 'private'})
        session = SpotifySession('C' * 32)
        with patch('music.spotify_session.authorize', return_value=client) as authorize, \
             patch('music.spotify_session.fetch_playlist', return_value=('Playlist', [{'title': 'Song', 'artist': 'Artist'}], [], LINK)):
            first = await session.export(LINK)
            await session.export(LINK)
        authorize.assert_called_once()
        self.assertEqual(first.count, 1)
        self.assertEqual(len(first.files), 2)
        await session.disconnect()
        self.assertEqual(client.tokens, {})
        self.assertIsNone(session.client)

    async def test_invalid_requests_do_not_authorize(self):
        with patch('music.spotify_session.authorize') as authorize:
            with self.assertRaises(ExportError):
                await SpotifySession('').export(LINK)
            with self.assertRaises(ExportError):
                await SpotifySession('C' * 32).export('http://localhost/secret')
        authorize.assert_not_called()

    async def test_busy_and_expired_sessions(self):
        session = SpotifySession('C' * 32)
        async with session.lock:
            with self.assertRaisesRegex(ExportError, 'Another'):
                await session.export(LINK)
            with self.assertRaisesRegex(ExportError, 'Wait'):
                await session.disconnect()
        client = session.client = MagicMock(tokens={'access_token': 'private'})
        with patch('music.spotify_session.fetch_playlist', side_effect=ExportError('Session expired')):
            with self.assertRaises(ExportError):
                await session.export(LINK)
        self.assertIsNone(session.client)
        self.assertEqual(client.tokens, {})

class SpotifyCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(user=SimpleNamespace(id=42),
                               response=SimpleNamespace(defer=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_non_owner_cannot_read_spotify(self):
        session = MagicMock(export=AsyncMock())
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=False)), \
             patch.object(main.bot, 'spotify', session):
            with self.assertRaisesRegex(ValueError, 'Only the bot owner'):
                await main.spotifyplaylist.callback(self.interaction(), LINK)
        session.export.assert_not_called()

    async def test_returns_private_files_without_voice(self):
        interaction = self.interaction()
        result = PlaylistExport('My Playlist', 1, 0, LINK,
                                [('playlist.json', b'[{"title":"Song","artist":"Artist"}]'), ('info.txt', b'Source: Spotify')])
        session = MagicMock(client=object(), export=AsyncMock(return_value=result))
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=True)), \
             patch.object(main.bot, 'spotify', session):
            await main.spotifyplaylist.callback(interaction, LINK, autoplay=False)
        session.export.assert_awaited_once_with(LINK)
        response = interaction.followup.send.call_args
        self.assertTrue(response.kwargs['ephemeral'])
        self.assertEqual([f.filename for f in response.kwargs['files']], ['playlist.json', 'info.txt'])
        self.assertIn('/play playlist_file', response.args[0])

    async def test_disconnect_owner_check(self):
        session = MagicMock(disconnect=AsyncMock())
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=False)), \
             patch.object(main.bot, 'spotify', session):
            with self.assertRaises(ValueError):
                await main.spotifydisconnect.callback(self.interaction())
        session.disconnect.assert_not_called()

    async def test_autoplay_queues_all_parts_in_order(self):
        interaction = self.interaction()
        result = PlaylistExport('Playlist', 3, 0, LINK, [
            ('part-001.json', json.dumps([{'title': 'First', 'artist': 'Artist'}, {'title': 'Second', 'artist': 'Artist'}]).encode()),
            ('part-002.json', json.dumps([{'title': 'First', 'artist': 'Artist'}]).encode()), ('info.txt', b'info')])
        session = MagicMock(client=object(), export=AsyncMock(return_value=result))
        player, channel = MagicMock(enqueue=AsyncMock()), object()
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=True)), \
             patch.object(main.bot, 'spotify', session), patch('main.player_for', return_value=(player, channel)):
            await main.spotifyplaylist.callback(interaction, LINK)
        tracks = player.enqueue.call_args.args[1]
        self.assertEqual([t.title for t in tracks], ['First', 'Second', 'First'])
        self.assertTrue(all(t.requested_by == 42 for t in tracks))
        self.assertIn('Queued 3 songs automatically', interaction.followup.send.call_args.args[0])

    async def test_play_spotify_link_routes_automatically(self):
        interaction = self.interaction()
        result = PlaylistExport('Playlist', 1, 0, LINK, [])
        with patch('main.spotify_request', AsyncMock(return_value=(result, 1, []))) as request, \
             patch.object(main.resolver, 'resolve') as resolve:
            await main.play.callback(interaction, query=LINK)
        request.assert_awaited_once_with(interaction, LINK, True)
        resolve.assert_not_called()
        self.assertTrue(interaction.response.defer.call_args.kwargs['ephemeral'])

    async def test_autoplay_requires_voice_before_fetching(self):
        session = MagicMock(client=object(), export=AsyncMock())
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=True)), \
             patch.object(main.bot, 'spotify', session), patch('main.player_for', side_effect=ValueError('Join voice')):
            with self.assertRaisesRegex(ValueError, 'Join voice'):
                await main.spotifyplaylist.callback(self.interaction(), LINK)
        session.export.assert_not_called()

    async def test_oversized_playlist_is_not_partially_queued(self):
        row = {'title': 'Song', 'artist': 'Artist'}
        result = PlaylistExport('Large', 1001, 0, LINK, [
            ('part-001.json', json.dumps([row] * 500).encode()),
            ('part-002.json', json.dumps([row] * 500).encode()),
            ('part-003.json', json.dumps([row]).encode())])
        player = MagicMock(enqueue=AsyncMock())
        with patch('main.player_for', return_value=(player, object())):
            with self.assertRaisesRegex(ValueError, '1000-song'):
                await main.queue_spotify_export(self.interaction(), result)
        player.enqueue.assert_not_called()
