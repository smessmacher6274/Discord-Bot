import asyncio
from dataclasses import dataclass
import re
from spotify_export import authorize, playlist_id, fetch_playlist, export_payloads, ExportError

@dataclass
class PlaylistExport:
    name: str
    count: int
    skipped: int
    source: str
    files: list[tuple[str, bytes]]

class SpotifySession:
    """One local bot-owner Spotify account. No persisted tokens or playlist files."""
    def __init__(self, client_id):
        self.client_id = client_id
        self.client = None
        self.lock = asyncio.Lock()

    def validate(self, link):
        identifier = playlist_id(link)
        if not re.fullmatch(r'[A-Za-z0-9]{32}', self.client_id):
            raise ExportError('Set SPOTIFY_CLIENT_ID in the bot’s .env and restart. Register http://127.0.0.1:8888/callback in your Spotify app.')
        return identifier

    async def export(self, link):
        identifier = self.validate(link)
        if self.lock.locked():
            raise ExportError('Another Spotify request is running. Try again after it finishes.')
        async with self.lock:
            if self.client is None:
                self.client = await asyncio.to_thread(authorize, self.client_id)
            try:
                name, rows, skipped, source = await asyncio.to_thread(fetch_playlist, self.client, identifier)
            except ExportError as error:
                if 'expired' in str(error) or 'revoked' in str(error) or 'signing in' in str(error):
                    self.clear()
                raise
            files, info = await asyncio.to_thread(export_payloads, identifier, name, rows, skipped, source)
            return PlaylistExport(name, len(rows), len(skipped), source, files + [info])

    def clear(self):
        if self.client:
            self.client.tokens.clear()
        self.client = None

    async def disconnect(self):
        if self.lock.locked():
            raise ExportError('Wait for the current Spotify request to finish, then disconnect.')
        async with self.lock:
            self.clear()
