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

    def test_skill_dice_persist_are_shared_by_party_and_isolated_by_server(self):
        self.assertEqual(self.tracker.roll_skill(1, 'CHR1', lambda _: 9),
                         ([10, 10], 3, 'Rule of Cool'))
        reopened = Tracker(self.path)
        self.assertEqual(reopened.roll_skill(1, 'CHR1', lambda _: 4), ([5, 5, 5], 3, None))
        self.assertEqual(reopened.roll_skill(2, 'CHR1', lambda _: 4), ([5, 5], 2, None))
        self.assertEqual(reopened.roll_skill(1, 'CHR2', lambda _: 4), ([5, 5, 5], 3, None))
        self.assertEqual(reopened.roll_skill(1, 'CHR2', lambda _: 0), ([1, 1, 1], 2, 'Rule of Drool'))
        self.assertEqual(reopened.roll_skill(1, 'CHR1', lambda _: 0), ([1, 1], 1, 'Rule of Drool'))
        self.assertEqual(reopened.roll_skill(1, 'CHR2', lambda _: 0), ([1], 1, 'Rule of Drool'))
        reopened.restore_skill_dice(1)
        self.assertEqual(reopened.roll_skill(1, 'CHR1', lambda _: 4), ([5, 5], 2, None))
        self.assertEqual(reopened.roll_skill(1, 'CHR2', lambda _: 4), ([5, 5], 2, None))

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
        await command.get_command('subtract').callback(interaction, stat='Health', amount=3, character='Ryujin')
        result = interaction.followup.send.call_args.kwargs['embed'].description
        self.assertIn('Current: **7** | Baseline: 10', result)
        self.assertIn('Stamina** — Not set', result)
        await command.get_command('baseline').callback(interaction, stat='Stamina', value=9, character='Ryujin')
        await command.get_command('reset').callback(interaction, 'Ryujin')
        self.assertIn('Current: **10**', interaction.followup.send.call_args.kwargs['embed'].description)
        choices = await command.get_command('view')._params['character'].autocomplete(interaction, 'ryu')
        self.assertEqual([choice.value for choice in choices], ['Ryujin'])

    async def test_party_stats_show_saved_values_and_only_server_roster(self):
        catalog = parse_catalog('Character,Character ID\nRyujin,CHR1\nAmy,CHR2\nHidden,CHR3\n',
                                'Ability ID,Ability Name,Description\n', 'Character ID,Ability ID\n')
        self.bot.skills.load.return_value = (catalog, {
            'CHR1': [Skill('Health', '10'), Skill('Stamina', '8')],
            'CHR2': [Skill('Health', '0')], 'CHR3': [Skill('Health', '99')]})
        tracker = self.bot.tracker
        tracker.signin(1, 1, 'CHR1')
        tracker.signin(1, 2, 'CHR2')
        tracker.signin(2, 3, 'CHR3')
        tracker.resources(1, 'CHR1', {'Health': 10, 'Stamina': 8}, 'subtract', 'Health', 3)
        tracker.resources(1, 'CHR1', {}, 'subtract', 'Stamina', 9)
        interaction = self.interaction()
        await self.bot.tree.get_command('stats').get_command('party').callback(interaction)
        payload = interaction.followup.send.call_args.kwargs
        text = payload['embed'].description
        self.assertIn('Health: **7 / 10**', text)
        self.assertIn('Stamina: **-1 / 8**', text)
        self.assertIn('**Amy** — Health: **0 / 0** | Stamina: **Not set**', text)
        self.assertLess(text.index('Amy'), text.index('Ryujin'))
        self.assertNotIn('Hidden', text)
        self.assertNotIn('Armor', text)
        self.assertNotIn('ephemeral', payload)
        self.assertEqual(tracker.resources(1, 'CHR1', {})['Health'], (7, 10))

    async def test_party_stats_empty_roster_and_removed_character(self):
        command = self.bot.tree.get_command('stats').get_command('party')
        interaction = self.interaction()
        await command.callback(interaction)
        self.bot.skills.load.assert_not_awaited()
        self.assertIn('No characters', interaction.followup.send.call_args.kwargs['embed'].description)
        self.bot.tracker.signin(1, 1, 'removed')
        await command.callback(interaction)
        self.assertIn('removed from Sheet', interaction.followup.send.call_args.kwargs['embed'].description)

    async def test_enemy_commands_and_attribution(self):
        command = self.bot.tree.get_command('enemy')
        interaction = self.interaction()
        await command.get_command('create').callback(interaction, 'Guard', 30)
        await command.get_command('damage').callback(interaction, enemy='Guard', amount=8, character='Ryujin')
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
