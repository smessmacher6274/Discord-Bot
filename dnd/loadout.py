"""Character relic holdings joined by the campaign's character IDs."""
import asyncio
import io
import time

import discord
from discord import app_commands
from dnd.abilities import AbilityError, AbilityService, parse_catalog, required_text, table


def parse_loadouts(character_csv, holdings_csv):
    catalog = parse_catalog(character_csv, 'Ability ID,Ability Name,Description\n',
                            'Character ID,Ability ID\n')
    holdings = {identifier: [] for identifier in catalog.characters}
    seen = set()
    for number, row in table(holdings_csv, 'Character Relics', ['character id', 'relic name']):
        location = f'Character Relics row {number}'
        identifier = row['character id'].strip()
        if identifier not in holdings:
            raise AbilityError(f'{location}: unknown character ID.')
        name = required_text(row, 'relic name', location)
        key = (identifier, name.casefold())
        if key in seen:
            raise AbilityError(f'{location}: duplicate relic for this character.')
        seen.add(key)
        holdings[identifier].append(name)
    for names in holdings.values():
        names.sort(key=str.casefold)
    return catalog, holdings


class LoadoutService(AbilityService):
    def __init__(self, sheet_id, character_gid, holdings_gid=''):
        super().__init__(sheet_id, character_gid)
        self.gids = (character_gid, holdings_gid)

    async def load(self, force=False):
        if not self.gids[1]:
            raise AbilityError('Loadouts are not configured yet. Set DND_CHARACTER_RELICS_GID in .env.')
        async with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.fetched_at < self.cache_seconds:
                return self.cached
            result = parse_loadouts(*(await self.fetch_tabs()))
            self.cached = result
            self.fetched_at = time.monotonic()
            return result


def loadout_response(character, relics, source_url):
    text = '\n'.join(f'• {name}' for name in relics)
    files = []
    if len(text) > 4096:
        files.append(discord.File(io.BytesIO(text.encode('utf-8')), filename='character-loadout.txt'))
        text = text[:3900] + '\n\nFull loadout attached as a text file.'
    embed = discord.Embed(title=f'{character.name} — Relic loadout', url=source_url,
                          description=text or 'This character holds no relics.')
    embed.set_footer(text=f'Character ID: {character.id} | {len(relics)} relics')
    return embed, files


def register_loadout_commands(bot, service):
    @bot.tree.command(name='loadout', description='Show all relics held by a character')
    @app_commands.guild_only()
    @app_commands.describe(character='Choose a character or enter their Character ID')
    async def loadout(interaction: discord.Interaction, character: str):
        await interaction.response.defer(ephemeral=True)
        catalog, holdings = await service.load()
        selected = catalog.character(character)
        embed, files = loadout_response(selected, holdings[selected.id], service.source_url)
        try:
            await interaction.followup.send(embed=embed, files=files, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()

    @loadout.autocomplete('character')
    async def character_autocomplete(interaction, current):
        try:
            catalog, _ = await asyncio.wait_for(service.load(), timeout=2)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=character.name, value=character.id)
                for character in sorted(catalog.characters.values(), key=lambda entry: entry.name.casefold())
                if current.casefold() in character.name.casefold()
                or current.casefold() in character.id.casefold()][:25]
