import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from spotify_export import SpotifyClient, authorize, playlist_id, fetch_playlist, export_payloads, ExportError

@dataclass
class PlaylistExport:
    name: str
    count: int
    skipped: int
    source: str
    files: list[tuple[str, bytes]]

class SpotifySession:
    """One bot-owner account, with an optional private refresh-token cache."""
    def __init__(self, client_id, token_path=None, callback_host='127.0.0.1'):
        self.client_id = client_id
        self.token_path = Path(token_path) if token_path else None
        self.callback_host = callback_host
        self.client = None
        self.lock = asyncio.Lock()
        if self.token_path:
            try:
                saved = json.loads(self.token_path.read_text(encoding='utf-8'))
                token = saved.get('refresh_token') if isinstance(saved, dict) else None
                if saved.get('client_id') == client_id and isinstance(token, str) and token:
                    self.client = SpotifyClient(client_id, {'refresh_token': token}, self.save)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, AttributeError):
                logging.warning('Could not load saved Spotify connection; authorization is required.')

    def save(self):
        if not self.token_path or not self.client:
            return
        token = self.client.tokens.get('refresh_token')
        if not isinstance(token, str) or not token:
            return
        temporary = self.token_path.with_suffix('.tmp')
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'client_id': self.client_id, 'refresh_token': token}, stream)
            if os.name != 'nt':
                temporary.chmod(0o600)
            os.replace(temporary, self.token_path)
        except OSError:
            raise ExportError('Could not save Spotify connection. Check write access to the bot data folder.') from None

    def validate(self, link):
        identifier = playlist_id(link)
        if not re.fullmatch(r'[A-Za-z0-9]{32}', self.client_id):
            raise ExportError('Set SPOTIFY_CLIENT_ID in the bot’s .env and restart. Register http://127.0.0.1:8888/callback in your Spotify app.')
        return identifier

    async def export(self, link, on_authorize=None):
        identifier = self.validate(link)
        if self.lock.locked():
            raise ExportError('Another Spotify request is running. Try again after it finishes.')
        async with self.lock:
            try:
                if self.client is None:
                    if on_authorize is None:
                        self.client = await asyncio.to_thread(authorize, self.client_id)
                    else:
                        loop = asyncio.get_running_loop()
                        def notify(url):
                            asyncio.run_coroutine_threadsafe(on_authorize(url), loop).result(timeout=15)
                        self.client = await asyncio.to_thread(authorize, self.client_id,
                                                             on_url=notify, callback_host=self.callback_host)
                    self.client.on_refresh = self.save
                    await asyncio.to_thread(self.save)
                if not self.client.tokens.get('access_token'):
                    await asyncio.to_thread(self.client.refresh)
                name, rows, skipped, source = await asyncio.to_thread(fetch_playlist, self.client, identifier)
            except ExportError as error:
                if 'expired' in str(error) or 'revoked' in str(error) or 'signing in' in str(error):
                    self.clear(forget=True)
                raise
            files, info = await asyncio.to_thread(export_payloads, identifier, name, rows, skipped, source)
            return PlaylistExport(name, len(rows), len(skipped), source, files + [info])

    def clear(self, forget=False):
        if forget and self.token_path:
            try:
                self.token_path.unlink(missing_ok=True)
            except OSError:
                raise ExportError('Could not remove saved Spotify connection. Check data folder permissions.') from None
        if self.client:
            self.client.tokens.clear()
        self.client = None

    async def disconnect(self):
        if self.lock.locked():
            raise ExportError('Wait for the current Spotify request to finish, then disconnect.')
        async with self.lock:
            await asyncio.to_thread(self.clear, forget=True)
