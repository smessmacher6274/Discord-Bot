import asyncio
import logging
import discord
from music.queue_manager import GuildQueue

class Player(GuildQueue):
    def __init__(self, provider, ffmpeg, idle_timeout=600):
        super().__init__()
        self.provider, self.ffmpeg = provider, ffmpeg
        self.voice = None
        self.channel = None
        self.task = None
        self.idle_task = None
        self.idle_timeout = idle_timeout
        self.lifecycle_lock = asyncio.Lock()

    async def enqueue(self, channel, tracks, notify):
        async with self.lifecycle_lock:
            await self._enqueue(channel, tracks, notify)

    async def _enqueue(self, channel, tracks, notify):
        async with self.lock:
            if self.voice and self.voice.is_connected() and self.voice.channel.id != channel.id:
                raise ValueError('Join the bot’s current voice channel to control playback.')
            self.channel = channel
            if not self.voice or not self.voice.is_connected():
                self.voice = channel.guild.voice_client
                if self.voice:
                    await self.voice.disconnect(force=True)
                self.voice = await channel.connect(timeout=20, reconnect=True, self_deaf=True)
            if len(self.upcoming) + len(tracks) > 1000:
                raise ValueError('Queue limit is 1000 upcoming songs.')
            self.upcoming.extend(tracks)
            if not self.task or self.task.done():
                self.task = asyncio.create_task(self.run(notify))
            if not self.idle_task or self.idle_task.done():
                self.idle_task = asyncio.create_task(self.watch_idle())

    async def watch_idle(self):
        loop = asyncio.get_running_loop()
        idle_since = loop.time()
        while True:
            await asyncio.sleep(min(5, self.idle_timeout))
            async with self.lifecycle_lock:
                if not self.voice or not self.voice.is_connected():
                    return
                if self.voice.is_playing():
                    idle_since = None
                elif idle_since is None:
                    idle_since = loop.time()
                elif loop.time() - idle_since >= self.idle_timeout:
                    await self._close()
                    return

    async def skip(self):
        async with self.lock:
            if not self.current or not self.voice or not (
                    self.voice.is_playing() or self.voice.is_paused()):
                raise ValueError('No active song to skip. If a song is loading, try again shortly.')
            track = self.current
            # stop() also ends paused audio and invokes the normal completion callback.
            self.voice.stop()
            return track

    async def run(self, notify):
        try:
            while True:
                async with self.lock:
                    if not self.upcoming:
                        self.current = None
                        return
                    self.current = self.upcoming.popleft()
                    track = self.current
                source = None
                try:
                    if track.provider == 'youtube_search':
                        track = await asyncio.to_thread(self.provider.prepare_track, track)
                        async with self.lock:
                            self.current = track
                        await notify(f'YouTube match: {track.label}\n{track.source_url}')
                    if not self.voice.is_connected():
                        await self.voice.disconnect(force=True)
                        self.voice = await self.channel.connect(timeout=20, reconnect=True, self_deaf=True)
                    if track.attribution:
                        # Publish the recording's required credit before broadcasting it.
                        await notify(f'Now playing: {track.label}\n{track.attribution}')
                    stream = await asyncio.to_thread(self.provider.get_stream, track)
                    if track.provider == 'youtube':
                        before = '-nostdin -protocol_whitelist https,tls,tcp,crypto,pipe -rw_timeout 15000000 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
                    else:
                        before = '-nostdin -protocol_whitelist file,pipe'
                    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(
                        stream, executable=self.ffmpeg, before_options=before, options='-vn'), self.volume)
                    loop = asyncio.get_running_loop()
                    finished = loop.create_future()
                    def complete(error):
                        def deliver():
                            if not finished.done():
                                finished.set_result(error)
                        loop.call_soon_threadsafe(deliver)
                    self.voice.play(source, after=complete)
                    while not finished.done():
                        await asyncio.wait([finished], timeout=2)
                        if not self.voice.is_connected():
                            self.voice.stop()
                            raise RuntimeError('Voice disconnected')
                    if finished.result():
                        raise finished.result()
                except Exception as error:
                    logging.exception('Playback failed')
                    try:
                        detail = str(error)[:500] if isinstance(error, ValueError) else 'playback failed; check the bot console.'
                        await notify(f'Skipped {track.title[:100]}: {detail}')
                    except discord.HTTPException:
                        pass
                finally:
                    if source:
                        source.cleanup()
                    async with self.lock:
                        self.current = None
        finally:
            self.current = None

    async def close(self):
        async with self.lifecycle_lock:
            await self._close()

    async def _close(self):
        idle_task = self.idle_task
        self.idle_task = None
        if idle_task and idle_task is not asyncio.current_task():
            idle_task.cancel()
            await asyncio.gather(idle_task, return_exceptions=True)
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.voice:
            self.voice.stop()
            await self.voice.disconnect(force=True)
            self.voice = None
        self.upcoming.clear()
        self.current = None
        self.channel = None
