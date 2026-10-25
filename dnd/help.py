"""Player-facing guide to the bot's active commands."""
import discord
from discord import app_commands


PAGES = {
    'start': ('Getting started', '''Use slash commands in a server. Select a character from autocomplete, then fill in the remaining options. Type part of a name to search; Discord shows at most 25 autocomplete choices at once.

**Choose a topic below**
• **Character stats** — current Health, Armor, Stamina; add, subtract, reset, and baselines.
• **Enemies** — create opponents and record damage by character.
• **Skills & rolls** — skill modifiers and 2d10 checks.
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
Help and reference lookups are private. Rolls, character trackers, and enemy trackers post in the channel. Everyone can update trackers; character ownership restrictions are not configured. Each server has separate tracker data.

No voice connection is needed for campaign commands. Music playback and controls require joining the bot's voice channel (or a voice channel before it connects).

`/help` opens this guide. `/help topic:stats` opens a topic directly. If the menu expires after 10 minutes, run `/help` again. AI image generation is currently disabled.'''),
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
Choose the character first, then a skill. Rolls two independent ten-sided dice and adds that character's skill modifier. Results appear in the channel with both dice, the modifier, and total.

**Example**
Dice 4 and 8, Willpower 6 → **4 + 8 + 6 = 18**.

Only whole-number modifiers are rollable: 6, +6, 0, and -2 all work. Blank or conditional text modifiers cannot be rolled. Skill autocomplete offers only rollable entries for the selected character. With more than 25 entries, type part of the skill name to find it.

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
    async def help_command(interaction: discord.Interaction, topic: str = 'start'):
        if topic not in PAGES:
            raise ValueError('Choose a help topic from the list.')
        await interaction.response.send_message(embed=help_embed(topic), view=HelpView(interaction.user.id, topic),
                                                 ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
