# Discord music bot

Python 3.11+ bot with the seven planned slash commands plus skip, per-server in-memory queues,
automatic advancement, immediate volume control, and queue pagination.

## Windows setup

Create an application at https://discord.com/developers/applications and add a bot.
Copy its token into `.env` (never share it). Invite it using OAuth2 URL Generator:
scopes `bot` and `applications.commands`; permissions View Channels, Send Messages,
Connect, Speak. No privileged intents or Administrator permission are required.

Install FFmpeg and ensure `ffmpeg -version` works, or set FFMPEG_PATH to its executable.
From this directory run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
New-Item -ItemType Directory -Force audio
Copy-Item catalog.example.json catalog.json
```

Edit `.env`, setting your token. Commands register individually in every server the
bot has joined and whenever it joins another server. `DISCORD_GUILD_ID` is retained
as a legacy setting and no longer restricts command registration.

For a harmless locally generated test file:

```powershell
ffmpeg -f lavfi -i "sine=frequency=440:duration=3" audio/test.wav
.\.venv\Scripts\python.exe main.py
```

Join a voice channel and use `/play Test tone`, `/play local:test`, or
`/play playlist:demo`. Stop the process with Ctrl+C; voice connections are closed.

## Approved catalog

### YouTube video links

Use `/play` with a YouTube video URL in `query`, including `https://youtu.be/VIDEO_ID`.
Public non-live videos are resolved by yt-dlp and streamed through FFmpeg.
Pause, resume, skip, queue, and volume controls apply. A video link containing a
playlist parameter plays only that video; playlist-only URLs are unsupported.
Direct title queries still search the local catalog. Playlist-file imports first
match the catalog, then search YouTube for unmatched songs when their turn arrives.

Install requirements including yt-dlp's default extras. Use Node.js 22+ on PATH or set
`YOUTUBE_NODE_PATH` to its executable. This installation uses the existing Node runtime.
Streams are refreshed at playback time. External extraction runs in bounded
subprocesses and does not block Discord commands. Private or restricted videos may
fail; no account cookies are configured. Use recordings you have permission to share.
This is an unofficial integration, subject to YouTube's terms and changes.

If extraction breaks, update with:
`.\.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"`
Reference: https://github.com/yt-dlp/yt-dlp/wiki/EJS

### Playlist-file imports

Use `/play` with the `playlist_file` attachment option instead of `query`. Upload a
UTF-8 `.txt` file containing one `Artist - Title` per line, or a `.json` list of
objects such as `[{"artist": "Local", "title": "Test tone"}]`.
`playlist.example.txt` is ready to test. Limit: 500 entries and 256 KB.
Both `Artist - Title` and `Title - Artist` text lines are accepted. JSON has explicit
title and artist fields. Catalog matches are queued in file order, including duplicates.
Unmatched entries become pending YouTube searches; each is searched as its turn arrives.
The best result must match both artist and title; official results are preferred, while
unrequested cover, karaoke, remix, live, or slowed versions are excluded. Minor typos
may match. Matching is heuristic, so check the posted video link and use `/skip` or a
direct link if needed. No confident match: notify the channel and advance to the next
entry. Ambiguous local catalog entries are reported privately. No Spotify API is used.

Add audio files under `audio/` and metadata to `catalog.json`. Set `authorized: true`
only for recordings you have permission to broadcast to the intended audience.
Owning a recording alone does not necessarily grant broadcast rights. A source_url
can be an approved HTTPS reference; requesting that exact URL plays its local catalog
file. Arbitrary remote URLs and user-supplied filesystem paths are never fetched;
the YouTube adapter accepts validated video URLs and HTTPS Google video streams.
Playlists map names to ordered track IDs and may contain duplicates (maximum 500).
Search matches catalog titles/artists and rejects ambiguous matches. Unknown recordings
produce an unavailable message. Duration is optional, in seconds.

The local catalog is the initial provider: it has no paid API or service dependency.
Public catalog discovery and provider-hosted playlists are deferred. A standalone
Spotify metadata exporter is available; see `SPOTIFY_SETUP.md`. It requires a Spotify
Client ID and browser authorization, preserves your playlist order, and produces
importable JSON/text files. Spotify playlist URLs can now feed the queue automatically;
Spotify supplies metadata while the catalog/YouTube providers supply audio. Spotify Premium
does not supply Discord broadcasting rights; Spotify supplies no audio for this bot.
Provider interfaces in `providers/base.py` support later audited integrations.

## Commands and reliability

`/generateimage prompt` generates an AI image in the text channel, independently of
music. It requires an OpenAI API key and Attach Files permission. API usage is billed
separately; the command is owner-only unless users are explicitly allowed in `.env`.
See `IMAGE_SETUP.md`. One generation at a time, with a 60-second per-user cooldown.

`/spotifyplaylist link` queues and plays a Spotify playlist automatically and returns
a private export file. `/play query` also accepts Spotify playlist URLs. Use
`/spotifyplaylist link autoplay:false` for export only; no voice channel is required.
On first use after restart, complete Spotify sign-in in the browser on the bot PC.
`/spotifydisconnect` forgets the in-memory session. Both are bot-owner-only because
they use one connected personal account. See `SPOTIFY_SETUP.md` for Client ID setup.

`/play query`, `/pause`, `/resume`, `/queue`, `/removeall`, `/removeindex index`,
`/volume level` (0–100; default 50), `/skip`, `/shuffle`. The `/queue` view also has a
Shuffle button that randomizes the live upcoming queue and refreshes its displayed
order. Shuffle requires at least two upcoming songs and being in the bot's voice
channel; it preserves the current song, duplicates, and volume. Skip stops the current playing or paused
song and advances to the next queued song. With an empty queue, the bot stays connected
and idle. Removal indices exclude the current song.
Queue views are snapshots; rerun `/queue` for current indices. Controls require being
in the bot's voice channel. Requests have a per-user cooldown and a 1000-song queue cap.
Queues reset at shutdown. The bot stays connected when idle. Playback failures skip
the affected track and notify the request channel; later tracks attempt reconnection.

Missing commands: check invitation scopes and guild ID. Missing voice: check Connect
and Speak permissions. Missing audio: check FFmpeg and catalog paths, and console logs.
Keep discord.py voice dependencies current for Discord voice protocol compatibility.

## Verification and remaining acceptance work

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Offline tests cover catalog safety, request resolution, playlist ordering, queue indices,
server isolation, concurrent mutations, skip advancement, credits, and YouTube URL
validation, stream refresh, and failure handling. Local playback and file imports have
been verified by the user in Discord. A public YouTube stream was resolved and decoded
through FFmpeg. YouTube audio in Discord, disconnect recovery, large queues, and
multi-server behavior still need live acceptance checks.

Reference policies: https://developer.spotify.com/policy and https://developer.spotify.com/terms
Voice installation: https://discordpy.readthedocs.io/en/stable/intro.html
