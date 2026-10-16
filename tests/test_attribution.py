import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from music.player import Player
from music.track import Track

class AttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_credit_precedes_audio(self):
        events = []
        player = Player(MagicMock(), 'ffmpeg')
        player.voice = MagicMock()
        player.voice.is_connected.return_value = True
        player.upcoming.append(Track('Song', 'Artist', 3, 'local:a', 'a.wav', attribution='Credit'))
        async def notify(message):
            events.append('credit')
            self.assertIn('Credit', message)
        def play(source, after):
            events.append('audio')
            after(None)
        player.voice.play.side_effect = play
        with patch('music.player.discord.FFmpegPCMAudio'), patch('music.player.discord.PCMVolumeTransformer'):
            await player.run(notify)
        self.assertEqual(events, ['credit', 'audio'])
        self.assertIsNone(player.current)

    async def test_missing_credit_permission_skips_track(self):
        player = Player(MagicMock(), 'ffmpeg')
        player.voice = MagicMock()
        player.voice.is_connected.return_value = True
        player.upcoming.append(Track('Song', 'Artist', 3, 'local:a', 'a.wav', attribution='Credit'))
        calls = 0
        async def notify(message):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError('Cannot publish credit')
        with self.assertLogs(level='ERROR'), patch('music.player.discord.FFmpegPCMAudio') as decoder:
            await player.run(notify)
        decoder.assert_not_called()
        player.voice.play.assert_not_called()
        self.assertIsNone(player.current)
