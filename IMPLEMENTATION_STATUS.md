# Implementation status

AI images are disabled for deployment: command registration, image-client startup,
and API configuration are commented out. Service source and its offline tests are
retained for later; command tests are skipped while disabled. No OpenAI credentials
or image-generation API calls are needed by the running bot.

Implemented: seven slash commands, approved local catalog search, exact source URL
resolution, ordered catalog playlists, independent server state, queue locking,
automatic advancement, failure skipping, reconnection attempts, pagination, shutdown,
credentials configuration, setup guide, and offline tests.

External setup completed: bot invited to Le Magic, token and guild ID configured,
FFmpeg installed, and credited Kevin MacLeod recordings added. The user verified
voice playback and playlist-file import. Skip is implemented with offline tests.

YouTube video-link playback is implemented with yt-dlp, its EJS components, and Node.
Twenty-seven offline tests pass. A public YouTube video was resolved and two seconds of its
audio successfully decoded through FFmpeg. Hearing YouTube playback inside Discord
remains a user acceptance check. YouTube playlist URLs are not enabled. Uploaded
text/JSON playlists now match local catalog tracks first, then queue pending YouTube
searches for unmatched entries. Artist/title matching supports reversed text order,
minor typos, and collaborators, and rejects unrequested versions. All three entries
in the user's edited playlist.starter.txt were matched and their streams resolved in
live tests. Direct song queries still search the local catalog. No Spotify API is used.

Provider review: Jamendo exposes per-recording license information, and its API terms
require compliance with each recording's Creative Commons license. API access alone
does not establish all rights for this bot's use. An automated public-provider adapter
is deferred; the initial provider uses files approved by the administrator.
Sources: https://devportal.jamendo.com/api_terms_of_use and
https://developer.jamendo.com/v3.0/tracks

Spotify: a standalone user-authorized metadata exporter now uses PKCE and the current
playlist `/items` endpoint, preserving order and duplicates with importable JSON/text.
Tokens stay in memory. Spotify supplies metadata, not audio. Forty-eight offline
tests pass. `/spotifyplaylist link` now queues the converted playlist automatically
and returns private playlist files in Discord. `/play query` accepts Spotify playlist
URLs too. Set `autoplay:false` for export-only behavior. `/spotifydisconnect` forgets
the in-memory personal session.
Both are restricted to the bot owner. Command exports stay in memory instead of
writing playlist metadata to the PC. Live Spotify authorization/export awaits the user's
Client ID, registered callback URI, and an owned or collaborated playlist. Setup is
documented in SPOTIFY_SETUP.md. User playlist metadata portability is addressed by
developer policy section III.9; other playback integrations have separate terms.
Sources: https://developer.spotify.com/policy and https://developer.spotify.com/terms

The original BotPlan.md remains the requested roadmap; this delivery does not claim
completion of external service setup, public catalog integration, or live acceptance.
