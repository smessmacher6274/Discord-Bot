import json
from pathlib import Path
from music.track import Track

class LicensedAudio:
    """Only administrator-approved local files, never arbitrary remote streams."""
    def __init__(self, catalog: Path, root: Path):
        self.root = root.resolve()
        data = json.loads(catalog.read_text(encoding='utf-8')) if catalog.exists() else {}
        self.tracks = {}
        for item in data.get('tracks', []):
            if item.get('authorized') is not True:
                raise ValueError('Every catalog track must explicitly be authorized.')
            path = (self.root / item['file']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('Catalog audio must exist within AUDIO_ROOT.')
            duration = item.get('duration')
            if duration is not None and (not isinstance(duration, int) or duration < 0):
                raise ValueError('Duration must be nonnegative seconds.')
            key = item['id']
            if key in self.tracks:
                raise ValueError('Duplicate track ID.')
            self.tracks[key] = Track(item['title'], item.get('artist', 'Unknown'), duration,
                                     item.get('source_url', f'local:{key}'), str(path),
                                     attribution=item.get('attribution'))
        self.playlists = data.get('playlists', {})
        for ids in self.playlists.values():
            if not ids or len(ids) > 500 or any(i not in self.tracks for i in ids):
                raise ValueError('Playlists require 1–500 valid catalog IDs.')

    def search(self, query):
        q = query.casefold().strip()
        exact = [t for t in self.tracks.values() if q in (t.title.casefold(), f'{t.artist} - {t.title}'.casefold())]
        matches = exact or [t for t in self.tracks.values() if q in f'{t.title} {t.artist}'.casefold()]
        if len(matches) > 1:
            raise ValueError('Several tracks match; use local:<track ID>.')
        return matches

    def resolve(self, url):
        if url.startswith('playlist:'):
            return [self.tracks[i] for i in self.playlists.get(url[9:], [])]
        if url.startswith('local:'):
            t = self.tracks.get(url[6:])
            return [t] if t else []
        return [t for t in self.tracks.values() if t.source_url == url]

    def get_stream(self, track):
        path = Path(track.stream_url).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('Audio file is missing or outside AUDIO_ROOT.')
        return str(path)
