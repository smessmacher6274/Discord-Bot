import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from dnd.signin import resolve_character
from dnd.skills import parse_skills
from dnd.tracker import Tracker


class SigninTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bot = main.Bot()
        self.bot.tracker.path = Path(self.temp.name) / 'tracker.sqlite3'
        self.catalog, self.records = parse_skills(
            'Character,Character ID\nHero,A\nOther,B\n',
            'Character ID,Skill,Modifier\nA,Melee,7\nA,Health,20\nB,Melee,9\n')
        self.bot.abilities.load = AsyncMock(return_value=self.catalog)
        self.bot.skills.load = AsyncMock(return_value=(self.catalog, self.records))
        self.bot.loadouts.load = AsyncMock(return_value=(self.catalog, {'A': [], 'B': []}))
        self.interaction = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=10),
            namespace=SimpleNamespace(), response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def test_persistence_exclusivity_switch_and_server_isolation(self):
        tracker = self.bot.tracker
        tracker.signin(1, 10, 'A')
        tracker.signin(1, 20, 'B')
        with self.assertRaisesRegex(ValueError, 'already signed in'):
            tracker.signin(1, 10, 'B')
        self.assertEqual(Tracker(tracker.path).signed_character(1, 10), 'A')
        self.assertIsNone(tracker.signed_character(2, 10))
        tracker.signin(2, 20, 'A')
        tracker.signout(1, 20)
        tracker.signin(1, 10, 'B')
        self.assertEqual(tracker.signed_in(1), [(10, 'B')])
        tracker.signout(1, 10)
        self.assertEqual(tracker.signed_in(1), [])

    async def test_signin_roster_signout_and_missing_default(self):
        await self.bot.tree.get_command('signin').callback(self.interaction, 'Hero')
        self.assertEqual(await resolve_character(self.bot, self.interaction), 'A')
        self.assertEqual(await resolve_character(self.bot, self.interaction, 'Other'), 'Other')
        await self.bot.tree.get_command('signedin').callback(self.interaction)
        self.assertIn('Hero', self.interaction.followup.send.call_args.args[0])
        await self.bot.tree.get_command('signout').callback(self.interaction)
        with self.assertRaisesRegex(ValueError, '/signin'):
            await resolve_character(self.bot, self.interaction)

    async def test_all_character_commands_accept_saved_default(self):
        self.bot.tracker.signin(1, 10, 'A')
        tree = self.bot.tree
        for name in ('skills', 'abilities', 'loadout'):
            await tree.get_command(name).callback(self.interaction)
        roll = tree.get_command('roll')
        choices = await roll._params['skill'].autocomplete(self.interaction, 'melee')
        self.assertEqual([(c.name, c.value) for c in choices], [('Melee +7', 'Melee')])
        with patch('dnd.skills.secrets.randbelow', return_value=0):
            await roll.callback(self.interaction, skill='Melee')
        self.assertIn('Modifier: **+7**', self.interaction.followup.send.call_args.kwargs['embed'].description)
        stats = tree.get_command('stats')
        await stats.get_command('view').callback(self.interaction)
        await stats.get_command('add').callback(self.interaction, stat='Health', amount=2)
        await stats.get_command('subtract').callback(self.interaction, stat='Health', amount=1)
        await stats.get_command('baseline').callback(self.interaction, stat='Health', value=30)
        await stats.get_command('reset').callback(self.interaction)
        enemies = tree.get_command('enemy')
        await enemies.get_command('create').callback(self.interaction, 'Guard', 50)
        await enemies.get_command('damage').callback(self.interaction, enemy='Guard', amount=5)
        self.assertEqual(self.bot.tracker.enemy(1, 'Guard')[3], [('A', 5)])
        for command in tree.walk_commands():
            if hasattr(command, '_params') and 'character' in command._params:
                self.assertEqual(command._params['character'].required, command.name == 'signin')

    async def test_removed_character_does_not_fall_back_to_someone_else(self):
        self.bot.tracker.signin(1, 10, 'removed')
        with self.assertRaisesRegex(ValueError, 'Character not found'):
            await self.bot.tree.get_command('skills').callback(self.interaction)
