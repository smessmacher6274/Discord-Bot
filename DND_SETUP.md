# Homebrew ability lookup

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
