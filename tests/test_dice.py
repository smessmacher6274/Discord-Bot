import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from dnd.skills import parse_skills
from dnd.tracker import Tracker


class DiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bot = main.Bot()
        self.bot.tracker.path = Path(self.temp.name) / 'points.sqlite3'
        catalog, records = parse_skills('Character,Character ID\nHero,A\n',
                                      'Character ID,Skill,Modifier\nA,Willpower,7\n')
        self.bot.abilities.load = AsyncMock(return_value=catalog)
        self.bot.skills.load = AsyncMock(return_value=(catalog, records))
        self.interaction = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=10),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))

    async def roll(self, values, damage=True):
        with patch('dnd.dice.secrets.randbelow', side_effect=values):
            await self.bot.tree.get_command('dice').callback(self.interaction, len(values), 6, damage)
        return self.interaction.followup.send.call_args.kwargs['embed'].description

    async def test_maximum_cap_spend_and_persistence(self):
        self.bot.tracker.signin(1, 10, 'A')
        text = await self.roll([5, 5, 0])
        self.assertIn('Total: **13**', text)
        self.assertIn('point earned', text)
        self.assertEqual(Tracker(self.bot.tracker.path).party_points(1), [(10, 'A', 1)])
        self.assertIn("Should've used your shinobi point dumbass", await self.roll([5]))
        await self.bot.tree.get_command('shinobi').callback(self.interaction, use=True)
        self.assertEqual(self.bot.tracker.party_points(1), [(10, 'A', 0)])
        self.assertIn('point earned', await self.roll([5]))
        self.assertFalse(self.bot.tracker.use_shinobi(2, 'A'))

    async def test_no_maximum_or_ordinary_roll_earns_nothing(self):
        await self.roll([5], damage=False)
        self.bot.abilities.load.assert_not_awaited()
        self.bot.tracker.signin(1, 10, 'A')
        await self.roll([4, 3])
        self.assertEqual(self.bot.tracker.party_points(1), [(10, 'A', 0)])

    async def test_damage_requires_signin_before_dice_are_rolled(self):
        with patch('dnd.dice.secrets.randbelow') as random:
            with self.assertRaisesRegex(ValueError, '/signin'):
                await self.bot.tree.get_command('dice').callback(self.interaction, 1, 6, True)
            random.assert_not_called()

    async def test_shinobi_display_lists_character_and_user(self):
        self.bot.tracker.signin(1, 10, 'A')
        await self.roll([5])
        await self.bot.tree.get_command('shinobi').callback(self.interaction, show=True)
        sent = self.interaction.followup.send.call_args
        self.assertIn('Hero (<@10>): **1/1**', sent.args[0])
        self.assertFalse(sent.kwargs['ephemeral'])

    async def test_visibility_options_and_skills_public_or_private(self):
        for name in ('skills', 'abilities', 'loadout', 'damage', 'relic', 'help', 'party', 'shinobi'):
            self.assertFalse(self.bot.tree.get_command(name)._params['show'].default)
        for show in (False, True):
            await self.bot.tree.get_command('skills').callback(self.interaction, 'Hero', show=show)
            self.assertEqual(self.interaction.response.defer.call_args.kwargs['ephemeral'], not show)
            self.assertEqual(self.interaction.followup.send.call_args.kwargs['ephemeral'], not show)

    async def test_points_survive_signout_and_multiple_awards_are_capped(self):
        self.bot.tracker.signin(1, 10, 'A')
        self.assertTrue(self.bot.tracker.award_shinobi(1, 'A'))
        self.assertFalse(self.bot.tracker.award_shinobi(1, 'A'))
        self.bot.tracker.signout(1, 10)
        self.bot.tracker.signin(1, 20, 'A')
        self.assertEqual(self.bot.tracker.party_points(1), [(20, 'A', 1)])
