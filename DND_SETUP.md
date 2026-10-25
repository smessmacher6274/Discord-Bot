# Homebrew ability lookup

Use `/help` in Discord for the full private guide, including examples for every
active command. Choose a topic from its menu, or use `/help topic:stats` directly.
The help menu lasts ten minutes and needs no Sheet, voice, or API connection.

## Character stats and enemy damage

- `/stats view character:Ryujin` shows Health, Armor, and Stamina as current/baseline.
- `/stats add character:Ryujin stat:Health amount:2` adds to current only.
- `/stats subtract character:Ryujin stat:Health amount:3` subtracts from current only.
- `/stats reset character:Ryujin` restores all saved baselines; optional `stat` resets just one.
- `/stats baseline character:Ryujin stat:Stamina value:8` sets a baseline and resets current to match.
- `/enemy create name:Guard health:30` creates an enemy. Health is optional for damage-only tracking.
- `/enemy damage enemy:Guard character:Ryujin amount:7` logs damage and who dealt it.
- `/enemy view enemy:Guard` shows damage totals and contributions; omit `enemy` to list enemy names.
- `/enemy reset enemy:Guard` clears its damage totals and restores its original health.

All tracker results are visible in the channel. Everyone can update trackers; no
player ownership restrictions are configured. Data is isolated by Discord server.
Names autocomplete; duplicate enemy names are rejected (use Guard 1, Guard 2, etc.).
Damage amounts are the final damage you choose to record; armor does not automatically
reduce damage, and rolling does not automatically modify trackers.

Numeric Health, Armor, and Stamina values from Skills initialize missing baselines
on first use. Missing values remain Not set. Changing the Sheet afterward does not
overwrite saved current values or baselines; use `/stats baseline` to change them.
Current values can exceed baseline or fall below zero. Add/subtract/reset do not
modify Google Sheets or skill roll modifiers.

Tracker data is stored in `data/tracker.sqlite3`, excluded from Git. It survives
restarts on the same host. Back up this file while the bot is stopped and copy it
to the same project-relative path when moving the bot to the Pi; a Git clone alone
does not transfer tracker state. Do not run two hosts against separate copies and
expect them to synchronize.

`/loadout character:<Character ID>` privately lists all relics held by that character.
Character autocomplete displays names and submits the corresponding Character ID;
typing an exact character name also works. Create a Character Relics tab with
`Character ID` and `Relic Name`, one row per character/relic pair. IDs must exist
in Characters. Set `DND_CHARACTER_RELICS_GID` to this tab's GID in `.env` and
restart. Holdings refresh after 60 seconds, independently of ability assignments.
Characters with no holdings show an empty loadout; long lists include a full attachment.

`/relic relic:<name>` offers searchable relic autocomplete and privately replies
with the selected relic's description, preserving its wording and line breaks.
Create a Relics tab with `Relic ID`, `Relic Name`, and `Description` headers and one unique
ID and name per row. Autocomplete shows names and selects by ID; typing an exact
name or ID also works. IDs remain internal and are not shown in the response. Character Relics holdings
continue to use their existing `Relic Name` column.
Set `DND_RELICS_GID` in `.env` to its numeric tab GID and restart
the bot. Descriptions refresh after 60 seconds; long descriptions include a full
text attachment. Relics load independently of character and ability assignments.

`/roll character:Ryujin skill:Willpower` rolls two independent d10s, adds the
selected character's whole-number skill modifier, and posts both dice, the modifier,
and total in the channel. Choose the character first; skill autocomplete lists only
that character's skills. No additional ability bonuses are inferred. Conditional
or nonnumeric modifiers produce an error instead of an assumed result.

`/skills character:Ryujin` shows all recorded skill modifiers in a private response,
with character autocomplete and optional notes. Values are shown as written; no
standard D&D calculations or bonuses inferred from ability descriptions are applied.
Create a Skills tab with `Character ID`, `Skill Name` (or `Skill`), `Modifier`, and optional `Notes`.
Use one row per character/skill pair; zero modifiers must be entered explicitly.
Blank modifiers display as Not set without blocking other skills. Roll autocomplete
offers only skills with whole-number modifiers; type to search beyond the first 25.
Set `DND_SKILLS_GID` in `.env` to that tab's numeric GID, then restart the bot.
Skills reload after the 60-second cache expires. Large lists include a full text
attachment. A missing Skills configuration does not prevent music or abilities.

Use `/abilities character:Ryujin` and choose an ability from the dropdown. Character
autocomplete shows names alphabetically. Anyone in a server where the bot is installed
can open their own private menu; only the requester can operate that menu.
No voice channel or AI API is required. IDs remain internal to the Sheet joins.

Configure the bot's `.env` on each host:

```env
DND_SHEET_ID=1FFhqTFytciy9fPGJHDZMnwLTdgfvEYTPH3M1gI6oOaM
DND_CHARACTERS_GID=0
DND_ABILITIES_GID=592372328
DND_CHARACTER_ABILITIES_GID=1938479340
```

The service reads CSV exports from the configured Sheet and never edits it. The
current Sheet allows this export without credentials. A private Sheet would require
an authenticated Google adapter; this version does not bypass Google access controls.

Required headers:

- Characters: `Character`, `Character ID`.
- Abilities: `Ability ID`, `Ability Name`, `Description`; optional `Type` (such as Action or Subaction), displayed with the ability.
- Character Abilities: `Character ID`, `Ability ID`; optional `Character Notes`.

IDs must be unique, and assignment IDs must exist in their respective tabs. Duplicate
assignments or character names produce explicit errors instead of selecting arbitrary
records. Descriptions retain their original wording and line breaks. Character-specific
notes display separately. Empty character inventories show a clear message.

Data is cached for 60 seconds; each new command reloads expired data. Autocomplete
uses the cached character list. The Refresh button forces a read and updates that
menu, including newly assigned abilities. Menus expire after five minutes; rerun the
command to get a fresh one. Abilities are alphabetical, with 25 dropdown options per
page and Previous/Next buttons for larger lists. Descriptions longer than Discord's
embed limit include a complete text attachment. The bot needs View Channels, Send
Messages, Embed Links, and Attach Files for full functionality.

Keep both IDs and descriptions in Google Sheets. Restart after changing the Sheet
configuration in `.env`. Music/Spotify remain usable if the Sheet is unreachable.

`/damage weapon` offers searchable weapon autocomplete from the Damage ranges tab
(GID `404740668`) and privately displays `Melee`, `Ranged`, and `Damage roll`
exactly as recorded. The tab requires `Weapon Type` plus those three headers, with
one unique weapon type per row. Blank values display as Not set. Data refreshes
after 60 seconds. Override the tab with `DND_DAMAGE_RANGES_GID` if needed.
Restart the bot to register the new command.
