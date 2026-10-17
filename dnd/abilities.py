"""Read-only ability catalog from the campaign's three Google Sheets tabs."""
import asyncio
import csv
import io
import re
import time
from dataclasses import dataclass
import aiohttp

class AbilityError(ValueError):
    pass

@dataclass(frozen=True)
class Character:
    id: str
    name: str

@dataclass(frozen=True)
class Ability:
    id: str
    name: str
    description: str
    type: str = ''

@dataclass(frozen=True)
class Assignment:
    ability_id: str
    notes: str = ''

@dataclass
class Catalog:
    characters: dict[str, Character]
    abilities: dict[str, Ability]
    assignments: dict[str, list[Assignment]]

    def character(self, query):
        query = query.strip().casefold()
        matches = [character for character in self.characters.values()
                   if query in (character.id.casefold(), character.name.casefold())]
        if len(matches) != 1:
            raise AbilityError('Character not found. Choose a character from autocomplete.')
        return matches[0]

def table(text, name, required):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff'), newline=''))
    headers = [header.strip().casefold() for header in (reader.fieldnames or [])]
    if len(headers) != len(set(headers)) or any(header not in headers for header in required):
        raise AbilityError(f'{name} tab needs these unique headers: {", ".join(required)}.')
    reader.fieldnames = headers
    result = []
    for row_number, row in enumerate(reader, 2):
        if None in row:
            raise AbilityError(f'{name} row {row_number} has more fields than its headers.')
        if any((value or '').strip() for value in row.values()):
            result.append((row_number, {key: value or '' for key, value in row.items()}))
    return result

def required_text(row, key, location, max_length=100):
    value = row.get(key, '').strip()
    if not value or len(value) > max_length:
        raise AbilityError(f'{location}: {key} must contain 1–{max_length} characters.')
    return value

def parse_catalog(character_csv, ability_csv, assignment_csv):
    characters, abilities, assignments = {}, {}, {}
    names = set()
    for number, row in table(character_csv, 'Characters', ['character', 'character id']):
        location = f'Characters row {number}'
        identifier = required_text(row, 'character id', location)
        name = required_text(row, 'character', location)
        if identifier in characters or name.casefold() in names:
            raise AbilityError(f'{location}: duplicate character ID or name.')
        characters[identifier] = Character(identifier, name)
        names.add(name.casefold())
        assignments[identifier] = []
    for number, row in table(ability_csv, 'Abilities', ['ability id', 'ability name', 'description']):
        location = f'Abilities row {number}'
        identifier = required_text(row, 'ability id', location)
        name = required_text(row, 'ability name', location)
        description = row['description']  # Preserve the original wording and line breaks.
        if not description.strip():
            raise AbilityError(f'{location}: description is blank.')
        if identifier in abilities:
            raise AbilityError(f'{location}: duplicate ability ID {identifier}.')
        abilities[identifier] = Ability(identifier, name, description, row.get('type', '').strip())
    seen = set()
    for number, row in table(assignment_csv, 'Character Abilities', ['character id', 'ability id']):
        character_id = row['character id'].strip()
        ability_id = row['ability id'].strip()
        if character_id not in characters or ability_id not in abilities:
            raise AbilityError(f'Character Abilities row {number}: unknown character ID or ability ID.')
        key = (character_id, ability_id)
        if key in seen:
            raise AbilityError(f'Character Abilities row {number}: duplicate assignment.')
        seen.add(key)
        assignments[character_id].append(Assignment(ability_id, row.get('character notes', '')))
    if not characters:
        raise AbilityError('The Characters tab has no characters.')
    return Catalog(characters, abilities, assignments)

class AbilityService:
    def __init__(self, sheet_id, character_gid='0', ability_gid='592372328', assignment_gid='1938479340', cache_seconds=60):
        self.sheet_id = sheet_id
        self.gids = (character_gid, ability_gid, assignment_gid)
        self.cache_seconds = cache_seconds
        self.cached = None
        self.fetched_at = 0
        self.lock = asyncio.Lock()

    @property
    def source_url(self):
        return f'https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit#gid={self.gids[1]}'

    async def fetch_tabs(self):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.sheet_id or '') or any(not str(gid).isdigit() for gid in self.gids):
            raise AbilityError('Configure DND_SHEET_ID and the three DND tab GIDs in .env.')
        async def fetch(session, gid):
            url = f'https://docs.google.com/spreadsheets/d/{self.sheet_id}/export'
            async with session.get(url, params={'format': 'csv', 'gid': gid}) as response:
                if response.status in (401, 403):
                    raise AbilityError('Google Sheets denied read access. Check the campaign sheet’s sharing settings.')
                if response.status != 200 or 'csv' not in response.headers.get('Content-Type', '').lower():
                    raise AbilityError('Could not read a campaign Sheet tab. Check its ID, tab GID, and read access.')
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise AbilityError('Campaign Sheet tab exceeds the 2 MB read limit.')
                    chunks.append(chunk)
                return b''.join(chunks).decode('utf-8-sig')
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20, connect=10)) as session:
                return await asyncio.gather(*(fetch(session, gid) for gid in self.gids))
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError):
            raise AbilityError('Could not reach the campaign Sheet. Try again shortly.') from None

    async def load(self, force=False):
        async with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.fetched_at < self.cache_seconds:
                return self.cached
            texts = await self.fetch_tabs()
            catalog = parse_catalog(*texts)
            self.cached = catalog  # Publish only after all three tabs pass validation.
            self.fetched_at = time.monotonic()
            return catalog
