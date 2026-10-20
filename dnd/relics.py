"""Read relic descriptions from the campaign Sheet."""
import asyncio
import io
import time
from dataclasses import dataclass

import discord
from discord import app_commands
from dnd.abilities import AbilityError, AbilityService, required_text, table


@dataclass(frozen=True)
class Relic:
    name: str
    description: str
    id: str = ''


def parse_relics(text):
    relics = {}
    names = set()
    for number, row in table(text, 'Relics', ['relic id', 'relic name', 'description']):
        location = f'Relics row {number}'
        identifier = required_text(row, 'relic id', location)
        name = required_text(row, 'relic name', location)
        if not row['description'].strip():
            raise AbilityError(f'{location}: description is blank.')
        key = identifier.casefold()
        if key in relics:
            raise AbilityError(f'{location}: duplicate relic ID {identifier}.')
        if name.casefold() in names:
            raise AbilityError(f'{location}: duplicate relic name {name}.')
        names.add(name.casefold())
        relics[key] = Relic(name, row['description'], identifier)
    return relics


class RelicService(AbilityService):
    def __init__(self, sheet_id, gid=''):
        super().__init__(sheet_id)
        self.gids = (gid,)

    @property
    def source_url(self):
        return f'https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit#gid={self.gids[0]}'

    async def load(self, force=False):
        if not self.gids[0]:
            raise AbilityError('Relics are not configured yet. Set DND_RELICS_GID to the Relics tab GID in .env.')
        async with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.fetched_at < self.cache_seconds:
                return self.cached
            relics = parse_relics((await self.fetch_tabs())[0])
            self.cached = relics
            self.fetched_at = time.monotonic()
            return relics


def relic_response(relic, source_url):
    description = relic.description
    files = []
    if len(description) > 4096:
        files.append(discord.File(io.BytesIO(description.encode('utf-8')), filename='relic-description.txt'))
        description = description[:3900] + '\n\nFull description attached as a text file.'
    embed = discord.Embed(title=relic.name, description=description, url=source_url)
    return embed, files


def register_relic_commands(bot, service):
    @bot.tree.command(name='relic', description='Look up a relic’s description')
    @app_commands.guild_only()
    @app_commands.describe(relic='Choose a relic')
    async def relic(interaction: discord.Interaction, relic: str):
        await interaction.response.defer(ephemeral=True)
        relics = await service.load()
        selected = relics.get(relic.strip().casefold())
        if selected is None:
            selected = next((entry for entry in relics.values()
                             if entry.name.casefold() == relic.strip().casefold()), None)
        if selected is None:
            raise AbilityError('Relic not found. Choose a relic from autocomplete.')
        embed, files = relic_response(selected, service.source_url)
        try:
            await interaction.followup.send(embed=embed, files=files, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()

    @relic.autocomplete('relic')
    async def relic_autocomplete(interaction, current):
        try:
            relics = await asyncio.wait_for(service.load(), timeout=2)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=entry.name, value=entry.id)
                for entry in sorted(relics.values(), key=lambda entry: entry.name.casefold())
                if current.casefold() in entry.name.casefold() or current.casefold() in entry.id.casefold()][:25]
