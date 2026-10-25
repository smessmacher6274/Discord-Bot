import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main
from discord import app_commands
from dnd.help import HelpView, PAGES, help_embed


class HelpTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_command_and_navigation(self):
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), response=SimpleNamespace(
            send_message=AsyncMock(), edit_message=AsyncMock()))
        command = main.Bot().tree.get_command('help')
        await command.callback(interaction)
        result = interaction.response.send_message.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        view = result['view']
        self.assertEqual(view.timeout, 600)
        self.assertTrue(await view.interaction_check(interaction))
        menu = view.children[0]
        menu._values = ['stats']
        await menu.callback(interaction)
        embed = interaction.response.edit_message.call_args.kwargs['embed']
        self.assertIn('Baseline', embed.description)
        self.assertEqual([option.value for option in menu.options if option.default], ['stats'])
        stranger = SimpleNamespace(user=SimpleNamespace(id=99), response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(stranger))
        self.assertTrue(stranger.response.send_message.call_args.kwargs['ephemeral'])
        await command.callback(interaction, 'enemies')
        self.assertIn('/enemy damage', interaction.response.send_message.call_args.kwargs['embed'].description)

    async def test_limits_and_all_active_commands_are_documented(self):
        for key in PAGES:
            with self.subTest(topic=key):
                embed = help_embed(key)
                self.assertLessEqual(len(embed.description), 4096)
                self.assertLessEqual(len(embed), 6000)
                self.assertEqual(len(HelpView(42, key).children[0].options), len(PAGES))
        text = '\n'.join(description for _, description in PAGES.values())
        for command in main.bot.tree.walk_commands():
            if isinstance(command, app_commands.Command):
                with self.subTest(command=command.qualified_name):
                    self.assertRegex(text, '/' + re.escape(command.qualified_name) + r'(?=[ `\n])')

