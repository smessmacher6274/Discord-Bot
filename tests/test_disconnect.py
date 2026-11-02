import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from music.player import Player


class DisconnectTests(unittest.IsolatedAsyncioTestCase):
    def player(self):
        player = Player(MagicMock(), 'ffmpeg', idle_timeout=0.01)
        player.voice = MagicMock(disconnect=AsyncMock())
        player.voice.is_connected.return_value = True
        player.voice.is_playing.return_value = False
        return player

    async def test_idle_and_paused_disconnect_and_clear_queue(self):
        for paused in (False, True):
            player = self.player()
            voice = player.voice
            voice.is_paused.return_value = paused
            player.upcoming.append('queued')
            player.task = asyncio.create_task(asyncio.Event().wait())
            task = player.task
            player.idle_task = asyncio.create_task(player.watch_idle())
            await asyncio.wait_for(player.idle_task, 1)
            voice.disconnect.assert_awaited_once_with(force=True)
            self.assertTrue(task.cancelled())
            self.assertEqual(list(player.upcoming), [])
            self.assertIsNone(player.voice)

    async def test_active_music_stays_connected_then_idle_disconnects(self):
        player = self.player()
        voice = player.voice
        voice.is_playing.return_value = True
        player.idle_task = asyncio.create_task(player.watch_idle())
        await asyncio.sleep(0.05)
        voice.disconnect.assert_not_awaited()
        voice.is_playing.return_value = False
        await asyncio.wait_for(player.idle_task, 1)
        voice.disconnect.assert_awaited_once()

    async def test_manual_close_cancels_idle_and_playback(self):
        player = self.player()
        voice = player.voice
        player.task = asyncio.create_task(asyncio.Event().wait())
        player.idle_task = asyncio.create_task(player.watch_idle())
        playback, idle = player.task, player.idle_task
        await player.close()
        self.assertTrue(playback.cancelled())
        self.assertTrue(idle.cancelled())
        voice.stop.assert_called_once()
        voice.disconnect.assert_awaited_once()

    async def test_remove_command_closes_player(self):
        player = self.player()
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()),
                                      user=SimpleNamespace(voice=SimpleNamespace(channel=player.voice.channel)))
        with patch('main.player_for', return_value=(player, player.voice.channel)):
            await main.remove.callback(interaction)
        self.assertIsNone(player.voice)
        interaction.followup.send.assert_awaited_once()
