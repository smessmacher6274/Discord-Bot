import json
from dataclasses import dataclass, replace
from music.track import Track

MAX_BYTES = 256 * 1024

@dataclass
class ImportResult:
    tracks: list[Track]
    unavailable: list[str]

def import_playlist(payload: bytes, filename: str, provider, user_id: int, youtube_fallback=False) -> ImportResult:
    if len(payload) > MAX_BYTES:
        raise ValueError('Playlist files must be 256 KB or smaller.')
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Save the playlist as UTF-8 text.') from None
    if filename.lower().endswith('.json'):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError('Invalid playlist JSON.') from None
        if not isinstance(rows, list):
            raise ValueError('JSON must be a list of title/artist objects.')
    elif filename.lower().endswith('.txt'):
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            artist, separator, title = line.strip().partition(' - ')
            if not separator:
                raise ValueError('Each text line must use Artist - Title.')
            rows.append({'artist': artist, 'title': title})
    else:
        raise ValueError('Attach a .txt or .json playlist file.')
    if not 1 <= len(rows) <= 500:
        raise ValueError('Playlists must contain 1–500 entries.')
    available, unavailable = [], []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                                             or len(row[k]) > 200 for k in ('title', 'artist')):
            raise ValueError(f'Entry {index} needs a title and artist of 1–200 characters.')
        title, artist = row['title'].strip(), row['artist'].strip()
        matches = [t for t in provider.tracks.values()
                   if t.title.strip().casefold() == title.casefold()
                   and t.artist.strip().casefold() == artist.casefold()]
        if not matches and filename.lower().endswith('.txt'):
            matches = [t for t in provider.tracks.values()
                       if t.title.strip().casefold() == artist.casefold()
                       and t.artist.strip().casefold() == title.casefold()]
        if len(matches) == 1:
            available.append(replace(matches[0], requested_by=user_id))
        elif not matches and youtube_fallback:
            request = json.dumps({'title': title, 'artist': artist,
                                  'allow_reverse': filename.lower().endswith('.txt')})
            available.append(Track(title, artist, None, request, '', requested_by=user_id,
                                   provider='youtube_search'))
        else:
            reason = 'ambiguous' if matches else 'unavailable'
            unavailable.append(f'{index}. {artist} - {title} ({reason})')
    return ImportResult(available, unavailable)
