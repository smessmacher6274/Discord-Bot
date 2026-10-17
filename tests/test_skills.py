import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from dnd.abilities import AbilityError
from dnd.skills import SkillService, parse_skills, skill_response
import main

CHARACTERS = 'Character,Character ID\nRyujin,CHR1\nKrusty,CHR2\n'
SKILLS = 'Character ID,Skill,Modifier,Notes\nCHR1,Willpower,+5,While transformed\nCHR1,Navigation,+4,\nCHR2,Navigation,-2,\n'


class SkillParsingTests(unittest.TestCase):
    def test_skill_name_header_and_zero_modifier(self):
        _, skills = parse_skills(CHARACTERS,
            'Character ID,Skill Name,Modifier,Notes\nCHR1,Endurance,0,Stat Mod\n')
        self.assertEqual(skills['CHR1'][0].name, 'Endurance')
        self.assertEqual(skills['CHR1'][0].modifier, '0')
        with self.assertRaises(AbilityError):
            parse_skills(CHARACTERS, 'Character ID,Skill,Skill Name,Modifier\nCHR1,A,B,1\n')

    def test_character_isolation_and_verbatim_homebrew_modifiers(self):
        catalog, skills = parse_skills(CHARACTERS, SKILLS)
        self.assertEqual([s.modifier for s in skills[catalog.character('ryujin').id]], ['+4', '+5'])
        self.assertEqual(skills['CHR2'][0].modifier, '-2')
        self.assertEqual(skills['CHR1'][1].notes, 'While transformed')
        for bad in ['MISSING,Strength,+2,', 'CHR1,Willpower,+2,']:
            with self.subTest(bad=bad), self.assertRaises(AbilityError):
                parse_skills(CHARACTERS, SKILLS + bad + '\n')

    def test_empty_and_long_responses(self):
        catalog, skills = parse_skills(CHARACTERS, SKILLS)
        self.assertIn('No skills', skill_response(catalog.character('Ryujin'), [], 'https://example.com')[0].description)
        entries = skills['CHR1'] * 300
        embed, files = skill_response(catalog.character('Ryujin'), entries, 'https://example.com')
        try:
            self.assertLessEqual(len(embed.description), 4096)
            self.assertEqual(files[0].fp.read().decode().count('Willpower: +5'), 300)
        finally:
            for file in files:
                file.close()


class SkillCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_modifiers_do_not_break_other_skills_or_autocomplete(self):
        bot = main.Bot()
        bot.skills.gids = ('0', '123')
        bot.skills.fetch_tabs = AsyncMock(return_value=(CHARACTERS,
            SKILLS.replace('Character ID,Skill,', 'Character ID,Skill Name,') + 'CHR1,Speed,,Jutsu\n'))
        catalog, records = await bot.skills.load()
        embed, _ = skill_response(catalog.character('Ryujin'), records['CHR1'], bot.skills.source_url)
        self.assertIn('Speed: Not set', embed.description)
        self.assertIn('Navigation: +4', embed.description)
        callback = bot.tree.get_command('roll')._params['skill'].autocomplete
        interaction = SimpleNamespace(namespace=SimpleNamespace(character='Ryujin'),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        self.assertEqual([choice.value for choice in await callback(interaction, '')], ['Navigation', 'Willpower'])
        self.assertEqual([choice.value for choice in await callback(interaction, 'will')], ['Willpower'])
        with patch('dnd.skills.secrets.randbelow') as dice:
            with self.assertRaisesRegex(AbilityError, 'whole-number'):
                await bot.tree.get_command('roll').callback(interaction, 'Ryujin', 'Speed')
            dice.assert_not_called()

    async def test_roll_uses_two_d10_and_selected_characters_modifier(self):
        bot = main.Bot()
        bot.skills.gids = ('0', '123')
        bot.skills.fetch_tabs = AsyncMock(return_value=(CHARACTERS, SKILLS))
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        with patch('dnd.skills.secrets.randbelow', side_effect=[0, 9]) as dice:
            await bot.tree.get_command('roll').callback(interaction, 'Krusty', 'navigation')
        self.assertEqual(dice.call_count, 2)
        self.assertTrue(all(call.args == (10,) for call in dice.call_args_list))
        description = interaction.followup.send.call_args.kwargs['embed'].description
        self.assertIn('1 + 10', description)
        self.assertIn('**-2**', description)
        self.assertIn('Total: **9**', description)
        with patch('dnd.skills.secrets.randbelow') as dice:
            with self.assertRaises(AbilityError):
                await bot.tree.get_command('roll').callback(interaction, 'Krusty', 'Willpower')
            bot.skills.fetch_tabs.return_value = (CHARACTERS, SKILLS.replace('+5', 'conditional'))
            await bot.skills.load(force=True)
            with self.assertRaisesRegex(AbilityError, 'whole-number'):
                await bot.tree.get_command('roll').callback(interaction, 'Ryujin', 'Willpower')
            dice.assert_not_called()

    async def test_roll_skill_autocomplete_depends_on_character(self):
        bot = main.Bot()
        bot.skills.gids = ('0', '123')
        bot.skills.fetch_tabs = AsyncMock(return_value=(CHARACTERS, SKILLS))
        callback = bot.tree.get_command('roll')._params['skill'].autocomplete
        interaction = SimpleNamespace(namespace=SimpleNamespace(character='Krusty'))
        self.assertEqual([choice.value for choice in await callback(interaction, '')], ['Navigation'])
        interaction.namespace.character = ''
        self.assertEqual(await callback(interaction, ''), [])

    async def test_command_private_and_cache_refresh_atomic(self):
        bot = main.Bot()
        bot.skills.gids = ('0', '123')
        bot.skills.fetch_tabs = AsyncMock(return_value=(CHARACTERS, SKILLS))
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await bot.tree.get_command('skills').callback(interaction, 'Ryujin')
        result = interaction.followup.send.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        self.assertIn('Navigation: +4', result['embed'].description)
        self.assertNotIn('-2', result['embed'].description)
        first = await bot.skills.load()
        bot.skills.fetch_tabs.assert_awaited_once()
        bot.skills.fetch_tabs.return_value = (CHARACTERS, 'Wrong,Headers\n')
        with self.assertRaises(AbilityError):
            await bot.skills.load(force=True)
        self.assertIs(bot.skills.cached, first)

    async def test_missing_configuration_is_clear(self):
        with self.assertRaisesRegex(AbilityError, 'DND_SKILLS_GID'):
            await SkillService('sheet', '0', '').load()
