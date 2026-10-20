import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main
from dnd.abilities import AbilityError
from dnd.relics import Relic, RelicService, parse_relics, relic_response


class RelicTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_autocomplete_and_private_reply(self):
        bot = main.Bot()
        bot.relics.gids = ('123',)
        bot.relics.fetch_tabs = AsyncMock(return_value=[
            'Relic ID,Relic Name,Description\nREL1,Sun Crown,"First line\nSecond line"\nREL2,Moon Ring,Cold light\n'])
        command = bot.tree.get_command('relic')
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        choices = await command._params['relic'].autocomplete(interaction, 'crown')
        self.assertEqual([choice.value for choice in choices], ['REL1'])
        await command.callback(interaction, 'rel1')
        self.assertIsNone(interaction.followup.send.call_args.kwargs['embed'].footer.text)
        await command.callback(interaction, ' SUN CROWN ')
        result = interaction.followup.send.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        self.assertEqual(result['embed'].description, 'First line\nSecond line')
        bot.relics.fetch_tabs.assert_awaited_once()
        with self.assertRaisesRegex(AbilityError, 'Relic not found'):
            await command.callback(interaction, 'Unknown')
        cached = bot.relics.cached
        bot.relics.fetch_tabs.return_value = ['Wrong,Headers\n']
        with self.assertRaises(AbilityError):
            await bot.relics.load(force=True)
        self.assertIs(bot.relics.cached, cached)

    async def test_validation_and_missing_configuration(self):
        for text in ['Relic ID,Relic Name,Description\nREL1,Crown,\n',
                     'Relic ID,Relic Name,Description\nREL1,Crown,A\nREL2,crown,B\n',
                     'Relic ID,Relic Name,Description\nREL1,Crown,A\nrel1,Ring,B\n',
                     'Relic ID,Relic Name,Description\n,Crown,A\n',
                     'Relic Name,Description\nCrown,A\n', 'Wrong,Headers\n']:
            with self.subTest(text=text), self.assertRaises(AbilityError):
                parse_relics(text)
        with self.assertRaisesRegex(AbilityError, 'DND_RELICS_GID'):
            await RelicService('sheet').load()

    async def test_long_description_attached_in_full(self):
        text = 'Ancient power.\n' * 1000
        embed, files = relic_response(Relic('Crown', text), 'https://example.com')
        try:
            self.assertLessEqual(len(embed.description), 4096)
            self.assertEqual(files[0].fp.read().decode('utf-8'), text)
        finally:
            for file in files:
                file.close()
