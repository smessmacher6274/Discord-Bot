"""Independent turn-duration rolls and voice countdown alerts."""
import asyncio
from array import array
import logging
import math
import re
import secrets
import threading

import discord
from discord import app_commands
from dnd.signin import resolve_character
from dnd.tracker import send_tracker


def turn_minutes(total):
    return max(1, 1 + (total - 14) // 4)


def roll_turn_times(roster, catalog, records):
    participants = []
    for user, identifier in roster:
        character = catalog.characters.get(identifier)
        if character is None:
            raise ValueError('A signed-in character was removed from the Sheet. Check /party.')
        values = {}
        for skill in records.get(identifier, []):
            name = skill.name.strip().casefold()
            if name in ('decipher', 'reflex'):
                if not re.fullmatch(r'[+-]?[0-9]{1,9}', skill.modifier):
                    raise ValueError(f'{character.name} needs whole-number Decipher and Reflex modifiers.')
                values[name] = int(skill.modifier)
        if len(values) != 2:
            raise ValueError(f'{character.name} needs both Decipher and Reflex in the Skills tab.')
        name = max(values, key=values.get)
        participants.append((user, character, name.title(), values[name]))
    results = []
    for user, character, name, modifier in participants:
        dice = [secrets.randbelow(10) + 1 for _ in range(2)]
        total = sum(dice) + modifier
        results.append(dict(user=user, character=character.id, name=character.name,
                            skill=name, modifier=modifier, dice=dice, total=total,
                            minutes=turn_minutes(total)))
    return results


def tone(kind):
    frequencies = {'start': [660, 880], 'warning': [880, 880, 880], 'end': [660, 440, 220]}[kind]
    # Brief lead-in lets a newly speaking voice connection begin transmitting.
    samples = array('h', [0] * (48000 * 2 * 3 // 10))
    for frequency in frequencies:
        for i in range(21600):
            envelope = min(1, i / 240, (21600 - i) / 240)
            value = int(9000 * envelope * math.sin(2 * math.pi * frequency * i / 48000))
            samples.extend((value, value))
        samples.extend([0] * 4800)
    return samples.tobytes()


class ChimeSource(discord.AudioSource):
    """Mix a short PCM chime into music without stopping its audio player."""
    def __init__(self, base=None):
        self.base = base
        self.pending = b''
        self.lock = threading.Lock()

    def add(self, data):
        with self.lock:
            self.pending += data

    def read(self):
        music = self.base.read() if self.base else b''
        with self.lock:
            chime, self.pending = self.pending[:3840], self.pending[3840:]
        if not chime:
            return music
        left = array('h', music.ljust(3840, b'\0'))
        right = array('h', chime.ljust(3840, b'\0'))
        return array('h', (max(-32768, min(32767, a + b)) for a, b in zip(left, right))).tobytes()

    def cleanup(self):
        if self.base:
            self.base.cleanup()


def play_chime(voice, kind, on_error=None):
    if not voice or not voice.is_connected():
        raise ValueError('Voice disconnected; sound could not play.')
    if voice.is_paused():
        raise ValueError('Resume paused music to hear timer sounds.')
    member = getattr(getattr(voice, 'guild', None), 'me', None)
    state = getattr(member, 'voice', None)
    if getattr(state, 'mute', False) is True or getattr(state, 'self_mute', False) is True:
        raise ValueError('The bot is muted in voice. Unmute Whittster’sDisciple before playing timer sounds.')
    if getattr(state, 'suppress', False) is True:
        raise ValueError('Allow the bot to speak on the Stage before playing timer sounds.')
    if member and voice.channel.permissions_for(member).speak is False:
        raise ValueError('Whittster’sDisciple needs Speak permission in this voice channel.')
    data = tone(kind)
    if voice.is_playing():
        source = voice.source
        if source.is_opus():
            raise ValueError('Timer sounds require PCM voice playback.')
        if not isinstance(source, ChimeSource):
            source = ChimeSource(source)
            voice.source = source
        source.add(data)
    else:
        source = ChimeSource()
        source.add(data)
        def complete(error):
            if error:
                logging.error('Timer audio playback failed: %s', type(error).__name__,
                              exc_info=(type(error), error, error.__traceback__))
                if on_error:
                    on_error(error)
        voice.play(source, after=complete)


async def timer_voice(interaction):
    state = getattr(interaction.user, 'voice', None)
    if not state or not state.channel:
        raise ValueError('Join a voice channel to use timer sounds.')
    voice = interaction.guild.voice_client
    if voice and voice.is_connected() and voice.channel.id != state.channel.id:
        raise ValueError('Join the bot’s voice channel first.')
    if not voice or not voice.is_connected():
        try:
            voice = await state.channel.connect(timeout=20, reconnect=True, self_deaf=True)
        except TimeoutError:
            raise ValueError('Discord voice connection timed out. The turn timer did not start; try again.') from None
    return voice


def sound_error_reporter(channel):
    loop = asyncio.get_running_loop()
    async def report():
        try:
            await channel.send('Timer sound playback failed. Text alerts continue; check the bot logs.')
        except discord.HTTPException:
            logging.exception('Could not report timer audio failure')
    def on_error(error):
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(report()))
    return on_error


class TurnTimers:
    def __init__(self):
        self.tasks = {}
        self.locks = {}

    async def stop(self, guild):
        task = self.tasks.pop(guild, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self):
        for guild in list(self.tasks):
            await self.stop(guild)

    async def countdown(self, guild, channel, voice, row, deadline):
        async def announce(kind, text):
            await channel.send(f'<@{row["user"]}> — {row["name"]}: {text}',
                               allowed_mentions=discord.AllowedMentions(users=[discord.Object(row['user'])]))
            try:
                play_chime(voice, kind, on_error=sound_error_reporter(channel))
            except Exception:
                logging.exception('Turn timer sound failed')
                await channel.send('Timer sound unavailable; check the bot’s voice connection.')
        try:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, deadline - 10 - loop.time()))
            await announce('warning', '**10 seconds left!**')
            await asyncio.sleep(max(0, deadline - loop.time()))
            await announce('end', '**Time is up!**')
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception('Turn timer notification failed in guild %s', guild)
        finally:
            if self.tasks.get(guild) is asyncio.current_task():
                self.tasks.pop(guild, None)


def register_turntimer_commands(bot, tracker, skills):
    timers = bot.turn_timers = TurnTimers()
    group = app_commands.Group(name='turntimer', description='Roll and view character turn durations')

    @group.command(name='roll', description='Roll 2d10 plus the higher of Decipher or Reflex for the party')
    @app_commands.guild_only()
    async def roll(interaction: discord.Interaction):
        await interaction.response.defer()
        roster = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
        if not roster:
            raise ValueError('No characters are signed in. Use /signin first.')
        catalog, records = await skills.load()
        rows = roll_turn_times(roster, catalog, records)
        await asyncio.to_thread(tracker.save_turn_times, interaction.guild_id, rows)
        await send_tracker(interaction, 'Turn timer rolls', '\n'.join(
            f'**{row["name"]}** — **{row["minutes"]} min** (2d10: {row["dice"][0]} + '
            f'{row["dice"][1]}; {row["skill"]}: {row["modifier"]:+d}; total: {row["total"]})' for row in rows))

    @group.command(name='view', description='Show saved turn durations without rerolling')
    @app_commands.guild_only()
    async def view(interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await asyncio.to_thread(tracker.turn_times, interaction.guild_id)
        await send_tracker(interaction, 'Turn durations', '\n'.join(
            f'{row["name"]}: **{row["minutes"]} min**' for row in rows) or 'Use /turntimer roll first.')

    @group.command(name='sound', description='Test the turn timer chime in your voice channel')
    @app_commands.guild_only()
    async def sound(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with timers.locks.setdefault(interaction.guild_id, asyncio.Lock()):
            voice = await timer_voice(interaction)
            play_chime(voice, 'start', on_error=sound_error_reporter(interaction.channel))
        await interaction.followup.send(
            'Test chime sent to Whittster’sDisciple’s voice channel. If silent, right-click '
            'Whittster’sDisciple in voice and check its user volume and mute setting. '
            'This does not start or change a turn timer.', ephemeral=True)

    bot.tree.add_command(group)

    @bot.tree.command(name='turnstart', description='Start a character’s rolled turn timer with voice alerts')
    @app_commands.guild_only()
    async def turnstart(interaction: discord.Interaction, character: str = None):
        await interaction.response.defer()
        async with timers.locks.setdefault(interaction.guild_id, asyncio.Lock()):
            catalog, _ = await skills.load()
            selected = catalog.character(await resolve_character(bot, interaction, character))
            roster = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
            user = next((user for user, identifier in roster if identifier == selected.id), None)
            rows = await asyncio.to_thread(tracker.turn_times, interaction.guild_id)
            row = next((row for row in rows if row['character'] == selected.id), None)
            if user is None or row is None:
                raise ValueError('That character must be signed in and included in /turntimer roll first.')
            row = dict(row, user=user)
            voice = await timer_voice(interaction)
            play_chime(voice, 'start', on_error=sound_error_reporter(interaction.channel))
            await timers.stop(interaction.guild_id)
            deadline = asyncio.get_running_loop().time() + row['minutes'] * 60
            timers.tasks[interaction.guild_id] = asyncio.create_task(timers.countdown(
                interaction.guild_id, interaction.channel, voice, row, deadline))
            await interaction.followup.send(
                f'<@{user}> — **{selected.name}**: turn started — **{row["minutes"]} minute(s)**. '
                'Voice alerts at start, 10 seconds left, and time up.',
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(user)]))

    @turnstart.autocomplete('character')
    async def characters(interaction, current):
        catalog, _ = await skills.load()
        roster = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
        return [app_commands.Choice(name=catalog.characters[identifier].name, value=identifier)
                for _, identifier in roster if identifier in catalog.characters
                and current.casefold() in catalog.characters[identifier].name.casefold()][:25]

    @bot.tree.command(name='turnstop', description='Cancel the current turn timer')
    @app_commands.guild_only()
    async def turnstop(interaction: discord.Interaction):
        await interaction.response.defer()
        async with timers.locks.setdefault(interaction.guild_id, asyncio.Lock()):
            await timers.stop(interaction.guild_id)
        await interaction.followup.send('Turn timer stopped.')
