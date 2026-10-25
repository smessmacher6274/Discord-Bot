import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main
from dnd.abilities import parse_catalog
from dnd.skills import Skill
from dnd.tracker import Tracker, sheet_baselines


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tracker.sqlite3'
        self.tracker = Tracker(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_stats_persist_baselines_and_resets(self):
        seed = {'Health': 10, 'Armor': 17}
        self.assertEqual(self.tracker.resources(1, 'CHR1', seed)['Health'], (10, 10))
        self.assertEqual(self.tracker.resources(1, 'CHR1', seed, 'subtract', 'Health', 3)['Health'], (7, 10))
        reopened = Tracker(self.path)
        self.assertEqual(reopened.resources(1, 'CHR1', {'Health': 99})['Health'], (7, 10))
        self.assertEqual(reopened.resources(1, 'CHR1', {}, 'add', 'Health', 5)['Health'], (12, 10))
        values = reopened.resources(1, 'CHR1', {}, 'baseline', 'Stamina', 8)
        self.assertEqual(values['Stamina'], (8, 8))
        reopened.resources(1, 'CHR1', {}, 'subtract', 'Stamina', 3)
        values = reopened.resources(1, 'CHR1', {}, 'reset', 'Health')
        self.assertEqual(values['Health'], (10, 10))
        self.assertEqual(values['Stamina'], (5, 8))
        self.assertEqual(reopened.resources(1, 'CHR1', {}, 'reset')['Stamina'], (8, 8))
        self.assertEqual(reopened.resources(2, 'CHR1', seed)['Health'], (10, 10))
        self.assertEqual(reopened.resources(1, 'CHR2', seed)['Health'], (10, 10))

    def test_unknown_baselines_and_invalid_changes_do_not_write(self):
        with self.assertRaisesRegex(ValueError, 'no baseline'):
            self.tracker.resources(1, 'CHR1', {}, 'subtract', 'Stamina', 1)
        with self.assertRaises(ValueError):
            self.tracker.resources(1, 'CHR1', {}, 'add', 'Health', -1)
        with self.assertRaises(ValueError):
            self.tracker.resources(1, 'CHR1', {}, 'baseline', 'Chakra', 4)
        self.assertEqual(self.tracker.resources(1, 'CHR1', {}), {})
        self.assertEqual(sheet_baselines([Skill('Health', '10'), Skill('Armor', '0'),
                         Skill('Stamina', ''), Skill('Chakara', '10')]), {'Health': 10, 'Armor': 0})

    def test_enemy_damage_and_attribution_survive_restart(self):
        self.tracker.create_enemy(1, 'Guard', 30)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.tracker.create_enemy(1, ' guard ', 50)
        self.tracker.enemy(1, 'Guard', 5, 'CHR1', 'user1')
        self.tracker.enemy(1, 'GUARD', 7, 'CHR2', 'user2')
        self.tracker.enemy(1, 'Guard', 6, 'CHR1', 'user1')
        name, health, total, contributions = Tracker(self.path).enemy(1, 'Guard')
        self.assertEqual((name, health, total), ('Guard', 30, 18))
        self.assertEqual(contributions, [('CHR1', 11), ('CHR2', 7)])
        with self.assertRaises(ValueError):
            self.tracker.enemy(2, 'Guard', 3, 'CHR1')
        with self.assertRaises(ValueError):
            self.tracker.enemy(1, 'Guard', -1, 'CHR1')
        self.assertEqual(self.tracker.enemy(1, 'Guard', reset=True)[2:], (0, []))
        self.tracker.create_enemy(2, 'Guard')
        self.assertEqual(self.tracker.enemy(2, 'Guard')[1], None)
        self.assertEqual(self.tracker.enemy_names(1), ['Guard'])


class TrackerCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bot = main.Bot()
        self.bot.tracker.path = Path(self.temp.name) / 'tracker.sqlite3'
        catalog = parse_catalog('Character,Character ID\nRyujin,CHR1\n',
                                'Ability ID,Ability Name,Description\n', 'Character ID,Ability ID\n')
        self.bot.skills.load = AsyncMock(return_value=(catalog, {'CHR1': [Skill('Health', '10'), Skill('Armor', '17')]}))

    async def asyncTearDown(self):
        self.temp.cleanup()

    def interaction(self):
        return SimpleNamespace(guild_id=1, user=SimpleNamespace(id=42),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))

    async def test_stat_commands_and_character_autocomplete(self):
        command = self.bot.tree.get_command('stats')
        interaction = self.interaction()
        await command.get_command('subtract').callback(interaction, 'Ryujin', 'Health', 3)
        result = interaction.followup.send.call_args.kwargs['embed'].description
        self.assertIn('Current: **7** | Baseline: 10', result)
        self.assertIn('Stamina** — Not set', result)
        await command.get_command('baseline').callback(interaction, 'Ryujin', 'Stamina', 9)
        await command.get_command('reset').callback(interaction, 'Ryujin')
        self.assertIn('Current: **10**', interaction.followup.send.call_args.kwargs['embed'].description)
        choices = await command.get_command('view')._params['character'].autocomplete(interaction, 'ryu')
        self.assertEqual([choice.value for choice in choices], ['Ryujin'])

    async def test_enemy_commands_and_attribution(self):
        command = self.bot.tree.get_command('enemy')
        interaction = self.interaction()
        await command.get_command('create').callback(interaction, 'Guard', 30)
        await command.get_command('damage').callback(interaction, 'Guard', 'Ryujin', 8)
        text = interaction.followup.send.call_args.kwargs['embed'].description
        self.assertIn('**22 / 30**', text)
        self.assertIn('Ryujin: **8**', text)
        choices = await command.get_command('damage')._params['enemy'].autocomplete(interaction, 'gu')
        self.assertEqual([choice.value for choice in choices], ['Guard'])
        await command.get_command('reset').callback(interaction, 'Guard')
        self.assertIn('Damage dealt: **0**', interaction.followup.send.call_args.kwargs['embed'].description)

    async def test_simultaneous_hits_and_stat_changes_are_atomic(self):
        tracker = self.bot.tracker
        tracker.create_enemy(1, 'Boss')
        tracker.resources(1, 'CHR1', {'Health': 100})
        await asyncio.gather(*(asyncio.to_thread(tracker.enemy, 1, 'Boss', 1, 'CHR1', 42) for _ in range(15)))
        await asyncio.gather(*(asyncio.to_thread(tracker.resources, 1, 'CHR1', {}, 'subtract', 'Health', 1)
                               for _ in range(15)))
        self.assertEqual(tracker.enemy(1, 'Boss')[2], 15)
        self.assertEqual(tracker.resources(1, 'CHR1', {})['Health'], (85, 100))
