"""User-authorized Spotify playlist metadata export. No audio or bot connection."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import webbrowser
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPES = 'playlist-read-private playlist-read-collaborative'
MAX_FILE_BYTES = 256 * 1024

class ExportError(ValueError):
    pass

def playlist_id(value):
    if value.startswith('spotify:playlist:'):
        identifier = value.removeprefix('spotify:playlist:')
    elif re.fullmatch(r'[A-Za-z0-9]{22}', value):
        identifier = value
    else:
        try:
            parsed = urlsplit(value)
            if (parsed.scheme != 'https' or parsed.hostname != 'open.spotify.com'
                    or parsed.username or parsed.password or parsed.port not in (None, 443)):
                raise ValueError
            match = re.fullmatch(r'/(?:intl-[a-z]{2}/)?playlist/([A-Za-z0-9]{22})/?', parsed.path)
            if not match:
                raise ValueError
            identifier = match[1]
        except ValueError:
            raise ExportError('Use a Spotify playlist URL, playlist URI, or 22-character playlist ID.') from None
    if not re.fullmatch(r'[A-Za-z0-9]{22}', identifier):
        raise ExportError('Invalid Spotify playlist ID.')
    return identifier

def authorization_url(client_id, verifier, state):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')
    return 'https://accounts.spotify.com/authorize?' + urlencode({
        'client_id': client_id, 'response_type': 'code', 'redirect_uri': REDIRECT_URI,
        'scope': SCOPES, 'state': state, 'code_challenge_method': 'S256', 'code_challenge': challenge})

def callback_code(path, state):
    parsed = urlsplit(path)
    if parsed.path != '/callback':
        raise ExportError('Unexpected OAuth callback path.')
    query = parse_qs(parsed.query)
    received = query.get('state', [''])
    if len(received) != 1 or not secrets.compare_digest(received[0], state):
        raise ExportError('Authorization state mismatch. Restart the exporter.')
    if 'error' in query:
        raise ExportError('Spotify authorization was declined. No playlist was exported.')
    codes = query.get('code', [])
    if len(codes) != 1 or not codes[0]:
        raise ExportError('Spotify did not provide an authorization code.')
    return codes[0]

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def http_json(url, *, data=None, token=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'PersonalPlaylistExporter/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    payload = urlencode(data).encode() if data is not None else None
    if payload is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = Request(url, data=payload, headers=headers)
    try:
        with build_opener(NoRedirect()).open(req, timeout=20) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ExportError('Spotify returned an unexpected response.')
        return result
    except (URLError, socket.timeout, TimeoutError) as error:
        if isinstance(error, HTTPError):
            raise
        raise ExportError('Cannot reach Spotify. Check your connection and try again.') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ExportError('Spotify returned invalid JSON.') from None

class SpotifyClient:
    def __init__(self, client_id, tokens):
        self.client_id = client_id
        self.tokens = tokens  # In memory only; never printed or persisted.

    def refresh(self):
        refresh_token = self.tokens.get('refresh_token')
        if not refresh_token:
            raise ExportError('Spotify session expired. Run the exporter and sign in again.')
        try:
            updated = http_json('https://accounts.spotify.com/api/token', data={
                'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': self.client_id})
        except HTTPError:
            raise ExportError('Spotify authorization expired or was revoked. Sign in again.') from None
        if not updated.get('access_token'):
            raise ExportError('Spotify did not provide a refreshed access token.')
        self.tokens.update(updated)

    def get(self, path):
        if not path.startswith('/playlists/'):
            raise ExportError('Unexpected Spotify API path.')
        refreshed = False
        for attempt in range(4):
            try:
                return http_json('https://api.spotify.com/v1' + path, token=self.tokens['access_token'])
            except HTTPError as error:
                if error.code == 401 and not refreshed:
                    self.refresh()
                    refreshed = True
                    continue
                if error.code == 429 and attempt < 3:
                    try:
                        delay = max(1, int(error.headers.get('Retry-After', '1')))
                    except (ValueError, TypeError):
                        delay = 1
                    if delay > 30:
                        raise ExportError(f'Spotify rate limit: try again in {delay} seconds.') from None
                    time.sleep(delay)
                    continue
                if error.code in (403, 404):
                    raise ExportError('Playlist unavailable to this app. Use a playlist you own or collaborate on, and check your app access and read scopes.') from None
                raise ExportError(f'Spotify request failed (HTTP {error.code}). Try signing in again or retry later.') from None
        raise ExportError('Spotify is still rate limiting requests. Retry later.')

def authorize(client_id, timeout=180):
    verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    outcome = {}
    class CallbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs include temporary authorization codes.
        def do_GET(self):
            if urlsplit(self.path).path != '/callback':
                self.send_error(404)
                return
            try:
                code = callback_code(self.path, state)
            except ExportError as error:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(error).encode())
                # Ignore forged callbacks; a valid denial ends authorization.
                if 'declined' in str(error):
                    outcome['error'] = error
                return
            outcome['code'] = code
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Spotify authorization received. You can close this tab and return to the exporter.')
    try:
        server = CallbackServer(('127.0.0.1', 8888), Handler)
    except OSError:
        raise ExportError('Port 8888 is in use. Close the other exporter or application and retry.') from None
    with server:
        server.timeout = 1
        url = authorization_url(client_id, verifier, state)
        print('Sign in to Spotify in your browser. This grants read-only playlist access.')
        if not webbrowser.open(url):
            print('Open this authorization link locally:', url)
        deadline = time.monotonic() + timeout
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if outcome.get('error'):
        raise outcome['error']
    if not outcome.get('code'):
        raise ExportError('Sign-in timed out. Run the exporter again.')
    try:
        tokens = http_json('https://accounts.spotify.com/api/token', data={
            'grant_type': 'authorization_code', 'code': outcome['code'], 'redirect_uri': REDIRECT_URI,
            'client_id': client_id, 'code_verifier': verifier})
    except HTTPError:
        raise ExportError('Spotify rejected sign-in. Check the Client ID and registered redirect URI.') from None
    if not tokens.get('access_token'):
        raise ExportError('Spotify did not provide an access token.')
    return SpotifyClient(client_id, tokens)

def clean_text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''

def fetch_playlist(client, identifier):
    identifier = playlist_id(identifier)
    path = '/playlists/' + identifier
    metadata = client.get(path)
    source = 'https://open.spotify.com/playlist/' + identifier
    rows, skipped, offset = [], [], 0
    for _ in range(2000):
        page = client.get(path + '/items?' + urlencode({'limit': 50, 'offset': offset}))
        items = page.get('items')
        if not isinstance(items, list):
            raise ExportError('Spotify did not return playlist items. Check playlist ownership or collaboration and app access.')
        for position, entry in enumerate(items, offset + 1):
            item = entry.get('item', entry.get('track')) if isinstance(entry, dict) else None
            if not isinstance(item, dict) or item.get('type') != 'track':
                skipped.append(f'{position}: unavailable item or non-music episode')
                continue
            if entry.get('is_local') or item.get('is_local'):
                skipped.append(f'{position}: local-only Spotify file')
                continue
            title = clean_text(item.get('name'))
            artists = [clean_text(a.get('name')) for a in item.get('artists', []) if isinstance(a, dict)]
            artists = [a for a in artists if a]
            if not title or not artists or len(title) > 200 or len(artists[0]) > 200:
                skipped.append(f'{position}: missing or unsupported title/artist metadata')
                continue
            track_id = item.get('id', '')
            track_url = 'https://open.spotify.com/track/' + track_id if re.fullmatch(r'[A-Za-z0-9]{22}', str(track_id)) else source
            rows.append({'title': title, 'artist': artists[0], 'artists': artists,
                         'spotify_url': track_url, 'spotify_playlist_url': source,
                         'playlist_position': position})
        if not page.get('next'):
            break
        if not items:
            raise ExportError('Spotify pagination stopped unexpectedly. No files were exported.')
        offset += len(items)  # Construct next request ourselves; never follow external URLs.
    else:
        raise ExportError('Playlist exceeded the export safety limit.')
    latest = client.get(path)
    if metadata.get('snapshot_id') != latest.get('snapshot_id'):
        raise ExportError('Playlist changed during export. Run again to preserve its order.')
    return clean_text(metadata.get('name')) or 'Spotify playlist', rows, skipped, source

def export_payloads(identifier, name, rows, skipped, source, output_format='json'):
    if not rows:
        raise ExportError('No music tracks could be exported. No playlist files were created.')
    identifier = playlist_id(identifier)
    def encode(chunk):
        if output_format == 'txt':
            return ''.join(f"{row['artist']} - {row['title']}\n" for row in chunk).encode('utf-8')
        return (json.dumps(chunk, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    chunks, current = [], []
    for row in rows:
        if len(current) >= 500 or len(encode(current + [row])) > MAX_FILE_BYTES:
            if current:
                chunks.append(current)
            current = []
        if len(encode([row])) > MAX_FILE_BYTES:
            raise ExportError('A playlist entry exceeds the file import size limit.')
        current.append(row)
    chunks.append(current)
    prefix = 'spotify-' + identifier
    files = []
    for number, chunk in enumerate(chunks, 1):
        suffix = f'-part-{number:03d}' if len(chunks) > 1 else ''
        files.append((prefix + suffix + '.' + output_format, encode(chunk)))
    report = (f'{name}\nMetadata supplied by Spotify: {source}\n'
                      f'Exported tracks: {len(rows)}\nSkipped entries: {len(skipped)}\n'
                      'Order and duplicates preserved. JSON retains all artist credits and Spotify links.\n'
                      'This is a metadata export, not a Spotify audio export.\n\n' + '\n'.join(skipped) + '\n')
    return files, (prefix + '-info.txt', report.encode('utf-8'))

def write_export(identifier, name, rows, skipped, source, directory, output_format='json'):
    files, info = export_payloads(identifier, name, rows, skipped, source, output_format)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    unique = secrets.token_hex(4)
    paths = []
    for filename, payload in files:
        path = directory / (unique + '-' + filename)
        with path.open('xb') as file:
            file.write(payload)
        paths.append(path)
    report = directory / (unique + '-' + info[0])
    with report.open('xb') as file:
        file.write(info[1])
    return paths, report

def main():
    parser = argparse.ArgumentParser(description='Export your authorized Spotify playlist to a bot-compatible metadata file.')
    parser.add_argument('playlist', help='Spotify playlist URL, URI, or ID')
    parser.add_argument('--format', choices=('json', 'txt'), default='json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'exports')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    try:
        identifier = playlist_id(args.playlist)
        client_id = os.getenv('SPOTIFY_CLIENT_ID', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{32}', client_id):
            raise ExportError('Set SPOTIFY_CLIENT_ID in .env. Register http://127.0.0.1:8888/callback in your Spotify app. No Client Secret is needed.')
        client = authorize(client_id)
        try:
            name, rows, skipped, source = fetch_playlist(client, identifier)
        finally:
            client.tokens.clear()
        paths, report = write_export(identifier, name, rows, skipped, source, args.output_dir, args.format)
        print(f'Exported {len(rows)} tracks from {name}. Skipped {len(skipped)} entries.')
        for path in paths:
            print('Playlist file:', path.resolve())
        print('Source and skipped-entry report:', report.resolve())
    except (ExportError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    except KeyboardInterrupt:
        parser.exit(1, 'Export cancelled.\n')

if __name__ == '__main__':
    main()
