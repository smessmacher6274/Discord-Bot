import csv
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from dnd.abilities import AbilityError, AbilityService, parse_catalog
from dnd.commands import AbilitySelect, AbilityView
import main

CHARACTERS = 'Character,Character ID\nRyujin,CHR-8F2C9A\nKrusty,CHR-B741E6\n'
ABILITIES = 'Ability ID,Ability Name,Description\nABL1,Bijuu Transformation,"Line one\nLine two, with comma"\n'
ASSIGNMENTS = 'Character ID,Ability ID\nCHR-8F2C9A,ABL1\n'

class CatalogTests(unittest.TestCase):
    def test_correct_character_and_verbatim_multiline_description(self):
        catalog = parse_catalog(CHARACTERS, ABILITIES, ASSIGNMENTS)
        character = catalog.character(' ryUJIN ')
        self.assertEqual(character.id, 'CHR-8F2C9A')
        self.assertEqual(catalog.assignments[character.id][0].ability_id, 'ABL1')
        self.assertEqual(catalog.abilities['ABL1'].description, 'Line one\nLine two, with comma')
        self.assertEqual(catalog.assignments[catalog.character('Krusty').id], [])

    def test_invalid_keys_and_duplicate_records_are_reported(self):
        cases = [(CHARACTERS + 'Ryujin,OTHER\n', ABILITIES, ASSIGNMENTS),
                 (CHARACTERS, ABILITIES + 'ABL1,Duplicate,Text\n', ASSIGNMENTS),
                 (CHARACTERS, ABILITIES, ASSIGNMENTS + 'MISSING,ABL1\n'),
                 (CHARACTERS, ABILITIES, ASSIGNMENTS + 'CHR-8F2C9A,MISSING\n'),
                 (CHARACTERS, ABILITIES, ASSIGNMENTS + 'CHR-8F2C9A,ABL1\n'),
                 ('Wrong,Headers\n', ABILITIES, ASSIGNMENTS)]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(AbilityError):
                parse_catalog(*data)

    def test_character_notes_are_optional(self):
        catalog = parse_catalog(CHARACTERS, ABILITIES,
            'Character ID,Ability ID,Character Notes\nCHR-8F2C9A,ABL1,Use once per rest\n')
        self.assertEqual(catalog.assignments['CHR-8F2C9A'][0].notes, 'Use once per rest')

class AbilityTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        service = AbilityService('test-sheet')
        service.fetch_tabs = AsyncMock(return_value=(CHARACTERS, ABILITIES, ASSIGNMENTS))
        return service

    def interaction(self, user_id=42):
        return SimpleNamespace(user=SimpleNamespace(id=user_id),
            response=SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_cache_and_atomic_refresh(self):
        service = self.service()
        first = await service.load()
        self.assertIs(await service.load(), first)
        service.fetch_tabs.assert_awaited_once()
        service.fetch_tabs.return_value = (CHARACTERS, ABILITIES, 'bad,headers\n')
        with self.assertRaises(AbilityError):
            await service.load(force=True)
        self.assertIs(service.cached, first)

    async def test_command_and_selection_without_voice(self):
        bot = main.Bot()
        bot.abilities.fetch_tabs = AsyncMock(return_value=(CHARACTERS, ABILITIES, ASSIGNMENTS))
        interaction = self.interaction()
        await bot.tree.get_command('abilities').callback(interaction, 'Ryujin')
        result = interaction.followup.send.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        view = result['view']
        select = next(child for child in view.children if isinstance(child, AbilitySelect))
        self.assertEqual(select.options[0].label, 'Bijuu Transformation')
        await view.show_ability(interaction, 'ABL1')
        self.assertEqual(interaction.response.edit_message.call_args.kwargs['embed'].description, 'Line one\nLine two, with comma')

    async def test_other_users_cannot_control_private_menu(self):
        service = self.service()
        view = AbilityView(service, await service.load(), 'CHR-8F2C9A', 42)
        self.assertFalse(await view.interaction_check(self.interaction(99)))

    async def test_ability_type_is_shown_when_present(self):
        service = self.service()
        service.fetch_tabs.return_value = (CHARACTERS,
            'Ability ID,Ability Name,Description,Type\nABL1,Bijuu Transformation,Original description,Subaction\n',
            ASSIGNMENTS)
        view = AbilityView(service, await service.load(), 'CHR-8F2C9A', 42)
        embed, _ = view.embed('ABL1')
        self.assertEqual(embed.description, 'Original description')
        self.assertEqual([(field.name, field.value) for field in embed.fields], [('Type', 'Subaction')])
        service.fetch_tabs.return_value = (CHARACTERS, ABILITIES, ASSIGNMENTS)
        view = AbilityView(service, await service.load(force=True), 'CHR-8F2C9A', 42)
        self.assertEqual(view.embed('ABL1')[0].fields, [])

    async def test_empty_character_and_foreign_ability(self):
        service = self.service()
        view = AbilityView(service, await service.load(), 'CHR-B741E6', 42)
        embed, _ = view.embed()
        self.assertIn('No abilities', embed.description)
        self.assertFalse(any(isinstance(child, AbilitySelect) for child in view.children))
        with self.assertRaises(AbilityError):
            view.embed('ABL1')

    async def test_dropdown_pagination_over_25_abilities(self):
        service = self.service()
        definitions = io.StringIO(newline='')
        writer = csv.writer(definitions)
        writer.writerow(['Ability ID', 'Ability Name', 'Description'])
        assignments = 'Character ID,Ability ID\n'
        for index in range(30):
            writer.writerow([f'A{index}', f'Ability {index:02}', 'Description'])
            assignments += f'CHR-8F2C9A,A{index}\n'
        service.fetch_tabs.return_value = (CHARACTERS, definitions.getvalue(), assignments)
        view = AbilityView(service, await service.load(), 'CHR-8F2C9A', 42)
        self.assertEqual(len(next(child for child in view.children if isinstance(child, AbilitySelect)).options), 25)
        await view.next_page.callback(self.interaction())
        self.assertEqual(len(next(child for child in view.children if isinstance(child, AbilitySelect)).options), 5)

    async def test_long_description_is_available_in_full(self):
        service = self.service()
        definitions = 'Ability ID,Ability Name,Description\nABL1,Long Ability,' + 'x' * 5000 + '\n'
        service.fetch_tabs.return_value = (CHARACTERS, definitions, ASSIGNMENTS)
        view = AbilityView(service, await service.load(), 'CHR-8F2C9A', 42)
        embed, files = view.embed('ABL1')
        try:
            self.assertLessEqual(len(embed.description), 4096)
            self.assertEqual(files[0].fp.read().decode(), 'x' * 5000)
        finally:
            for file in files:
                file.close()

    async def test_refresh_updates_character_menu(self):
        service = self.service()
        view = AbilityView(service, await service.load(), 'CHR-8F2C9A', 42)
        service.fetch_tabs.return_value = (CHARACTERS, ABILITIES, 'Character ID,Ability ID\n')
        interaction = self.interaction()
        await view.refresh.callback(interaction)
        self.assertEqual(view.entries(), [])
        interaction.edit_original_response.assert_awaited_once()
