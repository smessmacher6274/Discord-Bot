import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from music.player import Player
from music.track import Track

class SkipTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_advances_playing_and_paused_audio(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                player = Player(MagicMock(), 'ffmpeg')
                first = Track('First', 'Artist', 10, 'local:a', 'a.wav')
                second = Track('Second', 'Artist', 10, 'local:b', 'b.wav')
                player.upcoming.extend([first, second])
                voice = player.voice = MagicMock()
                voice.is_connected.return_value = True
                voice.is_playing.return_value = not paused
                voice.is_paused.return_value = paused
                started = asyncio.Event()
                callback = None
                played = []
                def play(source, after):
                    nonlocal callback
                    callback = after
                    played.append(player.current.title)
                    if len(played) == 1:
                        started.set()
                    else:
                        after(None)
                voice.play.side_effect = play
                voice.stop.side_effect = lambda: callback(None)
                with patch('music.player.discord.FFmpegPCMAudio'), patch('music.player.discord.PCMVolumeTransformer'):
                    task = asyncio.create_task(player.run(AsyncMock()))
                    try:
                        await asyncio.wait_for(started.wait(), 1)
                        self.assertEqual(await player.skip(), first)
                        self.assertEqual(list(player.upcoming), [second])
                        await asyncio.wait_for(task, 1)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                self.assertEqual(played, ['First', 'Second'])
                self.assertIsNone(player.current)

    async def test_idle_skip_does_not_change_queue(self):
        player = Player(MagicMock(), 'ffmpeg')
        player.upcoming.append('queued')
        with self.assertRaises(ValueError):
            await player.skip()
        self.assertEqual(list(player.upcoming), ['queued'])

    async def test_skip_last_song_keeps_connection(self):
        player = Player(MagicMock(), 'ffmpeg')
        player.voice = MagicMock()
        player.current = Track('Last', 'Artist', 1, 'local:a', 'a.wav')
        player.voice.is_playing.return_value = True
        await player.skip()
        player.voice.stop.assert_called_once()
        player.voice.disconnect.assert_not_called()
