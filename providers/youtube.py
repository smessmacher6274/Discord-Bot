import json
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from dataclasses import replace
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlsplit
from music.track import Track

YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
REQUEST_SLOTS = threading.BoundedSemaphore(2)

def words(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    text = text.replace('going to', 'gonna')
    return re.findall(r'[a-z0-9]+', text)

def phrase_score(phrase, candidate):
    wanted, actual = words(phrase), words(candidate)
    if not wanted or not actual:
        return 0
    compact = ''.join(wanted)
    best = 0
    for width in range(max(1, len(wanted) - 2), len(wanted) + 3):
        for offset in range(max(0, len(actual) - width + 1)):
            fragment = ''.join(actual[offset:offset + width])
            best = max(best, SequenceMatcher(None, compact, fragment).ratio())
    return best

def choose_match(entries, title, artist, allow_reverse=False):
    ranked = []
    requested = set(words(title + ' ' + artist))
    for entry in entries:
        if not isinstance(entry, dict) or not VIDEO_ID.fullmatch(str(entry.get('id', ''))):
            continue
        if entry.get('is_live') or entry.get('live_status') in {'is_live', 'is_upcoming', 'post_live'}:
            continue
        candidate_title = str(entry.get('title') or '')
        extra_versions = {'cover', 'karaoke', 'remix', 'nightcore', 'slowed', 'instrumental', 'live'}
        if (set(words(candidate_title)) & extra_versions) - requested:
            continue
        identity = candidate_title + ' ' + str(entry.get('uploader') or entry.get('channel') or '')
        orientations = [(title, artist)] + ([(artist, title)] if allow_reverse else [])
        for song, performer in orientations:
            clean_title = re.sub(r'\([^)]*\)|\[[^]]*\]', '', candidate_title).strip()
            if ' - ' in clean_title:
                credited_artist, credited_song = clean_title.split(' - ', 1)
                credited_song = re.split(r'\s+(?:ft\.?|feat\.?|featuring)\s+', credited_song, maxsplit=1, flags=re.IGNORECASE)[0]
                title_score = SequenceMatcher(None, ''.join(words(song)), ''.join(words(credited_song))).ratio()
                artist_score = phrase_score(performer, credited_artist)
            else:
                title_score = phrase_score(song, candidate_title)
                artist_score = phrase_score(performer, identity)
            if title_score < 0.82 or artist_score < 0.72:
                continue
            score = title_score * 0.65 + artist_score * 0.35
            if 'official' in words(candidate_title):
                score += 0.03
            ranked.append((score, entry, song, performer))
    if not ranked:
        raise ValueError(f'No confident YouTube match for {artist} - {title}. Try corrected spelling or a direct video link.')
    return max(ranked, key=lambda item: item[0])[1:]

def normalize_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in YOUTUBE_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError
        if parsed.hostname in {'youtu.be', 'www.youtu.be'}:
            video_id = parsed.path.lstrip('/')
        elif parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        elif parsed.path.startswith(('/shorts/', '/live/', '/embed/')):
            video_id = parsed.path.split('/')[2]
        else:
            raise ValueError
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError
    except (ValueError, IndexError):
        raise ValueError('Use an HTTPS YouTube video link. YouTube playlist-only links are not supported.') from None
    return 'https://www.youtube.com/watch?v=' + video_id

def validate_stream(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.googlevideo.com')
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise ValueError('YouTube did not return a supported HTTPS audio stream.') from None
    return url

class YouTube:
    def __init__(self, node_path=None):
        self.node_path = node_path or shutil.which('node')

    def extract(self, url):
        url = normalize_url(url)
        args = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--dump-single-json',
                '--no-playlist', '--no-warnings', '--quiet', '--no-cache-dir',
                '--socket-timeout', '15', '--retries', '1', '--extractor-retries', '1',
                '--format', 'bestaudio[protocol=https]', '--skip-download']
        if self.node_path:
            args.extend(['--js-runtimes', 'node:' + self.node_path])
        args.extend(['--', url])
        if not REQUEST_SLOTS.acquire(timeout=1):
            raise ValueError('YouTube is busy resolving other requests. Try again shortly.')
        try:
            try:
                result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                        timeout=75, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError('YouTube took too long to respond. Try again later.') from None
            if result.returncode:
                # Do not surface extractor diagnostics containing signed stream URLs.
                raise ValueError('YouTube could not provide audio. The video may be restricted, unavailable, or blocked. Try another public video or update yt-dlp.')
            try:
                info = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise ValueError('YouTube returned invalid track information.') from None
            if not isinstance(info, dict) or info.get('_type', 'video') != 'video':
                raise ValueError('Only individual YouTube videos are supported.')
            if info.get('is_live') or info.get('live_status') in {'is_live', 'is_upcoming', 'post_live'}:
                raise ValueError('Live and upcoming YouTube streams are not supported.')
            validate_stream(info.get('url', ''))
            return info
        finally:
            REQUEST_SLOTS.release()

    def resolve(self, url):
        canonical = normalize_url(url)
        info = self.extract(canonical)
        duration = info.get('duration')
        return [Track(str(info.get('track') or info.get('title') or 'YouTube video')[:200],
                      str(info.get('artist') or info.get('uploader') or 'YouTube')[:200],
                      round(duration) if isinstance(duration, (int, float)) and duration >= 0 else None,
                      canonical, '', provider='youtube')]

    def get_stream(self, track):
        # Resolve again at playback time: queued streams can expire.
        return validate_stream(self.extract(track.source_url)['url'])

    def search_track(self, track):
        request = json.loads(track.source_url)
        title, artist = request['title'], request['artist']
        query = f'{artist} {title} official audio'
        args = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--dump-single-json',
                '--flat-playlist', '--no-warnings', '--quiet', '--no-cache-dir',
                '--socket-timeout', '15', '--retries', '1', '--extractor-retries', '1',
                '--skip-download', '--', 'ytsearch5:' + query]
        if not REQUEST_SLOTS.acquire(timeout=1):
            raise ValueError('YouTube search is busy. Try again shortly.')
        try:
            try:
                result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                        timeout=75, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError('YouTube search timed out.') from None
            if result.returncode:
                raise ValueError('YouTube search is unavailable. Try again later.')
            try:
                info = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise ValueError('YouTube search returned invalid results.') from None
            entry, song, performer = choose_match(info.get('entries', []), title, artist,
                                                  request.get('allow_reverse', False))
            duration = entry.get('duration')
            return replace(track, title=song, artist=performer,
                           duration=round(duration) if isinstance(duration, (int, float)) and duration >= 0 else None,
                           source_url='https://www.youtube.com/watch?v=' + entry['id'], provider='youtube')
        finally:
            REQUEST_SLOTS.release()
