"""Persistent, server-scoped character resources and enemy damage totals."""
import asyncio
import io
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import discord
from discord import app_commands
from dnd.signin import resolve_character

STATS = ('Health', 'Armor', 'Stamina')
LIMIT = 1_000_000_000


class Tracker:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS signins (
                    guild INTEGER, user INTEGER, character TEXT,
                    PRIMARY KEY (guild, user), UNIQUE (guild, character));
                CREATE TABLE IF NOT EXISTS attendance_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL,
                    started INTEGER NOT NULL, actor INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS attendance_entries (
                    session INTEGER, user INTEGER, character TEXT NOT NULL, arrived INTEGER NOT NULL,
                    PRIMARY KEY (session, user));
                CREATE TABLE IF NOT EXISTS attendance_closures (
                    session INTEGER PRIMARY KEY, ended INTEGER NOT NULL, actor INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS initiative_orders (
                    guild INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turn_durations (
                    guild INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS skill_dice (
                    guild INTEGER, character TEXT, dice INTEGER NOT NULL CHECK(dice >= 1),
                    PRIMARY KEY (guild, character));
                CREATE TABLE IF NOT EXISTS party_skill_dice (
                    guild INTEGER PRIMARY KEY, dice INTEGER NOT NULL CHECK(dice >= 1));
                CREATE TABLE IF NOT EXISTS shinobi_points (
                    guild INTEGER, character TEXT, points INTEGER NOT NULL CHECK(points IN (0,1)),
                    PRIMARY KEY (guild, character));
                CREATE TABLE IF NOT EXISTS resources (
                    guild INTEGER, character TEXT, stat TEXT, baseline INTEGER, current INTEGER,
                    PRIMARY KEY (guild, character, stat));
                CREATE TABLE IF NOT EXISTS enemies (
                    guild INTEGER, key TEXT, name TEXT, health INTEGER,
                    PRIMARY KEY (guild, key));
                CREATE TABLE IF NOT EXISTS hits (
                    guild INTEGER, enemy TEXT, character TEXT, actor TEXT, amount INTEGER,
                    created TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save_turn_times(self, guild, rows):
        with self.transaction() as db:
            db.execute('INSERT INTO turn_durations VALUES (?,?) ON CONFLICT(guild) '
                       'DO UPDATE SET body=excluded.body', (guild, json.dumps(rows)))

    def turn_times(self, guild):
        with self.transaction() as db:
            row = db.execute('SELECT body FROM turn_durations WHERE guild=?', (guild,)).fetchone()
            return json.loads(row['body']) if row else []

    def roll_skill(self, guild, character, randbelow):
        with self.transaction() as db:
            row = db.execute('SELECT dice FROM party_skill_dice WHERE guild=?', (guild,)).fetchone()
            count = row['dice'] if row else 2
            rolls = [randbelow(10) + 1 for _ in range(count)]
            event = 'Rule of Cool' if all(die == 10 for die in rolls) else (
                'Rule of Drool' if all(die == 1 for die in rolls) else None)
            next_count = count + 1 if event == 'Rule of Cool' else (
                max(1, count - 1) if event == 'Rule of Drool' else count)
            db.execute('INSERT INTO party_skill_dice VALUES (?,?) ON CONFLICT(guild) '
                       'DO UPDATE SET dice=excluded.dice', (guild, next_count))
            return rolls, next_count, event

    def restore_skill_dice(self, guild):
        with self.transaction() as db:
            db.execute('INSERT INTO party_skill_dice VALUES (?,2) ON CONFLICT(guild) '
                       'DO UPDATE SET dice=2', (guild,))

    def start_session(self, guild, actor, started=None):
        started = int(time.time() if started is None else started)
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO attendance_closures '
                       'SELECT id,?,? FROM attendance_sessions WHERE guild=?', (started, actor, guild))
            result = db.execute('INSERT INTO attendance_sessions(guild,started,actor) VALUES (?,?,?)',
                                (guild, started, actor))
            return result.lastrowid, started

    def end_session(self, guild, actor, ended=None):
        ended = int(time.time() if ended is None else ended)
        with self.transaction() as db:
            session = db.execute('SELECT id FROM attendance_sessions WHERE guild=? '
                                 'ORDER BY id DESC LIMIT 1', (guild,)).fetchone()
            identifier = session['id'] if session else None
            if identifier is not None:
                db.execute('INSERT OR IGNORE INTO attendance_closures VALUES (?,?,?)',
                           (identifier, ended, actor))
                ended = db.execute('SELECT ended FROM attendance_closures WHERE session=?',
                                   (identifier,)).fetchone()['ended']
            count = db.execute('DELETE FROM signins WHERE guild=?', (guild,)).rowcount
            return identifier, ended, count

    def session_ended(self, guild, session):
        with self.transaction() as db:
            row = db.execute('SELECT c.ended FROM attendance_closures c '
                             'JOIN attendance_sessions s ON s.id=c.session WHERE s.guild=? AND s.id=?',
                             (guild, session)).fetchone()
            return row['ended'] if row else None

    def attendance(self, guild, session=None):
        with self.transaction() as db:
            row = db.execute('SELECT id,started FROM attendance_sessions WHERE guild=? '
                             + ('ORDER BY id DESC LIMIT 1' if session is None else 'AND id=?'),
                             (guild,) if session is None else (guild, session)).fetchone()
            if row is None:
                raise ValueError('No session found. The DM must run /starttime first.')
            entries = [tuple(entry) for entry in db.execute(
                'SELECT user,character,arrived FROM attendance_entries WHERE session=? '
                'ORDER BY arrived,user', (row['id'],))]
            return row['id'], row['started'], entries

    def signin(self, guild, user, character, arrived=None):
        arrived = int(time.time() if arrived is None else arrived)
        with self.transaction() as db:
            try:
                db.execute('INSERT INTO signins VALUES (?,?,?) ON CONFLICT(guild,user) '
                           'DO UPDATE SET character=excluded.character', (guild, user, character))
            except sqlite3.IntegrityError:
                raise ValueError('That character is already signed in by another user.') from None
            session = db.execute('SELECT s.id,s.started,c.ended FROM attendance_sessions s '
                                 'LEFT JOIN attendance_closures c ON c.session=s.id WHERE s.guild=? '
                                 'ORDER BY s.id DESC LIMIT 1', (guild,)).fetchone()
            if session is not None and session['ended'] is None and arrived >= session['started']:
                db.execute('INSERT OR IGNORE INTO attendance_entries VALUES (?,?,?,?)',
                           (session['id'], user, character, arrived))
                entry = db.execute('SELECT arrived FROM attendance_entries WHERE session=? AND user=?',
                                   (session['id'], user)).fetchone()
                return session['started'], entry['arrived']

    def signout(self, guild, user):
        with self.transaction() as db:
            return bool(db.execute('DELETE FROM signins WHERE guild=? AND user=?', (guild, user)).rowcount)

    def signed_character(self, guild, user):
        with self.transaction() as db:
            row = db.execute('SELECT character FROM signins WHERE guild=? AND user=?', (guild, user)).fetchone()
            return row['character'] if row else None

    def signed_in(self, guild):
        with self.transaction() as db:
            return [(row['user'], row['character']) for row in db.execute(
                'SELECT user,character FROM signins WHERE guild=? ORDER BY character', (guild,))]

    def award_shinobi(self, guild, character):
        with self.transaction() as db:
            row = db.execute('INSERT INTO shinobi_points VALUES (?,?,1) '
                             'ON CONFLICT(guild,character) DO UPDATE SET points=1 WHERE points=0',
                             (guild, character))
            return bool(row.rowcount)

    def use_shinobi(self, guild, character):
        with self.transaction() as db:
            result = db.execute('UPDATE shinobi_points SET points=0 '
                                'WHERE guild=? AND character=? AND points=1', (guild, character))
            return bool(result.rowcount)

    def party_points(self, guild):
        with self.transaction() as db:
            return [(row['user'], row['character'], row['points']) for row in db.execute(
                'SELECT s.user,s.character,COALESCE(p.points,0) AS points FROM signins s '
                'LEFT JOIN shinobi_points p ON s.guild=p.guild AND s.character=p.character '
                'WHERE s.guild=? ORDER BY s.character', (guild,))]

    def save_turn_order(self, guild, body):
        with self.transaction() as db:
            db.execute('INSERT INTO initiative_orders VALUES (?,?) ON CONFLICT(guild) '
                       'DO UPDATE SET body=excluded.body', (guild, body))

    def turn_order(self, guild):
        with self.transaction() as db:
            row = db.execute('SELECT body FROM initiative_orders WHERE guild=?', (guild,)).fetchone()
            return row['body'] if row else None

    def resources(self, guild, character, baselines, action='view', stat=None, amount=None):
        if action not in ('view', 'add', 'subtract', 'reset', 'baseline'):
            raise ValueError('Unknown stat action.')
        if stat is not None and stat not in STATS:
            raise ValueError('Choose Health, Armor, or Stamina.')
        if action in ('add', 'subtract', 'baseline'):
            if stat is None or type(amount) is not int or not 0 <= amount <= LIMIT:
                raise ValueError('Choose a stat and an amount between 0 and 1,000,000,000.')
        with self.transaction() as db:
            for name, value in baselines.items():
                if name in STATS and type(value) is int and 0 <= value <= LIMIT:
                    db.execute('INSERT OR IGNORE INTO resources VALUES (?,?,?,?,?)',
                               (guild, character, name, value, value))
            if action == 'baseline':
                # An explicit baseline change also resets current to that value.
                db.execute('INSERT INTO resources VALUES (?,?,?,?,?) ON CONFLICT(guild,character,stat) '
                           'DO UPDATE SET baseline=excluded.baseline,current=excluded.current',
                           (guild, character, stat, amount, amount))
            elif action in ('add', 'subtract'):
                row = db.execute('SELECT current FROM resources WHERE guild=? AND character=? AND stat=?',
                                 (guild, character, stat)).fetchone()
                if row is None:
                    raise ValueError(f'{stat} has no baseline. Set it with /stats baseline first.')
                value = row['current'] + (amount if action == 'add' else -amount)
                if abs(value) > LIMIT:
                    raise ValueError('Result exceeds the tracker limit of ±1,000,000,000.')
                db.execute('UPDATE resources SET current=? WHERE guild=? AND character=? AND stat=?',
                           (value, guild, character, stat))
            elif action == 'reset':
                if stat:
                    result = db.execute('UPDATE resources SET current=baseline WHERE guild=? AND character=? AND stat=?',
                                        (guild, character, stat))
                    if not result.rowcount:
                        raise ValueError(f'{stat} has no baseline. Set it with /stats baseline first.')
                else:
                    db.execute('UPDATE resources SET current=baseline WHERE guild=? AND character=?', (guild, character))
            return {row['stat']: (row['current'], row['baseline']) for row in db.execute(
                'SELECT * FROM resources WHERE guild=? AND character=?', (guild, character))}

    def create_enemy(self, guild, name, health=None):
        name = name.strip()
        if not name or len(name) > 80 or '\n' in name or '\r' in name:
            raise ValueError('Enemy name must be 1–80 characters on one line.')
        if health is not None and (type(health) is not int or not 1 <= health <= LIMIT):
            raise ValueError('Enemy health must be between 1 and 1,000,000,000.')
        with self.transaction() as db:
            try:
                db.execute('INSERT INTO enemies VALUES (?,?,?,?)', (guild, name.casefold(), name, health))
            except sqlite3.IntegrityError:
                raise ValueError('That enemy already exists. Use a distinct name, such as Guard 2.') from None
        return name

    def enemy(self, guild, name, amount=None, character='', actor='', reset=False):
        key = name.strip().casefold()
        if amount is not None and (type(amount) is not int or not 1 <= amount <= LIMIT):
            raise ValueError('Damage must be between 1 and 1,000,000,000.')
        with self.transaction() as db:
            row = db.execute('SELECT * FROM enemies WHERE guild=? AND key=?', (guild, key)).fetchone()
            if row is None:
                raise ValueError('Enemy not found. Create it with /enemy create first.')
            if reset:
                db.execute('DELETE FROM hits WHERE guild=? AND enemy=?', (guild, key))
            if amount is not None:
                db.execute('INSERT INTO hits (guild,enemy,character,actor,amount) VALUES (?,?,?,?,?)',
                           (guild, key, character, str(actor), amount))
            contributions = [(hit['character'], hit['damage']) for hit in db.execute(
                'SELECT character,SUM(amount) AS damage FROM hits WHERE guild=? AND enemy=? '
                'GROUP BY character ORDER BY damage DESC,character', (guild, key))]
            total = sum(value for _, value in contributions)
            return row['name'], row['health'], total, contributions

    def enemy_names(self, guild):
        with self.transaction() as db:
            return [row['name'] for row in db.execute('SELECT name FROM enemies WHERE guild=? ORDER BY key', (guild,))]


def sheet_baselines(entries):
    return {stat: int(entry.modifier) for stat in STATS for entry in entries
            if entry.name.casefold() == stat.casefold() and re.fullmatch(r'[+]?[0-9]{1,9}', entry.modifier)}


async def send_tracker(interaction, title, text):
    files = []
    if len(text) > 4096:
        files = [discord.File(io.BytesIO(text.encode('utf-8')), filename='tracker.txt')]
        text = text[:3900] + '\n\nFull tracker attached.'
    try:
        await interaction.followup.send(embed=discord.Embed(title=title, description=text), files=files,
                                        allowed_mentions=discord.AllowedMentions.none())
    finally:
        for file in files:
            file.close()


def register_tracker_commands(bot, tracker, skills):
    stats = app_commands.Group(name='stats', description='Track current Health, Armor, and Stamina', guild_only=True)
    enemies = app_commands.Group(name='enemy', description='Create enemies and record damage dealt', guild_only=True)
    stat_choices = [app_commands.Choice(name=name, value=name) for name in STATS]

    async def character_autocomplete(interaction, current):
        try:
            catalog, _ = await asyncio.wait_for(skills.load(), 2)
        except (ValueError, asyncio.TimeoutError):
            return []
        return [app_commands.Choice(name=c.name, value=c.name)
                for c in sorted(catalog.characters.values(), key=lambda c: c.name.casefold())
                if current.casefold() in c.name.casefold()][:25]

    async def change(interaction, character, action='view', stat=None, amount=None):
        await interaction.response.defer()
        catalog, records = await skills.load()
        selected = catalog.character(await resolve_character(bot, interaction, character))
        values = await asyncio.to_thread(tracker.resources, interaction.guild_id, selected.id,
                                        sheet_baselines(records[selected.id]), action, stat, amount)
        lines = []
        for name in STATS:
            if name in values:
                current, baseline = values[name]
                lines.append(f'**{name}** — Current: **{current}** | Baseline: {baseline}')
            else:
                lines.append(f'**{name}** — Not set; use `/stats baseline`.')
        if action != 'view':
            detail = f' {stat}' if stat else ' all stats'
            if amount is not None:
                detail += f' ({amount})'
            lines.insert(0, f'{action.capitalize()}{detail}\n')
        await send_tracker(interaction, f'{selected.name} — Stats', '\n'.join(lines))

    @stats.command(name='view', description='Show current and baseline character stats')
    async def view(interaction: discord.Interaction, character: str = None):
        await change(interaction, character)

    @stats.command(name='party', description='Show Health and Stamina for all signed-in characters')
    async def party(interaction: discord.Interaction):
        await interaction.response.defer()
        roster = await asyncio.to_thread(tracker.signed_in, interaction.guild_id)
        if not roster:
            await send_tracker(interaction, 'Party — Health & Stamina',
                               'No characters are signed in. Use /signin first.')
            return
        catalog, records = await skills.load()
        lines = []
        for _, identifier in sorted(roster, key=lambda row: (
                catalog.characters[row[1]].name.casefold() if row[1] in catalog.characters else row[1].casefold())):
            selected = catalog.characters.get(identifier)
            label = selected.name if selected else f'{identifier} (removed from Sheet)'
            values = await asyncio.to_thread(tracker.resources, interaction.guild_id, identifier,
                                            sheet_baselines(records.get(identifier, [])))
            parts = []
            for name in ('Health', 'Stamina'):
                if name in values:
                    current, baseline = values[name]
                    parts.append(f'{name}: **{current} / {baseline}**')
                else:
                    parts.append(f'{name}: **Not set**')
            lines.append(f'**{discord.utils.escape_markdown(label)}** — ' + ' | '.join(parts))
        lines.append('\nValues show current / baseline. Set missing values with `/stats baseline`.')
        await send_tracker(interaction, 'Party — Health & Stamina', '\n'.join(lines))

    @stats.command(name='add', description='Add to a character’s current stat')
    @app_commands.choices(stat=stat_choices)
    async def add(interaction: discord.Interaction, stat: str,
                  amount: app_commands.Range[int, 1, LIMIT], character: str = None):
        await change(interaction, character, 'add', stat, amount)

    @stats.command(name='subtract', description='Subtract from a character’s current stat')
    @app_commands.choices(stat=stat_choices)
    async def subtract(interaction: discord.Interaction, stat: str,
                  amount: app_commands.Range[int, 1, LIMIT], character: str = None):
        await change(interaction, character, 'subtract', stat, amount)

    @stats.command(name='reset', description='Reset one stat or all stats to their saved baselines')
    @app_commands.choices(stat=stat_choices)
    async def reset(interaction: discord.Interaction, character: str = None, stat: str = None):
        await change(interaction, character, 'reset', stat)

    @stats.command(name='baseline', description='Set a stat’s baseline and reset its current value to match')
    @app_commands.choices(stat=stat_choices)
    async def baseline(interaction: discord.Interaction, stat: str,
                       value: app_commands.Range[int, 0, LIMIT], character: str = None):
        await change(interaction, character, 'baseline', stat, value)

    for command in (view, add, subtract, reset, baseline):
        command.autocomplete('character')(character_autocomplete)

    async def enemy_autocomplete(interaction, current):
        names = await asyncio.to_thread(tracker.enemy_names, interaction.guild_id)
        return [app_commands.Choice(name=name, value=name) for name in names
                if current.casefold() in name.casefold()][:25]

    async def show_enemy(interaction, name, amount=None, character='', reset=False):
        catalog = None
        if amount is not None:
            catalog, _ = await skills.load()
            character = catalog.character(await resolve_character(bot, interaction, character)).id
        name, health, total, contributions = await asyncio.to_thread(
            tracker.enemy, interaction.guild_id, name, amount, character, interaction.user.id, reset)
        lines = [f'Damage dealt: **{total}**']
        if health is not None:
            lines.insert(0, f'Health: **{health - total} / {health}**')
        if amount is not None:
            lines.append(f'Last hit: **{amount}**')
        if contributions:
            if catalog is None:
                try:
                    catalog, _ = await skills.load()
                except ValueError:
                    pass
            lines.append('\nDamage by character:')
            for identifier, damage in contributions:
                selected = catalog.characters.get(identifier) if catalog else None
                label = selected.name if selected else 'Unavailable character'
                lines.append(f'{label}: **{damage}**')
        await send_tracker(interaction, name, '\n'.join(lines))

    @enemies.command(name='create', description='Create an enemy, optionally with starting health')
    async def create(interaction: discord.Interaction, name: str,
                     health: app_commands.Range[int, 1, LIMIT] = None):
        await interaction.response.defer()
        await asyncio.to_thread(tracker.create_enemy, interaction.guild_id, name, health)
        await show_enemy(interaction, name)

    @enemies.command(name='damage', description='Assign damage dealt by a character to an enemy')
    async def damage(interaction: discord.Interaction, enemy: str,
                     amount: app_commands.Range[int, 1, LIMIT], character: str = None):
        await interaction.response.defer()
        await show_enemy(interaction, enemy, amount, character)

    damage.autocomplete('character')(character_autocomplete)

    @enemies.command(name='view', description='View an enemy’s damage totals or list all enemy names')
    async def enemy_view(interaction: discord.Interaction, enemy: str = None):
        await interaction.response.defer()
        if enemy:
            await show_enemy(interaction, enemy)
        else:
            names = await asyncio.to_thread(tracker.enemy_names, interaction.guild_id)
            await send_tracker(interaction, 'Enemies', '\n'.join(names) or 'No enemies yet. Use `/enemy create`.')

    @enemies.command(name='reset', description='Clear an enemy’s damage totals and restore starting health')
    async def enemy_reset(interaction: discord.Interaction, enemy: str):
        await interaction.response.defer()
        await show_enemy(interaction, enemy, reset=True)

    for command in (damage, enemy_view, enemy_reset):
        command.autocomplete('enemy')(enemy_autocomplete)
    bot.tree.add_command(stats)
    bot.tree.add_command(enemies)
