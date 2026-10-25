"""Persistent, server-scoped character resources and enemy damage totals."""
import asyncio
import io
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import discord
from discord import app_commands

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
        selected = catalog.character(character)
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
    async def view(interaction: discord.Interaction, character: str):
        await change(interaction, character)

    @stats.command(name='add', description='Add to a character’s current stat')
    @app_commands.choices(stat=stat_choices)
    async def add(interaction: discord.Interaction, character: str, stat: str,
                  amount: app_commands.Range[int, 1, LIMIT]):
        await change(interaction, character, 'add', stat, amount)

    @stats.command(name='subtract', description='Subtract from a character’s current stat')
    @app_commands.choices(stat=stat_choices)
    async def subtract(interaction: discord.Interaction, character: str, stat: str,
                       amount: app_commands.Range[int, 1, LIMIT]):
        await change(interaction, character, 'subtract', stat, amount)

    @stats.command(name='reset', description='Reset one stat or all stats to their saved baselines')
    @app_commands.choices(stat=stat_choices)
    async def reset(interaction: discord.Interaction, character: str, stat: str = None):
        await change(interaction, character, 'reset', stat)

    @stats.command(name='baseline', description='Set a stat’s baseline and reset its current value to match')
    @app_commands.choices(stat=stat_choices)
    async def baseline(interaction: discord.Interaction, character: str, stat: str,
                       value: app_commands.Range[int, 0, LIMIT]):
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
            character = catalog.character(character).id
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
    async def damage(interaction: discord.Interaction, enemy: str, character: str,
                     amount: app_commands.Range[int, 1, LIMIT]):
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
