import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from dnd.initiative import initiative_order, register_initiative_command
from dnd.skills import parse_skills
from dnd.tracker import Tracker


def campaign(modifier='7'):
    return parse_skills('Character,Character ID\nZed,A\nAmy,B\n',
                        f'Character ID,Skill,Modifier\nA,Willpower,{modifier}\nB,willpower,-2\n')


class InitiativeTests(unittest.TestCase):
    def test_two_d10_per_character_and_descending_totals(self):
        catalog, records = campaign()
        with patch('dnd.initiative.secrets.randbelow', side_effect=[0, 0, 9, 9]) as dice:
            result = initiative_order([(10, 'A'), (20, 'B')], catalog, records)
        self.assertEqual([(c.name, a, b, m, total) for c, a, b, m, total in result],
                         [('Amy', 10, 10, -2, 18), ('Zed', 1, 1, 7, 9)])
        self.assertEqual(dice.call_count, 4)
        self.assertTrue(all(call.args == (10,) for call in dice.call_args_list))

    def test_ties_are_alphabetical_and_zero_is_valid(self):
        catalog, records = campaign('0')
        with patch('dnd.initiative.secrets.randbelow', side_effect=[0, 0, 1, 1]):
            result = initiative_order([(10, 'A'), (20, 'B')], catalog, records)
        self.assertEqual([(r[0].name, r[4]) for r in result], [('Amy', 2), ('Zed', 2)])

    def test_invalid_roster_never_rolls_any_dice(self):
        for modifier in ('', 'conditional', '+2 while transformed'):
            catalog, records = campaign(modifier)
            with self.subTest(modifier=modifier), patch('dnd.initiative.secrets.randbelow') as dice:
                with self.assertRaisesRegex(ValueError, 'Willpower'):
                    initiative_order([(20, 'B'), (10, 'A')], catalog, records)
                dice.assert_not_called()
        catalog, records = campaign()
        for identifier in ('missing', 'A'):
            records['A'] = []
            with patch('dnd.initiative.secrets.randbelow') as dice:
                with self.assertRaises(ValueError):
                    initiative_order([(20, 'B'), (10, identifier)], catalog, records)
                dice.assert_not_called()


class InitiativeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_order_uses_only_current_server_roster(self):
        bot = main.Bot()
        tracker = MagicMock()
        tracker.signed_in.return_value = [(10, 'A')]
        skills = SimpleNamespace(load=AsyncMock(return_value=campaign()))
        bot.tree.remove_command('initiative')
        bot.tree.remove_command('turnorder')
        register_initiative_command(bot, tracker, skills)
        interaction = SimpleNamespace(guild_id=123, response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        with patch('dnd.initiative.secrets.randbelow', side_effect=[0, 9]):
            await bot.tree.get_command('initiative').callback(interaction)
        tracker.signed_in.assert_called_once_with(123)
        interaction.response.defer.assert_awaited_once_with()
        payload = interaction.followup.send.call_args.kwargs
        self.assertNotIn('ephemeral', payload)
        text = payload['embed'].description
        self.assertIn('1. **Zed** \u2014 **18**', text)
        self.assertIn('2d10: 1 + 10; Willpower: +7', text)
        self.assertNotIn('Amy', text)
        tracker.save_turn_order.assert_called_once_with(123, text)

    async def test_empty_roster_does_not_load_sheet(self):
        bot = main.Bot()
        tracker = MagicMock()
        tracker.signed_in.return_value = []
        skills = SimpleNamespace(load=AsyncMock())
        bot.tree.remove_command('initiative')
        bot.tree.remove_command('turnorder')
        register_initiative_command(bot, tracker, skills)
        interaction = SimpleNamespace(guild_id=1, response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await bot.tree.get_command('initiative').callback(interaction)
        skills.load.assert_not_awaited()
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])

    async def test_saved_order_survives_restart_party_changes_and_failed_roll(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = main.Bot()
            bot.tracker.path = Path(directory) / 'tracker.sqlite3'
            bot.tracker.signin(1, 10, 'A')
            bot.skills.load = AsyncMock(return_value=campaign())
            interaction = SimpleNamespace(guild_id=1, response=SimpleNamespace(defer=AsyncMock()),
                                          followup=SimpleNamespace(send=AsyncMock()))
            with patch('dnd.initiative.secrets.randbelow', side_effect=[0, 9]):
                await bot.tree.get_command('initiative').callback(interaction)
            original = interaction.followup.send.call_args.kwargs['embed'].description
            bot.tracker.signout(1, 10)
            self.assertEqual(Tracker(bot.tracker.path).turn_order(1), original)
            bot.skills.load.reset_mock()
            with patch('dnd.initiative.secrets.randbelow') as dice:
                await bot.tree.get_command('turnorder').callback(interaction)
                dice.assert_not_called()
            bot.skills.load.assert_not_awaited()
            self.assertEqual(interaction.followup.send.call_args.kwargs['embed'].description, original)
            interaction.guild_id = 2
            await bot.tree.get_command('turnorder').callback(interaction)
            self.assertIn('/initiative', interaction.followup.send.call_args.args[0])
            self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
            interaction.guild_id = 1
            bot.tracker.signin(1, 10, 'A')
            bot.skills.load.return_value = campaign('conditional')
            await bot.tree.get_command('initiative').callback(interaction)
            self.assertEqual(bot.tracker.turn_order(1), original)
            bot.skills.load.return_value = campaign()
            with patch('dnd.initiative.secrets.randbelow', return_value=9):
                await bot.tree.get_command('initiative').callback(interaction)
            self.assertNotEqual(bot.tracker.turn_order(1), original)
