import asyncio
import logging
import shutil
import io
from urllib.parse import urlsplit
import discord
from discord import app_commands
from discord.ext import commands
import config
from providers.licensed_audio import LicensedAudio
from music.resolver import Resolver
from music.player import Player
from music.playlist_import import import_playlist, MAX_BYTES
from providers.youtube import YouTube
from providers.router import ProviderRouter
from music.spotify_session import SpotifySession
from dnd.abilities import AbilityService
from dnd.commands import register_ability_commands
from dnd.skills import SkillService, register_skill_commands
# AI image generation disabled for deployment; implementation kept for later.
# from services.image_generation import ImageGenerator

provider = ProviderRouter(LicensedAudio(config.CATALOG, config.AUDIO_ROOT), YouTube(config.YOUTUBE_NODE_PATH))
resolver = Resolver(provider)

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.players = {}
        self.spotify = SpotifySession(config.SPOTIFY_CLIENT_ID)
        self.abilities = AbilityService(config.DND_SHEET_ID, config.DND_CHARACTERS_GID,
                                        config.DND_ABILITIES_GID, config.DND_CHARACTER_ABILITIES_GID)
        register_ability_commands(self, self.abilities)
        self.skills = SkillService(config.DND_SHEET_ID, config.DND_CHARACTERS_GID, config.DND_SKILLS_GID)
        register_skill_commands(self, self.skills, self.abilities)
        # self.images = ImageGenerator(config.ROOT / '.env', config.OPENAI_API_KEY, config.IMAGE_MODEL)

    async def setup_hook(self):
        if config.DND_SHEET_ID:
            try:
                await self.abilities.load()
            except ValueError as error:
                logging.warning('Ability catalog not loaded: %s', error)
        # Guild registration makes commands available immediately in every installed server.
        async for guild in self.fetch_guilds():
            await self.register_guild(guild)

    async def register_guild(self, guild):
        self.tree.copy_global_to(guild=guild)
        try:
            await self.tree.sync(guild=guild)
            logging.info('Commands registered in guild %s', guild.id)
        except discord.HTTPException:
            logging.exception('Command registration failed in guild %s; check installation scopes', guild.id)

    async def on_guild_join(self, guild):
        await self.register_guild(guild)

    async def close(self):
        self.spotify.clear()
        await asyncio.gather(*(p.close() for p in self.players.values()), return_exceptions=True)
        await super().close()

bot = Bot()

def player_for(interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        raise ValueError('Use this command in a server.')
    voice = interaction.user.voice
    if not voice or not voice.channel:
        raise ValueError('Join a voice channel first.')
    player = bot.players.setdefault(interaction.guild_id, Player(provider, config.FFMPEG))
    if player.voice and player.voice.is_connected() and player.voice.channel.id != voice.channel.id:
        raise ValueError('Join the bot’s voice channel first.')
    return player, voice.channel

def is_spotify_query(query):
    if not query:
        return False
    query = query.strip()
    return query.startswith('spotify:playlist:') or urlsplit(query).hostname == 'open.spotify.com'

async def queue_spotify_export(interaction, result):
    tracks, unavailable = [], []
    for filename, payload in result.files:
        if not filename.endswith('.json'):
            continue
        report = import_playlist(payload, filename, provider, interaction.user.id, youtube_fallback=True)
        tracks.extend(report.tracks)
        unavailable.extend(report.unavailable)
    if len(tracks) > 1000:
        raise ValueError('Playlist exceeds the 1000-song queue limit. Use /spotifyplaylist with autoplay:false to export its parts instead.')
    if tracks:
        # Recheck the user's voice channel after any browser sign-in or API wait.
        player, channel = player_for(interaction)
        async def notify(message):
            await interaction.channel.send(message, allowed_mentions=discord.AllowedMentions.none())
        await player.enqueue(channel, tracks, notify)
    return len(tracks), unavailable

async def spotify_request(interaction, link, autoplay):
    if not await bot.is_owner(interaction.user):
        raise ValueError('Only the bot owner can use the connected personal Spotify account.')
    bot.spotify.validate(link)
    if autoplay:
        player_for(interaction)  # Fail before authorization if the user is not in voice.
    if bot.spotify.client is None:
        await interaction.followup.send('Sign in and approve Spotify playlist access in the browser opening on the bot’s PC. I’ll continue automatically after authorization.', ephemeral=True)
    result = await bot.spotify.export(link)
    queued, unavailable = await queue_spotify_export(interaction, result) if autoplay else (0, [])
    return result, queued, unavailable

@bot.tree.command(description='Play an approved song, source URL, or playlist')
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
async def play(interaction: discord.Interaction, query: str | None = None,
               playlist_file: discord.Attachment | None = None):
    await interaction.response.defer(ephemeral=is_spotify_query(query))
    if bool(query) == bool(playlist_file):
        raise ValueError('Provide either a query or a playlist_file attachment.')
    if is_spotify_query(query):
        result, queued, unavailable = await spotify_request(interaction, query.strip(), True)
        await interaction.followup.send(f'Queued {queued} songs from **{discord.utils.escape_markdown(result.name[:150])}**. '
            f'{result.skipped + len(unavailable)} entries skipped. YouTube matches are found as each song comes up.\n'
            f'Metadata supplied by Spotify: {result.source}', ephemeral=True)
        return
    player, channel = player_for(interaction)
    report = None
    if playlist_file:
        if playlist_file.size > MAX_BYTES:
            raise ValueError('Playlist files must be 256 KB or smaller.')
        payload = await asyncio.wait_for(playlist_file.read(), timeout=15)
        report = import_playlist(payload, playlist_file.filename, provider, interaction.user.id,
                                 youtube_fallback=True)
        tracks = report.tracks
    else:
        tracks = await asyncio.to_thread(resolver.resolve, query, interaction.user.id)
    async def notify(message):
        await interaction.channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    if tracks:
        await player.enqueue(channel, tracks, notify)
    await interaction.followup.send(f'Added {len(tracks)} song(s).' +
                                   (f' Skipped {len(report.unavailable)} ambiguous catalog entries. YouTube matches are found as each song comes up.' if report else ''))
    if report and report.unavailable:
        import io
        await interaction.followup.send('Playlist import report:', ephemeral=True,
            file=discord.File(io.BytesIO('\n'.join(report.unavailable).encode('utf-8')), filename='unavailable.txt'))

@bot.tree.command(description='Pause the current song')
@app_commands.guild_only()
async def pause(interaction: discord.Interaction):
    player, _ = player_for(interaction)
    async with player.lock:
        if not player.voice or not player.voice.is_playing():
            raise ValueError('No song is playing.')
        player.voice.pause()
    await interaction.response.send_message('Paused.')

# AI image command disabled. Uncomment this block and the startup/config wiring to restore.
# computer = app_commands.Group(name='computer', description='Computer commands', guild_only=True)
# computer_show = app_commands.Group(name='show', description='Ask the computer to show an image', parent=computer)
#
# @computer_show.command(name='me', description='Generate an AI image from a prompt')
# @app_commands.guild_only()
# @app_commands.describe(prompt='Describe the image you want to generate')
# @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
# async def show_me(interaction: discord.Interaction, prompt: str):
#     if interaction.user.id not in config.IMAGE_ALLOWED_USER_IDS and not await bot.is_owner(interaction.user):
#         raise ValueError('Image generation is limited to the bot owner and users listed in IMAGE_ALLOWED_USER_IDS because API usage is billed.')
#     if not interaction.app_permissions.attach_files:
#         raise ValueError('Give the bot Attach Files permission in this channel to return generated images.')
#     await interaction.response.defer(thinking=True)
#     limit = min(interaction.guild.filesize_limit, 8 * 1024 * 1024)
#     generated = await bot.images.generate(prompt, interaction.user.id, max_bytes=limit)
#     file = discord.File(io.BytesIO(generated.data), filename=generated.filename)
#     try:
#         await interaction.followup.send('AI-generated image:', file=file, allowed_mentions=discord.AllowedMentions.none())
#     finally:
#         file.close()
#
# bot.tree.add_command(computer)

@bot.tree.command(description='Play a Spotify playlist or export its file (bot owner only)')
@app_commands.guild_only()
@app_commands.describe(link='Spotify playlist URL', autoplay='Queue and play automatically; turn off to export only')
@app_commands.checks.cooldown(1, 15, key=lambda i: i.user.id)
async def spotifyplaylist(interaction: discord.Interaction, link: str, autoplay: bool = True):
    await interaction.response.defer(ephemeral=True)
    result, queued, unavailable = await spotify_request(interaction, link, autoplay)
    action = (f'Queued {queued} songs automatically; {len(unavailable)} ambiguous catalog entries skipped. '
              'YouTube matches are found as each song comes up.' if autoplay else
              'Download the JSON file, then attach it to `/play playlist_file`. For numbered parts, load them in order.')
    summary = (f'Exported **{discord.utils.escape_markdown(result.name[:150])}**: {result.count} songs; '
               f'{result.skipped} skipped entries.\nMetadata supplied by Spotify: {result.source}\n'
               + action)
    for offset in range(0, len(result.files), 10):
        files = [discord.File(io.BytesIO(payload), filename=filename)
                 for filename, payload in result.files[offset:offset + 10]]
        try:
            await interaction.followup.send(summary if offset == 0 else 'More playlist files:',
                                            files=files, ephemeral=True)
        finally:
            for file in files:
                file.close()

@bot.tree.command(description='Forget the connected Spotify session (bot owner only)')
@app_commands.guild_only()
async def spotifydisconnect(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not await bot.is_owner(interaction.user):
        raise ValueError('Only the bot owner can disconnect the personal Spotify account.')
    await bot.spotify.disconnect()
    await interaction.followup.send('Spotify session forgotten. To revoke the app’s Spotify permission too, visit https://www.spotify.com/account/apps/. Previously downloaded files stay with you.', ephemeral=True)

@bot.tree.command(description='Resume the paused song')
@app_commands.guild_only()
async def resume(interaction: discord.Interaction):
    player, _ = player_for(interaction)
    async with player.lock:
        if not player.voice or not player.voice.is_paused():
            raise ValueError('No song is paused.')
        player.voice.resume()
    await interaction.response.send_message('Resumed.')

@bot.tree.command(description='Skip the current song and play the next queued song')
@app_commands.guild_only()
async def skip(interaction: discord.Interaction):
    player, _ = player_for(interaction)
    track = await player.skip()
    await interaction.response.send_message(f'Skipped: {discord.utils.escape_markdown(track.label[:180])}')

class QueuePages(discord.ui.View):
    def __init__(self, tracks, current, user):
        super().__init__(timeout=120)
        self.tracks, self.current, self.user, self.page = tracks, current, user, 0
        self.notice = ''

    def content(self):
        count = max(1, (len(self.tracks) + 9) // 10)
        lines = [f'Now: {self.current.label[:180] if self.current else "Nothing"}',
                 f'{len(self.tracks)} upcoming • Page {self.page + 1}/{count} (snapshot)']
        if self.notice:
            lines.insert(0, self.notice)
        lines.extend(f'{i + 1}. {t.label[:140]}' for i, t in enumerate(self.tracks)
                     if self.page * 10 <= i < (self.page + 1) * 10)
        return discord.utils.escape_mentions(discord.utils.escape_markdown('\n'.join(lines)))

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user:
            return True
        await interaction.response.send_message('Open your own /queue view.', ephemeral=True)
        return False

    @discord.ui.button(label='Previous')
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(content=self.content(), view=self)

    @discord.ui.button(label='Next')
    async def next_page(self, interaction, button):
        self.page = min(max(0, (len(self.tracks) - 1) // 10), self.page + 1)
        await interaction.response.edit_message(content=self.content(), view=self)

    @discord.ui.button(label='Shuffle', style=discord.ButtonStyle.primary)
    async def shuffle_queue(self, interaction, button):
        try:
            player, _ = player_for(interaction)
            async with player.lock:
                count = player.shuffle()
                self.tracks = list(player.upcoming)
                self.current = player.current
            self.page = 0
            self.notice = f'Shuffled {count} upcoming songs.'
            await interaction.response.edit_message(content=self.content(), view=self)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)

    async def on_error(self, interaction, error, item):
        await command_error(interaction, error)

@bot.tree.command(description='Show current and upcoming songs')
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    player = bot.players.get(interaction.guild_id)
    if player:
        async with player.lock:
            view = QueuePages(list(player.upcoming), player.current, interaction.user.id)
    else:
        view = QueuePages([], None, interaction.user.id)
    await interaction.response.send_message(view.content(), view=view, ephemeral=True)

@bot.tree.command(description='Shuffle upcoming songs without interrupting the current song')
@app_commands.guild_only()
async def shuffle(interaction: discord.Interaction):
    player, _ = player_for(interaction)
    async with player.lock:
        count = player.shuffle()
    await interaction.response.send_message(f'Shuffled {count} upcoming songs.')

@bot.tree.command(description='Clear upcoming songs, keeping the current song')
@app_commands.guild_only()
async def removeall(interaction: discord.Interaction):
    player, _ = player_for(interaction)
    async with player.lock:
        count = len(player.upcoming)
        player.upcoming.clear()
    await interaction.response.send_message(f'Removed {count} upcoming songs.')

@bot.tree.command(description='Remove an upcoming song by its 1-based position')
@app_commands.guild_only()
async def removeindex(interaction: discord.Interaction, index: app_commands.Range[int, 1, 1000]):
    player, _ = player_for(interaction)
    async with player.lock:
        track = player.remove(index)
    await interaction.response.send_message(f'Removed: {discord.utils.escape_markdown(track.label[:180])}')

@bot.tree.command(description='Set playback volume from 0 to 100')
@app_commands.guild_only()
async def volume(interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
    player, _ = player_for(interaction)
    async with player.lock:
        player.volume = level / 100
        if player.voice and isinstance(player.voice.source, discord.PCMVolumeTransformer):
            player.voice.source.volume = player.volume
    await interaction.response.send_message(f'Volume: {level}%.')

@bot.tree.error
async def command_error(interaction, error):
    original = getattr(error, 'original', error)
    if isinstance(original, (ValueError, app_commands.CommandOnCooldown)):
        message = str(original)
    else:
        logging.error('Command failed', exc_info=(type(original), original, original.__traceback__))
        message = 'Command failed. Check bot permissions, audio configuration, and the console.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    if not config.TOKEN:
        raise SystemExit('Set DISCORD_BOT_TOKEN in .env first.')
    if not shutil.which(config.FFMPEG):
        raise SystemExit('FFmpeg is missing; install it or set FFMPEG_PATH.')
    bot.run(config.TOKEN)
