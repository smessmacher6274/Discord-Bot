import asyncio
import tempfile
import unittest
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import main
from dnd.skills import parse_skills
from dnd.tracker import Tracker
from dnd.turntimer import ChimeSource, TurnTimers, play_chime, roll_turn_times, tone, turn_minutes


def campaign():
    return parse_skills('Character,Character ID\nHero,A\nOther,B\n',
        'Character ID,Skill,Modifier\nA,Decipher,5\nA,Reflex,7\nB,Decipher,9\nB,Reflex,-2\n')


class TurnRollTests(unittest.TestCase):
    def test_thresholds(self):
        for total, minutes in [(-5, 1), (13, 1), (14, 1), (17, 1), (18, 2),
                               (21, 2), (22, 3), (25, 3), (26, 4), (30, 5)]:
            self.assertEqual(turn_minutes(total), minutes)

    def test_higher_modifier_two_d10_and_validation_before_rolling(self):
        catalog, records = campaign()
        with patch('dnd.turntimer.secrets.randbelow', side_effect=[0, 9, 9, 9]) as dice:
            rows = roll_turn_times([(1, 'A'), (2, 'B')], catalog, records)
        self.assertEqual([(r['skill'], r['total'], r['minutes']) for r in rows],
                         [('Reflex', 18, 2), ('Decipher', 29, 4)])
        self.assertEqual(dice.call_count, 4)
        records['B'] = []
        with patch('dnd.turntimer.secrets.randbelow') as dice:
            with self.assertRaises(ValueError):
                roll_turn_times([(1, 'A'), (2, 'B')], catalog, records)
            dice.assert_not_called()

    def test_saved_results_persist_and_are_server_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = Tracker(Path(directory) / 'test.sqlite3')
            tracker.save_turn_times(1, [{'character': 'A', 'minutes': 2}])
            self.assertEqual(Tracker(tracker.path).turn_times(1), [{'character': 'A', 'minutes': 2}])
            self.assertEqual(tracker.turn_times(2), [])

    def test_chime_pcm_clips_mixes_and_finishes(self):
        base = MagicMock()
        base.read.side_effect = [array('h', [32000] * 1920).tobytes(), b'']
        source = ChimeSource(base)
        source.add(array('h', [1000] * 1920).tobytes())
        self.assertEqual(array('h', source.read())[0], 32767)
        self.assertEqual(source.read(), b'')
        source.cleanup()
        base.cleanup.assert_called_once()
        self.assertEqual(len({tone(kind) for kind in ('start', 'warning', 'end')}), 3)

    def test_sound_wraps_music_without_stopping_it(self):
        voice = MagicMock()
        voice.is_paused.return_value = False
        voice.source.is_opus.return_value = False
        play_chime(voice, 'start')
        self.assertIsInstance(voice.source, ChimeSource)
        voice.stop.assert_not_called()
        voice.play.assert_not_called()


class TurnTimerTests(unittest.IsolatedAsyncioTestCase):
    async def test_warning_and_end_deadlines_and_mentions(self):
        timers = TurnTimers()
        channel = SimpleNamespace(send=AsyncMock())
        row = {'user': 123, 'name': 'Hero'}
        with patch('dnd.turntimer.asyncio.sleep', new_callable=AsyncMock) as sleep, \
             patch('dnd.turntimer.play_chime') as chime:
            deadline = asyncio.get_running_loop().time() + 60
            await timers.countdown(1, channel, object(), row, deadline)
        self.assertAlmostEqual(sleep.await_args_list[0].args[0], 50, delta=1)
        self.assertAlmostEqual(sleep.await_args_list[1].args[0], 60, delta=1)
        self.assertEqual([c.args[1] for c in chime.call_args_list], ['warning', 'end'])
        self.assertIn('10 seconds', channel.send.await_args_list[0].args[0])
        self.assertIn('Time is up', channel.send.await_args_list[1].args[0])

    async def test_start_replace_cancel_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            bot = main.Bot()
            bot.tracker.path = Path(directory) / 'test.sqlite3'
            bot.tracker.signin(1, 123, 'A')
            bot.tracker.save_turn_times(1, [{'character': 'A', 'name': 'Hero', 'minutes': 2, 'user': 123}])
            bot.skills.load = AsyncMock(return_value=campaign())
            voice = MagicMock()
            voice.channel.id = 7
            voice.is_paused.return_value = False
            interaction = SimpleNamespace(guild_id=1, guild=SimpleNamespace(voice_client=voice),
                user=SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(id=7))),
                channel=SimpleNamespace(send=AsyncMock()), response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            with patch('dnd.turntimer.play_chime'):
                start = bot.tree.get_command('turnstart').callback
                await start(interaction, 'Hero')
                old = bot.turn_timers.tasks[1]
                await start(interaction, 'Hero')
                self.assertTrue(old.cancelled())
                await bot.tree.get_command('turnstop').callback(interaction)
                self.assertEqual(bot.turn_timers.tasks, {})
                await start(interaction, 'Hero')
                await bot.turn_timers.close()
                self.assertEqual(bot.turn_timers.tasks, {})
