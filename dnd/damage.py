"""Read weapon ranges and damage directly from the campaign Sheet."""
import asyncio
import io
import time
from dataclasses import dataclass

import discord
from discord import app_commands
from dnd.abilities import AbilityError, AbilityService, required_text, table


@dataclass(frozen=True)
class Weapon:
    name: str
    melee: str
    ranged: str
    damage_roll: str


def parse_damage(text):
    weapons = {}
    for number, row in table(text, 'Damage ranges', ['weapon type', 'melee', 'ranged', 'damage roll']):
        name = required_text(row, 'weapon type', f'Damage ranges row {number}')
        key = name.casefold()
        if key in weapons:
            raise AbilityError(f'Damage ranges row {number}: duplicate weapon type {name}.')
        weapons[key] = Weapon(name, row['melee'], row['ranged'], row['damage roll'])
    return weapons


class DamageService(AbilityService):
    def __init__(self, sheet_id, gid='404740668'):
        super().__init__(sheet_id)
        self.gids = (gid,)

    @property
    def source_url(self):
        return f'https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit#gid={self.gids[0]}'

    async def load(self, force=False):
        async with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.fetched_at < self.cache_seconds:
                return self.cached
            weapons = parse_damage((await self.fetch_tabs())[0])
            self.cached = weapons
            self.fetched_at = time.monotonic()
            return weapons


def damage_response(weapon, source_url):
    embed = discord.Embed(title=weapon.name, url=source_url)
    fields = [('Melee', weapon.melee), ('Ranged', weapon.ranged), ('Damage roll', weapon.damage_roll)]
    files = []
    if any(len(value) > 1024 for _, value in fields):
        text = weapon.name + '\n\n' + '\n\n'.join(f'{name}: {value}' for name, value in fields)
        files.append(discord.File(io.BytesIO(text.encode('utf-8')), filename='weapon-damage.txt'))
        embed.set_footer(text='Full values attached as a text file.')
    for name, value in fields:
        embed.add_field(name=name, value=(value if value.strip() else 'Not set')[:1024], inline=False)
    return embed, files


def register_damage_commands(bot, service):
    @bot.tree.command(name='damage', description='Look up a weapon’s melee range, ranged range, and damage roll')
    @app_commands.guild_only()
    @app_commands.describe(weapon='Choose a weapon type from Damage ranges')
    async def damage(interaction: discord.Interaction, weapon: str):
        await interaction.response.defer(ephemeral=True)
        weapons = await service.load()
        selected = weapons.get(weapon.strip().casefold())
        if selected is None:
            raise AbilityError('Weapon not found. Choose a weapon from autocomplete.')
        embed, files = damage_response(selected, service.source_url)
        try:
            await interaction.followup.send(embed=embed, files=files, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()

    @damage.autocomplete('weapon')
    async def weapon_autocomplete(interaction, current):
        try:
            weapons = await asyncio.wait_for(service.load(), timeout=2)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=entry.name, value=entry.name)
                for entry in sorted(weapons.values(), key=lambda entry: entry.name.casefold())
                if current.casefold() in entry.name.casefold()][:25]
