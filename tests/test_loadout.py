import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main
from dnd.abilities import AbilityError
from dnd.loadout import LoadoutService, loadout_response, parse_loadouts


CHARACTERS = 'Character,Character ID\nRyujin,CHR1\nKrusty,CHR2\nEmpty,CHR3\n'
HOLDINGS = 'Character ID,Relic Name\nCHR1,Sun Crown\nCHR2,Moon Ring\nCHR1,Ancient Blade\n'


class LoadoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_isolates_holdings_by_id_and_autocomplete_uses_ids(self):
        bot = main.Bot()
        bot.loadouts.gids = ('0', '123')
        bot.loadouts.fetch_tabs = AsyncMock(return_value=[CHARACTERS, HOLDINGS])
        command = bot.tree.get_command('loadout')
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        choices = await command._params['character'].autocomplete(interaction, 'ryu')
        self.assertEqual([(c.name, c.value) for c in choices], [('Ryujin', 'CHR1')])
        choices = await command._params['character'].autocomplete(interaction, 'CHR2')
        self.assertEqual([c.value for c in choices], ['CHR2'])
        await command.callback(interaction, 'CHR1')
        result = interaction.followup.send.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        self.assertIn('Sun Crown', result['embed'].description)
        self.assertIn('Ancient Blade', result['embed'].description)
        self.assertNotIn('Moon Ring', result['embed'].description)
        await command.callback(interaction, 'CHR3')
        self.assertIn('no relics', interaction.followup.send.call_args.kwargs['embed'].description)
        with self.assertRaises(AbilityError):
            await command.callback(interaction, 'unknown')
        bot.loadouts.fetch_tabs.assert_awaited_once()
        cached = bot.loadouts.cached
        bot.loadouts.fetch_tabs.return_value = [CHARACTERS, HOLDINGS + 'UNKNOWN,Bad\n']
        with self.assertRaises(AbilityError):
            await bot.loadouts.load(force=True)
        self.assertIs(bot.loadouts.cached, cached)

    async def test_invalid_assignments_and_missing_configuration(self):
        for extra in ['UNKNOWN,Crown\n', 'CHR1,sun crown\n', 'CHR1,\n']:
            with self.subTest(extra=extra), self.assertRaises(AbilityError):
                parse_loadouts(CHARACTERS, HOLDINGS + extra)
        with self.assertRaisesRegex(AbilityError, 'DND_CHARACTER_RELICS_GID'):
            await LoadoutService('sheet', '0').load()

    async def test_long_loadout_retains_all_relics_in_attachment(self):
        catalog, _ = parse_loadouts(CHARACTERS, HOLDINGS)
        names = [f'Relic {i}' for i in range(1000)]
        embed, files = loadout_response(catalog.character('CHR1'), names, 'https://example.com')
        try:
            self.assertLessEqual(len(embed.description), 4096)
            self.assertEqual(files[0].fp.read().decode(), '\n'.join(f'• {name}' for name in names))
        finally:
            for file in files:
                file.close()
