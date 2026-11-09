"""Persistent character defaults and the server's signed-in roster."""
import asyncio
import time

import discord
from dnd.visibility import Visibility
from discord import app_commands


async def resolve_character(bot, interaction, character=None):
    if character:
        return character
    if not getattr(interaction, 'guild_id', None) or not getattr(interaction, 'user', None):
        raise ValueError('Choose a character or use /signin character:<name> first.')
    character = await asyncio.to_thread(bot.tracker.signed_character,
                                        interaction.guild_id, interaction.user.id)
    if not character:
        raise ValueError('Choose a character or use /signin character:<name> first.')
    return character


def register_signin_commands(bot, tracker, character_service):
    @bot.tree.command(name='starttime', description='Start a new session’s sign-in timer')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def starttime(interaction: discord.Interaction):
        started = int(interaction.created_at.timestamp())
        await interaction.response.defer()
        session, started = await asyncio.to_thread(
            tracker.start_session, interaction.guild_id, interaction.user.id, started)
        await interaction.followup.send(
            f'Session **{session}** started at <t:{started}:F>. '
            'Everyone: run /signin to record your arrival for this session, even if already signed in. '
            'View times with /attendance.', allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name='attendance', description='Show session sign-in times and elapsed time')
    @app_commands.guild_only()
    async def attendance(interaction: discord.Interaction, session: int = None,
                         visibility: Visibility = Visibility.Hide):
        await interaction.response.defer(ephemeral=visibility != Visibility.Show)
        identifier, started, rows = await asyncio.to_thread(
            tracker.attendance, interaction.guild_id, session)
        catalog = await character_service.load() if rows else None
        lines = [f'Session **{identifier}** — start: <t:{started}:F>']
        for user, character, arrived in rows:
            selected = catalog.characters.get(character)
            label = discord.utils.escape_markdown(selected.name if selected else character)
            minutes, seconds = divmod(arrived - started, 60)
            lines.append(f'<@{user}> — {label}: <t:{arrived}:T> — **{minutes}m {seconds}s** after start')
        if not rows:
            lines.append('No sign-ins recorded for this session yet.')
        chunk = ''
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await interaction.followup.send(chunk, ephemeral=visibility != Visibility.Show,
                                                allowed_mentions=discord.AllowedMentions.none())
                chunk = ''
            chunk += line + '\n'
        await interaction.followup.send(chunk, ephemeral=visibility != Visibility.Show,
                                        allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name='signin', description='Save your character for this server’s commands')
    @app_commands.guild_only()
    async def signin(interaction: discord.Interaction, character: str):
        created_at = getattr(interaction, 'created_at', None)
        arrived = int(created_at.timestamp() if created_at else time.time())
        await interaction.response.defer(ephemeral=True)
        catalog = await character_service.load()
        selected = catalog.character(character)
        timing = await asyncio.to_thread(tracker.signin, interaction.guild_id, interaction.user.id, selected.id, arrived)
        attendance_text = ''
        if timing:
            minutes, seconds = divmod(timing[1] - timing[0], 60)
            attendance_text = f' Session arrival: **{minutes}m {seconds}s** after start (first sign-in retained).'
        await interaction.followup.send(
            f'Signed in as {selected.name}. Commands use this character when you omit character. '
            'Use /signin to switch or /signout to leave the roster.' + attendance_text, ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    @signin.autocomplete('character')
    async def character_autocomplete(interaction, current):
        try:
            catalog = await asyncio.wait_for(character_service.load(), 2)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=c.name, value=c.id)
                for c in sorted(catalog.characters.values(), key=lambda c: c.name.casefold())
                if current.casefold() in c.name.casefold()][:25]

    @bot.tree.command(name='signout', description='Clear your saved character and leave the signed-in roster')
    @app_commands.guild_only()
    async def signout(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(tracker.signout, interaction.guild_id, interaction.user.id)
        await interaction.followup.send('Signed out. Your saved character has been cleared.', ephemeral=True)

    @bot.tree.command(name='party', description='List the characters and users signed in to this server')
    @app_commands.guild_only()
    async def party(interaction: discord.Interaction, visibility: Visibility = Visibility.Hide):
        await interaction.response.defer(ephemeral=visibility != Visibility.Show)
        rows = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
        catalog = await character_service.load() if rows else None
        lines = []
        for user, identifier in rows:
            character = catalog.characters.get(identifier)
            label = character.name if character else 'Character removed from Sheet; sign in again'
            lines.append(f'{discord.utils.escape_markdown(label)} — <@{user}>')
        # Chunk responses so large rosters remain readable within Discord's limits.
        chunk = ''
        for line in lines or ['No characters are signed in. Use /signin to join.']:
            if len(chunk) + len(line) + 1 > 1900:
                await interaction.followup.send(chunk, ephemeral=visibility != Visibility.Show,
                                                allowed_mentions=discord.AllowedMentions.none())
                chunk = ''
            chunk += line + '\n'
        await interaction.followup.send(chunk, ephemeral=visibility != Visibility.Show, allowed_mentions=discord.AllowedMentions.none())
