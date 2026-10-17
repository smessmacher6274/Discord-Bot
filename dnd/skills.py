"""Read-only homebrew skill modifiers; no standard D&D calculations."""
import asyncio
import csv
import io
import re
import secrets
import time
from dataclasses import dataclass
import discord
from discord import app_commands
from dnd.abilities import AbilityError, AbilityService, parse_catalog, required_text, table


@dataclass(frozen=True)
class Skill:
    name: str
    modifier: str
    notes: str = ''


def parse_skills(character_csv, skill_csv):
    reader = csv.reader(io.StringIO(skill_csv.lstrip('\ufeff'), newline=''))
    headers = next(reader, [])
    normalized = io.StringIO(newline='')
    writer = csv.writer(normalized)
    writer.writerow(['skill' if header.strip().casefold() == 'skill name' else header for header in headers])
    writer.writerows(reader)
    skill_csv = normalized.getvalue()
    catalog = parse_catalog(character_csv, 'Ability ID,Ability Name,Description\n',
                            'Character ID,Ability ID\n')
    skills = {identifier: [] for identifier in catalog.characters}
    seen = set()
    for number, row in table(skill_csv, 'Skills', ['character id', 'skill', 'modifier']):
        location = f'Skills row {number}'
        identifier = row['character id'].strip()
        if identifier not in skills:
            raise AbilityError(f'{location}: unknown character ID.')
        name = required_text(row, 'skill', location)
        modifier = row['modifier'].strip()
        if len(modifier) > 500:
            raise AbilityError(f'{location}: modifier must contain at most 500 characters.')
        key = (identifier, name.casefold())
        if key in seen:
            raise AbilityError(f'{location}: duplicate skill for this character.')
        seen.add(key)
        skills[identifier].append(Skill(name, modifier, row.get('notes', '').strip()))
    for entries in skills.values():
        entries.sort(key=lambda skill: skill.name.casefold())
    return catalog, skills


class SkillService(AbilityService):
    def __init__(self, sheet_id, character_gid, skill_gid):
        super().__init__(sheet_id, character_gid)
        self.gids = (character_gid, skill_gid)

    async def load(self, force=False):
        if not self.gids[1]:
            raise AbilityError('Skills are not configured yet. Set DND_SKILLS_GID to the Skills tab GID in .env.')
        async with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.fetched_at < self.cache_seconds:
                return self.cached
            catalog, skills = parse_skills(*(await self.fetch_tabs()))
            self.cached = (catalog, skills)
            self.fetched_at = time.monotonic()
            return self.cached


def skill_response(character, entries, source_url):
    text = '\n'.join(f'{skill.name}: {skill.modifier or "Not set"}' + (f' — {skill.notes}' if skill.notes else '')
                     for skill in entries)
    attachments = []
    if len(text) > 4096:
        attachments = [discord.File(io.BytesIO(text.encode('utf-8')), filename='skill-modifiers.txt')]
        text = text[:3900] + '\n\nAll skill modifiers are included in the attached file.'
    embed = discord.Embed(title=f'{character.name} — Skill modifiers',
                          description=text or 'No skills are recorded for this character yet.', url=source_url)
    embed.set_footer(text=f'{len(entries)} skills | Values from the campaign Sheet')
    return embed, attachments


def register_skill_commands(bot, service, character_service):
    @bot.tree.command(name='skills', description='Show all skill roll modifiers for a character')
    @app_commands.guild_only()
    @app_commands.describe(character='Choose your character')
    async def skills(interaction: discord.Interaction, character: str):
        await interaction.response.defer(ephemeral=True)
        catalog, records = await service.load()
        selected = catalog.character(character)
        embed, files = skill_response(selected, records[selected.id], service.source_url)
        try:
            await interaction.followup.send(embed=embed, files=files, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
        finally:
            for file in files:
                file.close()

    @skills.autocomplete('character')
    async def character_autocomplete(interaction, current):
        catalog = service.cached[0] if service.cached else character_service.cached
        if catalog is None:
            try:
                catalog, _ = await asyncio.wait_for(service.load(), timeout=2)
            except (ValueError, asyncio.TimeoutError):
                return []
        names = sorted((character.name for character in catalog.characters.values()), key=str.casefold)
        return [app_commands.Choice(name=name, value=name) for name in names
                if current.casefold() in name.casefold()][:25]

    @bot.tree.command(name='roll', description='Roll 2d10 plus a character’s skill modifier')
    @app_commands.guild_only()
    @app_commands.describe(character='Choose your character', skill='Choose one of this character’s skills')
    async def roll(interaction: discord.Interaction, character: str, skill: str):
        # Validate before publishing a roll; invalid inputs get a private error.
        await interaction.response.defer()
        catalog, records = await service.load()
        selected = catalog.character(character)
        entry = next((entry for entry in records[selected.id]
                      if entry.name.casefold() == skill.strip().casefold()), None)
        if entry is None:
            raise AbilityError('Skill not found for this character. Choose a skill from autocomplete.')
        if not re.fullmatch(r'[+-]?[0-9]{1,9}', entry.modifier):
            raise AbilityError(f'{entry.name} needs a whole-number modifier to roll (for example +4, 0, or -2).')
        modifier = int(entry.modifier)
        first, second = secrets.randbelow(10) + 1, secrets.randbelow(10) + 1
        embed = discord.Embed(title=f'{selected.name} — {entry.name}',
            description=f'2d10: **{first} + {second}**\nModifier: **{modifier:+d}**\n'
                        f'Total: **{first + second + modifier}**')
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    roll.autocomplete('character')(character_autocomplete)

    @roll.autocomplete('skill')
    async def skill_autocomplete(interaction, current):
        character = getattr(interaction.namespace, 'character', '')
        if not character:
            return []
        try:
            catalog, records = await asyncio.wait_for(service.load(), timeout=2)
            selected = catalog.character(character)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=entry.name, value=entry.name)
                for entry in records[selected.id]
                if current.casefold() in entry.name.casefold()
                and re.fullmatch(r'[+-]?[0-9]{1,9}', entry.modifier)][:25]
