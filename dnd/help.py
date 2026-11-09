"""Player-facing guide to the bot's active commands."""
import discord
from dnd.visibility import Visibility
from discord import app_commands


PAGES = {
    'turntimer': ('Turn timers', '''`/turntimer roll`
Rolls exactly 2d10 plus the higher of Decipher and Reflex for every signed-in character. Both modifiers must be whole numbers. Cool/Drool is neither used nor changed. Totals 17 or lower grant 1 minute, 18–21 grant 2 minutes, 22–25 grant 3 minutes, and every additional 4 adds another minute.

`/turntimer view` shows saved durations without rerolling. Results survive restarts; rolling again replaces the saved party results.

`/turnstart character:Ryujin` starts that signed-in character's saved duration. Join the bot's voice channel first, or it joins yours. Sounds play at the start, 10 seconds remaining, and the end. Text alerts mention the player. Everyone must be in voice to hear sounds. Chimes mix with music; resume paused music before starting a timer. If voice disconnects, text alerts continue.

Only one timer runs per server. Starting another replaces it. `/turnstop` cancels it. Running timers are cancelled on bot restart; use `/turnstart` again. Rerolling durations does not change an already running countdown.'''),
    'start': ('Getting started', '''Use slash commands in a server. Select a character from autocomplete, then fill in the remaining options. Type part of a name to search; Discord shows at most 25 autocomplete choices at once.

**Choose a topic below**
• **Character stats** — current Health, Armor, Stamina; add, subtract, reset, and baselines.
• **Enemies** — create opponents and record damage by character.
• **Skills & rolls** — skill modifiers and Cool/Drool checks.
• **Initiative** — roll for all signed-in characters and create a turn order.
• **Abilities & relics** — descriptions, loadouts, and weapon damage references.
• **Music** — playback, playlists, queues, volume, and shuffle.
• **Spotify** — playlist import, export, and account connection.

**Quick combat example**
1. `/stats view character:Ryujin`
2. `/roll character:Ryujin skill:Willpower`
3. `/enemy create name:Guard health:30`
4. `/enemy damage enemy:Guard character:Ryujin amount:7`
5. `/stats subtract character:Ryujin stat:Health amount:2`

A roll does not automatically deal damage or spend resources. Record the final outcome using the tracker commands.

**Privacy and access**
Help and reference lookups are private by default. Add `visibility:Show` to `/help`, `/skills`, `/abilities`, `/loadout`, `/damage`, `/relic`, `/party`, or `/shinobi` to share the result in the channel; `visibility:Hide` keeps it private. Sign-in and account authorization messages stay private. Rolls, character trackers, and enemy trackers post in the channel. Everyone can update trackers; character ownership restrictions are not configured. Each server has separate tracker data.

No voice connection is needed for campaign commands. Music playback and controls require joining the bot's voice channel (or a voice channel before it connects).

`/help` opens this guide. `/help topic:stats` opens a topic directly. If the menu expires after 10 minutes, run `/help` again. AI image generation is currently disabled.'''),
    'signin': ('Character sign-in', '''`/signin character:Ryujin` saves your character in this server. Omit character from `/roll`, `/skills`, `/abilities`, `/loadout`, `/stats` commands, and `/enemy damage` to use it automatically. Roll skill suggestions also use your saved character. Discord does not visibly prefill the character field.

**End of session**
`/kickout player:@User` lets the DM clear another player's character sign-in so they can sign in again correctly. Requires Manage Server permission. The response is private and attendance history stays saved. This removes their character selection only; the player stays in Discord.

`/signout` removes only you from the signed-in roster and clears your saved character. Your attendance record stays saved. The DM uses `/endsession` (requires Manage Server) to close attendance, sign everyone out in this server, and stop the active turn timer. Attendance history remains available. Use `/starttime` to open the next session.

**Session attendance**
The DM runs `/starttime` at session start (requires Manage Server permission). Everyone then runs `/signin`, even if already signed in. Your first successful sign-in records arrival time and elapsed minutes/seconds after start. Switching characters or signing out does not reset that record. `/attendance` shows the latest session privately; add `visibility:Show` to share or `session:<id>` for history. Each `/starttime` creates a new session and keeps previous records. Times survive restarts. Penalties are decided by the DM; none are applied automatically.

`/signout` clears your character and removes you from the roster.
`/party` lists signed-in characters and Discord users in this server.

One character per user and one user per character in each server. Run `/signin` again to switch; an occupied character cannot be claimed. Sign-ins survive restarts and stay active until you sign out or switch. Explicit character choices override your default for that command without changing sign-in. This is a default selection, not an access restriction on other characters.'''),
    'initiative': ('Initiative & turn order', '''Have each player use `/signin character:Name`, then run `/initiative` once for the group.

The bot rolls two independent d10s for each character signed in to this server, adds that character's Willpower modifier from Skills, and posts a numbered turn order from highest total to lowest. Each entry shows the dice, modifier, and total. Ties are ordered alphabetically by character name.

All signed-in characters participate, even if their Discord users are offline. Other servers are excluded. Missing characters or missing, blank, or conditional Willpower modifiers must be fixed before anyone is rolled; no partial order is posted. Any server member can run the command.

`/turnorder` shows the latest saved initiative order without rerolling or loading the Sheet. The order survives restarts and stays unchanged when players sign in or out. Run `/initiative` again to roll and save a fresh order. This does not advance turns, apply damage, or change character stats.'''),
    'dice': ('Custom dice & shinobi points', '''`/dice dice:3 faces:6 damage_healing:false` rolls 3d6 and shows every die plus the total. Use 1-100 dice with 2-1000 faces. This is separate from the 2d10 `/roll` command and adds no skill modifier.

You must choose `damage_healing:true` or `damage_healing:false` on every roll. For damage or healing use `damage_healing:true`. Sign in first with `/signin`. If ANY individual die equals its number of faces (for example a 6 on d6), your signed-in character earns one shinobi point. Multiple maximum dice in one roll still award only one point. Ordinary rolls and `/roll` do not award points. No enemy damage or character healing is automatically applied.

Each character can hold at most one point per server. Earning another while full displays: Should've used your shinobi point dumbass

`/shinobi` shows each party character, user, and point balance. `/shinobi use:true` spends your signed-in character's point. Points survive restarts, switching characters, and sign-out. They belong to the character. Use `visibility:Show` to share the shinobi display.'''),
    'stats': ('Character stats', '''Track **Health, Armor, and Stamina** independently for each character.

**Baseline** is the saved starting value. **Current** is the amount remaining after changes. You do not switch a Sheet cell or edit its formula when using the bot.

`/stats view character:Ryujin`
Shows current and baseline values for all three stats. On first use, numeric values in the Skills tab initialize missing baselines. Missing stats display **Not set**, rather than assuming zero.

`/stats subtract character:Ryujin stat:Health amount:2`
Subtracts a positive amount from current only. Health 10 becomes 8; baseline stays 10. Use Stamina for resource spending or Armor to track armor loss.

`/stats add character:Ryujin stat:Health amount:1`
Adds a positive amount to current only. Health 8 becomes 9. Use for healing, recovery, or temporary increases.

`/stats reset character:Ryujin stat:Health`
Restores that stat's current value to its saved baseline. **Omit stat** to reset all three stats for that character. This restores values; it does not erase baselines.

`/stats baseline character:Ryujin stat:Stamina value:8`
Sets the saved baseline **and resets current to the same value**. Use for missing baselines or permanent stat changes. Value may be zero. Do not use this for ordinary damage or healing.

**Example**
Baseline 10 → subtract 2 → current 8 → add 1 → current 9 → reset → current 10.

**Important behavior**
• Add/subtract amounts must be positive whole numbers.
• Current may exceed baseline or go below zero; the bot does not clamp it.
• Sheet values/formulas and skill roll modifiers are never edited by these commands.
• Baselines are copied on first use. Later Sheet edits do **not** automatically replace saved baselines; use `/stats baseline` to update them.
• Values survive restarts on the same host. They are stored locally, separately per server. Moving the bot to the Pi requires copying its tracker database as well as the code.'''),
    'enemies': ('Enemies & damage dealt', '''Enemy trackers represent opponents in your game, not actual Discord bot accounts.

`/enemy create name:Guard health:30`
Creates an enemy with starting health 30 and damage dealt 0. **Health is optional**: omit it if you only want to count damage without revealing or tracking maximum health. Give separate opponents distinct names, such as Guard 1 and Guard 2. Duplicate names, ignoring case, are rejected.

`/enemy damage enemy:Guard character:Ryujin amount:7`
Records 7 damage against Guard and credits Ryujin. Repeating this command adds another hit. It shows total damage, remaining health when configured, and contributions by character. Choose character and enemy from autocomplete.

`/enemy view enemy:Guard`
Shows the enemy's current totals. **Omit enemy** to list all created enemy names in this server.

`/enemy reset enemy:Guard`
Clears **all recorded damage and character contributions** for that enemy. Starting health stays the same, so remaining health returns to its original value. This resets the enemy for reuse.

**Example**
Guard starts with 30 health. Ryujin deals 7 and Krusty deals 5. Total damage is 12, remaining health is 18, and the contribution list shows 7 and 5.

**What damage means**
Enter the final damage your group agrees was dealt. Armor, resistances, abilities, and damage rolls are not automatically applied. `/roll` and `/damage` do not change enemy health. Enemy damage does not change the attacking character's stats. Overkill may display negative remaining health.

Amounts must be positive whole numbers. Trackers persist across restarts on this host and are separate per server. Everyone can record or reset them.'''),
    'rolls': ('Skills & rolls', '''`/skills character:Ryujin`
Privately displays **all** that character's recorded skill values and notes from the campaign Skills tab. Notes such as Stat, Attack, Defensive, and Jutsu describe the entry. The bot preserves your homebrew values without applying standard D&D rules.

Blank modifiers display **Not set**. Zero is a valid modifier. Long lists include a full text attachment.

`/roll character:Ryujin skill:Willpower`
Choose the character first, then a skill. Starts at 2d10 and adds that character's skill modifier. Results show every die, the modifier, and total. All dice showing 10 triggers Rule of Cool: add one die to future skill rolls. All dice showing 1 triggers Rule of Drool: remove one die, to a minimum of 1d10. Changes apply after the triggering roll, across all skills for that character. Pools persist per server across restarts. `/restore character:Ryujin` resets the pool to 2d10; omit character to use your signed-in character.

**Example**
Dice 4 and 8, Willpower 6 → **4 + 8 + 6 = 18**.

Only whole-number modifiers are rollable: 6, +6, 0, and -2 all work. Blank or conditional text modifiers cannot be rolled. Skill autocomplete offers only rollable entries for the selected character and shows each modifier (for example Melee +7). With more than 25 entries, type part of the skill name to find it.

No critical-hit, advantage, extra ability bonus, or target difficulty calculation is automatically added. Rolls do not modify current Health, Armor, or Stamina and do not apply damage to enemies.

Skills are read from the Sheet and cached for about 60 seconds. Temporary tracker changes do not change `/roll` modifiers. A Sheet error can prevent autocomplete from loading; check the error returned by `/skills` if suggestions are empty.'''),
    'lookups': ('Abilities, relics & weapon references', '''`/abilities character:Ryujin`
Opens a private ability menu for the selected character. Choose an ability to see its description, Type (when supplied), and character-specific notes. Abilities sort alphabetically. **Previous/Next** move through groups of 25, and **Refresh** reloads the Sheet. Only the person who opened the menu can operate it. The menu expires after five minutes; rerun the command to reopen it.

`/relic relic:Bubble Bag`
Privately shows a relic's name and full description. Search by typing part of its name. IDs are used internally and are not displayed in the result. An exact relic name or ID also works when typed manually. This lookup does not equip or transfer the relic.

`/loadout character:Ryujin`
Privately lists the relics assigned to that character in the Character Relics tab. It reads holdings only; it does not equip items, change ownership, or automatically apply relic effects.

`/damage weapon:<weapon type>`
Privately shows the selected weapon type's **Melee**, **Ranged**, and **Damage roll** values from the Damage ranges tab. This is a reference lookup: it does not roll dice or record a hit. To record actual damage, use `/enemy damage`.

These lookups preserve the campaign Sheet's wording. Long descriptions or lists include full text attachments. Most Sheet data is cached for 60 seconds; abilities also have the Refresh button.

**When something is missing**
Check the character's assignment rows, exact column headers, and the relevant tab's configured GID. Unknown IDs or duplicate records can block a tab from loading. An empty inventory means no records are assigned. Configuring a new tab requires updating the bot's `.env` and restarting it.'''),
    'music': ('Music & queue controls', '''Join a voice channel before playing music. If the bot is connected elsewhere, join its channel to control playback.

`/play query:<song or source URL>`
Resolves a supported catalog request or source URL and adds it to the queue. Playback starts when the player is idle; adding songs does not replace the current track. Spotify playlist links use the separate owner-only Spotify workflow.

`/play playlist_file:<attachment>`
Imports a UTF-8 `.txt` or `.json` playlist. Supply **either query or playlist_file**, not both. Files must be at most 256 KB and contain at most 1,000 songs.
TXT: one `Artist - Title` per line.
JSON: `[{"title":"Song title","artist":"Artist name"}]`
Missing catalog matches can be searched on YouTube as each song comes up. Ambiguous/unavailable entries may be skipped and reported.

`/pause` — pauses the playing song.
`/resume` — continues a paused song.
`/skip` — stops the current song and advances to the next queued song.
`/remove` — stops music, clears the queue, and leaves voice. The bot also leaves automatically after 10 minutes without music, including while paused.

`/queue`
Opens a private snapshot of the current and upcoming songs, 10 per page. Previous/Next navigate the snapshot. Reopen `/queue` for a fresh view. The menu lasts two minutes and only its requester can operate it.

`/shuffle`
Randomizes upcoming songs without interrupting the current song. The **Shuffle** button in `/queue` does the same and refreshes that menu. Join the bot's voice channel to shuffle.

`/removeindex index:3`
Removes upcoming song number 3. Numbering starts at 1 and excludes the currently playing song. Use a fresh `/queue` view for the positions.

`/removeall`
Clears upcoming songs and keeps the current song playing.

`/volume level:50`
Sets playback volume from 0 to 100; 0 is muted. It does not change your Discord speaker settings.

Music queues are held in memory and are lost when the bot restarts. `/play` has a three-second per-user cooldown in each server.'''),
    'spotify': ('Spotify playlists', '''Spotify commands use the connected personal account and are **bot-owner only**.

`/spotifyplaylist link:<Spotify playlist URL>`
Default **autoplay:true** imports playlist metadata, converts it into the supported playlist format, queues matching recordings, and begins playback if idle. Join voice first. YouTube matches are found as each track comes up. The response also includes exported playlist files and skipped-entry counts.

`/spotifyplaylist link:<Spotify playlist URL> autoplay:false`
Exports the playlist without playing it. Download the JSON files and later attach them with `/play playlist_file`. If exports have numbered parts, load them in order. No voice connection is needed to export only.

`/play query:<Spotify playlist URL>`
Shortcut for the owner-only automatic import-and-play flow. It adds to the existing queue.

**First connection**
The bot owner must sign in to Spotify and approve access. Playback continues after authorization. On a headless Pi, use the browser URL printed by the bot and the localhost callback tunnel configured during setup. Spotify supplies playlist metadata; audio playback uses the bot's available playback sources.

`/spotifydisconnect`
Forgets the bot's connected Spotify session. It does not remove previously downloaded files or revoke permission on Spotify itself. To revoke permission, use Spotify's account Apps page.

Spotify authorization is stored in memory and is forgotten on bot restart. `/spotifyplaylist` has a 15-second per-user cooldown. Very large playlists may need export-only mode and separate file imports; the automatic flow has a 1,000-song limit.

If a request fails, check the playlist link, access permissions, sign-in, and voice channel before retrying.'''),
}


def help_embed(topic):
    title, text = PAGES[topic]
    embed = discord.Embed(title=f'Help — {title}', description=text)
    embed.set_footer(text='Use the topic menu below • Only you can see this guide')
    return embed


class HelpTopics(discord.ui.Select):
    def __init__(self, topic):
        super().__init__(placeholder='Choose a help topic', options=[
            discord.SelectOption(label=title, value=key, default=key == topic)
            for key, (title, _) in PAGES.items()])

    async def callback(self, interaction):
        topic = self.values[0]
        for option in self.options:
            option.default = option.value == topic
        await interaction.response.edit_message(embed=help_embed(topic), view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, user_id, topic):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.add_item(HelpTopics(topic))

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message('Run /help to open your own guide.', ephemeral=True)
        return False


def register_help_command(bot):
    @bot.tree.command(name='help', description='Detailed command guide with examples and a topic menu')
    @app_commands.guild_only()
    @app_commands.choices(topic=[app_commands.Choice(name=title, value=key) for key, (title, _) in PAGES.items()])
    async def help_command(interaction: discord.Interaction, topic: str = 'start', visibility: Visibility = Visibility.Hide):
        if topic not in PAGES:
            raise ValueError('Choose a help topic from the list.')
        await interaction.response.send_message(embed=help_embed(topic), view=HelpView(interaction.user.id, topic),
                                                 ephemeral=visibility != Visibility.Show, allowed_mentions=discord.AllowedMentions.none())
