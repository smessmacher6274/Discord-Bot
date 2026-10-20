import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main
from dnd.abilities import AbilityError
from dnd.damage import parse_damage, damage_response

DATA = 'Weapon Type,Melee,Ranged,Damage roll\nSword,5 ft,—,2d6\nBow,,100 ft,1d8\n'


class DamageTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_autocomplete_and_cache(self):
        bot = main.Bot()
        bot.damage.fetch_tabs = AsyncMock(return_value=[DATA])
        command = bot.tree.get_command('damage')
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        choices = await command._params['weapon'].autocomplete(interaction, 'swo')
        self.assertEqual([choice.value for choice in choices], ['Sword'])
        await command.callback(interaction, ' sword ')
        result = interaction.followup.send.call_args.kwargs
        self.assertTrue(result['ephemeral'])
        self.assertEqual([(field.name, field.value) for field in result['embed'].fields],
                         [('Melee', '5 ft'), ('Ranged', '—'), ('Damage roll', '2d6')])
        self.assertTrue(result['embed'].url.endswith('#gid=404740668'))
        bot.damage.fetch_tabs.assert_awaited_once()
        with self.assertRaisesRegex(AbilityError, 'Weapon not found'):
            await command.callback(interaction, 'missing')
        previous = bot.damage.cached
        bot.damage.fetch_tabs.return_value = ['Wrong,Headers\n']
        with self.assertRaises(AbilityError):
            await bot.damage.load(force=True)
        self.assertIs(bot.damage.cached, previous)

    async def test_validation_blanks_and_long_values(self):
        weapons = parse_damage(DATA)
        embed, _ = damage_response(weapons['bow'], 'https://example.com')
        self.assertEqual(embed.fields[0].value, 'Not set')
        for invalid in [DATA + 'sword,1,2,3\n', 'Weapon Type,Melee,Ranged\n',
                        'Weapon Type,Melee,Ranged,Damage roll\n,1,2,3\n']:
            with self.assertRaises(AbilityError):
                parse_damage(invalid)
        long_value = 'x' * 2000
        weapon = parse_damage(DATA + f'Spear,{long_value},20 ft,1d6\n')['spear']
        embed, files = damage_response(weapon, 'https://example.com')
        try:
            self.assertEqual(len(embed.fields[0].value), 1024)
            self.assertIn(long_value, files[0].fp.read().decode())
        finally:
            for file in files:
                file.close()
