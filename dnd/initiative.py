"""Group initiative from a snapshot of the server's signed-in characters."""
import asyncio
import re
import secrets

import discord
from discord import app_commands
from dnd.tracker import send_tracker


def initiative_order(roster, catalog, records):
    participants = []
    # Validate everyone before rolling so an incomplete roster never yields a partial order.
    for _, identifier in roster:
        character = catalog.characters.get(identifier)
        if character is None:
            raise ValueError('A signed-in character was removed from the Sheet. '
                             'Check /party and have that user /signout or /signin again.')
        willpower = next((skill for skill in records.get(identifier, [])
                         if skill.name.strip().casefold() == 'willpower'), None)
        if willpower is None or not re.fullmatch(r'[+-]?[0-9]{1,9}', willpower.modifier):
            raise ValueError(f'{character.name} needs a whole-number Willpower modifier in the Skills tab '
                             '(for example +7, 0, or -2). No initiative was rolled.')
        participants.append((character, int(willpower.modifier)))
    results = []
    for character, modifier in participants:
        first, second = secrets.randbelow(10) + 1, secrets.randbelow(10) + 1
        results.append((character, first, second, modifier, first + second + modifier))
    return sorted(results, key=lambda row: (-row[4], row[0].name.casefold(), row[0].id))


def register_initiative_command(bot, tracker, skills):
    @bot.tree.command(name='initiative', description='Roll 2d10 + Willpower for all signed-in characters')
    @app_commands.guild_only()
    async def initiative(interaction: discord.Interaction):
        await interaction.response.defer()
        roster = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
        if not roster:
            await interaction.followup.send('No characters are signed in. Use /signin first.', ephemeral=True)
            return
        catalog, records = await skills.load()
        try:
            results = initiative_order(roster, catalog, records)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())
            return
        lines = [f'{position}. **{discord.utils.escape_markdown(character.name)}** — **{total}** '
                 f'(2d10: {first} + {second}; Willpower: {modifier:+d})'
                 for position, (character, first, second, modifier, total) in enumerate(results, 1)]
        lines.append('\nHighest total goes first. Ties are ordered alphabetically. '
                     'Use /turnorder to view this order. Run /initiative again to roll a new order.')
        body = '\n'.join(lines)
        await asyncio.to_thread(tracker.save_turn_order, interaction.guild_id, body)
        await send_tracker(interaction, 'Initiative — Turn order', body)

    @bot.tree.command(name='turnorder', description='Show this server’s latest initiative order without rerolling')
    @app_commands.guild_only()
    async def turnorder(interaction: discord.Interaction):
        await interaction.response.defer()
        body = await asyncio.to_thread(tracker.turn_order, interaction.guild_id)
        if body is None:
            await interaction.followup.send('No turn order saved yet. Use /initiative first.', ephemeral=True)
            return
        await send_tracker(interaction, 'Initiative — Turn order', body)
