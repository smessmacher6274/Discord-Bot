import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from music.queue_manager import GuildQueue
from music.track import Track
import main

class ShuffleTests(unittest.TestCase):
    def test_preserves_current_duplicates_and_other_servers(self):
        queue, other = GuildQueue(), GuildQueue()
        queue.current = 'current'
        queue.upcoming.extend(['a', 'b', 'a', 'c'])
        other.upcoming.append('other')
        with patch('music.queue_manager.random.shuffle', side_effect=lambda items: items.reverse()):
            self.assertEqual(queue.shuffle(), 4)
        self.assertEqual(list(queue.upcoming), ['c', 'a', 'b', 'a'])
        self.assertEqual(queue.current, 'current')
        self.assertEqual(list(other.upcoming), ['other'])

    def test_insufficient_queue_is_unchanged(self):
        for tracks in ([], ['one']):
            queue = GuildQueue()
            queue.upcoming.extend(tracks)
            with self.assertRaises(ValueError):
                queue.shuffle()
            self.assertEqual(list(queue.upcoming), tracks)

class ShuffleButtonTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(user=SimpleNamespace(id=42), response=SimpleNamespace(
            edit_message=AsyncMock(), send_message=AsyncMock()))

    async def test_button_shuffles_live_queue_and_refreshes_snapshot(self):
        first = Track('First', 'Artist', 1, 'local:a', 'a.wav')
        second = Track('Second', 'Artist', 1, 'local:b', 'b.wav')
        current = Track('Current', 'Artist', 1, 'local:c', 'c.wav')
        player = GuildQueue()
        player.current = current
        player.upcoming.extend([first, second])
        view = main.QueuePages([], None, 42)
        interaction = self.interaction()
        with patch('main.player_for', return_value=(player, object())), \
             patch('music.queue_manager.random.shuffle', side_effect=lambda items: items.reverse()):
            await view.shuffle_queue.callback(interaction)
        self.assertEqual(view.tracks, [second, first])
        self.assertIs(view.current, current)
        self.assertIs(player.current, current)
        self.assertEqual(view.page, 0)
        interaction.response.edit_message.assert_awaited_once()
        self.assertIn('Shuffled 2', view.content())

    async def test_voice_permission_failure_leaves_queue_unchanged(self):
        view = main.QueuePages([], None, 42)
        interaction = self.interaction()
        with patch('main.player_for', side_effect=ValueError('Join the bot’s voice channel first.')):
            await view.shuffle_queue.callback(interaction)
        interaction.response.edit_message.assert_not_called()
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])

    async def test_only_view_owner_can_use_buttons(self):
        view = main.QueuePages([], None, 1)
        interaction = self.interaction()
        self.assertFalse(await view.interaction_check(interaction))

    async def test_command_shuffles_upcoming_only(self):
        player = GuildQueue()
        player.current = 'playing'
        player.upcoming.extend(['a', 'b'])
        interaction = self.interaction()
        with patch('main.player_for', return_value=(player, object())):
            await main.shuffle.callback(interaction)
        self.assertEqual(player.current, 'playing')
        self.assertCountEqual(player.upcoming, ['a', 'b'])
        interaction.response.send_message.assert_awaited_once_with('Shuffled 2 upcoming songs.')
