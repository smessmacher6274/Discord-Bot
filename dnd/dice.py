"""Custom dice and persistent, capped shinobi points."""
import asyncio
import secrets

import discord
from dnd.visibility import Visibility
from discord import app_commands
from dnd.signin import resolve_character


def register_dice_commands(bot, tracker, characters):
    @bot.tree.command(name='dice', description='Roll custom dice; damage/healing maximums can earn a shinobi point')
    @app_commands.guild_only()
    @app_commands.describe(dice='Number of dice (1-100)', faces='Faces per die (2-1000)',
                           damage_healing='True for damage/healing: any maximum die earns a shinobi point')
    async def dice(interaction: discord.Interaction, dice: app_commands.Range[int, 1, 100],
                   faces: app_commands.Range[int, 2, 1000], damage_healing: bool):
        await interaction.response.defer()
        if not 1 <= dice <= 100 or not 2 <= faces <= 1000:
            raise ValueError('Use 1-100 dice with 2-1000 faces each.')
        character = None
        if damage_healing:
            character = await resolve_character(bot, interaction)
            catalog = await characters.load()
            character = catalog.character(character)
        values = [secrets.randbelow(faces) + 1 for _ in range(dice)]
        text = f'Dice: {", ".join(map(str, values))}\nTotal: **{sum(values)}**'
        if character and faces in values:
            awarded = await asyncio.to_thread(tracker.award_shinobi, interaction.guild_id, character.id)
            text += ('\nShinobi point earned! You now have **1/1**.' if awarded else
                     "\nShould've used your shinobi point dumbass")
        elif character:
            text += '\nNo maximum die rolled; no shinobi point earned.'
        label = f'{character.name} - ' if character else ''
        await interaction.followup.send(embed=discord.Embed(title=f'{label}{dice}d{faces}', description=text),
                                        allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name='shinobi', description='Show party shinobi points, or spend your saved point')
    @app_commands.guild_only()
    @app_commands.describe(use='Spend your signed-in character’s point', visibility='Show to everyone or Hide so only you can see it')
    async def shinobi(interaction: discord.Interaction, use: bool = False, visibility: Visibility = Visibility.Hide):
        await interaction.response.defer(ephemeral=visibility != Visibility.Show)
        prefix = ''
        if use:
            identifier = await resolve_character(bot, interaction)
            spent = await asyncio.to_thread(tracker.use_shinobi, interaction.guild_id, identifier)
            prefix = ('Shinobi point used.\n\n' if spent else 'You have no shinobi point to use.\n\n')
        rows = await asyncio.to_thread(tracker.party_points, interaction.guild_id)
        catalog = await characters.load() if rows else None
        lines = []
        for user, identifier, points in rows:
            character = catalog.characters.get(identifier)
            label = character.name if character else 'Unavailable character'
            lines.append(f'{discord.utils.escape_markdown(label)} (<@{user}>): **{points}/1**')
        text = prefix + ('\n'.join(lines) or 'No party members. Use /signin first.')
        # Text chunks also accommodate unusually large parties.
        while text:
            split = text.rfind('\n', 0, 1900) if len(text) > 1900 else len(text)
            if split <= 0:
                split = 1900
            await interaction.followup.send(text[:split], ephemeral=visibility != Visibility.Show,
                                            allowed_mentions=discord.AllowedMentions.none())
            text = text[split:].lstrip('\n')
