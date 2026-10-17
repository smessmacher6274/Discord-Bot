import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import main

class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_syncs_all_installed_servers(self):
        bot = main.Bot()
        first, second = SimpleNamespace(id=1), SimpleNamespace(id=2)
        async def guilds():
            yield first
            yield second
        with patch.object(bot, 'fetch_guilds', return_value=guilds()), \
             patch.object(bot.abilities, 'load', AsyncMock()), \
             patch.object(bot.tree, 'copy_global_to') as copy, \
             patch.object(bot.tree, 'sync', AsyncMock()) as sync:
            await bot.setup_hook()
        self.assertEqual(copy.call_count, 2)
        self.assertEqual([call.kwargs['guild'].id for call in sync.call_args_list], [1, 2])

    async def test_new_server_registered_when_joined(self):
        bot = main.Bot()
        guild = SimpleNamespace(id=3)
        with patch.object(bot, 'register_guild', AsyncMock()) as register:
            await bot.on_guild_join(guild)
        register.assert_awaited_once_with(guild)
