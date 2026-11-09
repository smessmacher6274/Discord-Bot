# Spotify playlist export

The standalone `spotify_export.py` tool reads a playlist you authorize and saves
its metadata in the same JSON or text format accepted by the bot. It exports no
Spotify audio and does not automatically start Discord playback.

## One-time setup

1. Open https://developer.spotify.com/dashboard and create an app, or use your
   existing app. Select Web API. The app owner needs active Spotify Premium in
   Development Mode. New development apps have a five-user limit.
2. Add this exact redirect URI in the app settings:
   `http://127.0.0.1:8888/callback`
3. Copy the app's Client ID into this project's `.env`:
   `SPOTIFY_CLIENT_ID=your_client_id`
   The Client ID is public. This tool does not need a Client Secret.
4. If signing in as another test user, add that account in the app's user-access
   settings. Export a playlist you own or collaborate on; current development-mode
   access does not expose arbitrary public playlist contents.

## Export

### From Discord

Use `/spotifyplaylist link:https://open.spotify.com/playlist/YOUR_PLAYLIST_ID`.
When authorization is needed, the bot sends a private sign-in link in Discord.
Open it in your browser and approve read-only playlist access within three minutes; the command then returns
JSON playlist files and a source/skipped-entry report privately in Discord.
Join a voice channel first: `/spotifyplaylist link` queues and plays the converted
playlist automatically by default, while still returning the export files privately.
It uses the same ordered catalog/YouTube matching as file imports. You can also pass
the playlist URL directly to `/play query`. No download/reupload is needed.
Use `/spotifyplaylist link:URL autoplay:false` for export only, without joining voice.
The existing upcoming queue is preserved; requested songs append in playlist order.
Autoplay is limited to 1000 upcoming songs, and larger exports can be imported in parts.

The command is restricted to the bot application owner because it uses one personal
Spotify session. A refresh token is saved to `data/spotify-session.json`, excluded
from Git, so restarts reuse the connection and refresh expired access tokens.
`/spotifydisconnect` deletes the saved token. Spotify can still require sign-in
if the refresh token expires or access is revoked. Keep the data folder on a
persistent Docker volume or bind mount, just like the tracker database. Command
exports are sent from memory and create no files on the bot PC. Other server members
cannot use this connected account. The Client ID and callback setup above are required.

### Signing in from Windows while the bot runs on the Pi

For a Docker container using **host networking**, leave this running in Windows
PowerShell before requesting Spotify authorization:

```powershell
ssh -N -L 8888:127.0.0.1:8888 cochiloco@cochilocopi
```

Run `/spotifyplaylist link:URL autoplay:false` in Discord and open the private
Spotify link on that same Windows computer. Log in and approve access. The browser
redirects through the SSH tunnel to the bot's callback on the Pi. Close the tunnel
with Ctrl+C after authorization finishes. Future bot restarts reuse the saved
connection; the tunnel is needed only when browser authorization is required.

Keep `SPOTIFY_CALLBACK_HOST=127.0.0.1` for host networking. For Docker bridge
networking, set `SPOTIFY_CALLBACK_HOST=0.0.0.0` in the container environment and
publish `127.0.0.1:8888:8888` on the host, then use the same SSH tunnel. The
registered Spotify redirect URI stays `http://127.0.0.1:8888/callback` in both cases.

### From a terminal

From the bot folder:

```powershell
.\.venv\Scripts\python.exe spotify_export.py "https://open.spotify.com/playlist/YOUR_PLAYLIST_ID"
```

Sign in and approve read-only playlist access in the browser that opens. You have
three minutes to sign in. The local callback listens only on 127.0.0.1 and closes
after authorization. Tokens stay in memory, are refreshed if needed during export,
and are never saved. Sign-in is required for each new run.

The tool prints the output paths under `exports/`. JSON is recommended because it
preserves exact artist/title fields, all credited artists, original positions, and
links back to Spotify. The first credited artist supplies the importer artist field.
For text output, append `--format txt` to get `Artist - Title` lines.
The export preserves order and duplicates. Local-only files, episodes, and missing
metadata are skipped with a separate report. Large playlists are divided into
ordered files of at most 500 songs and 256 KB; load the numbered parts in order.
If the playlist changes during export, rerun instead of using inconsistent results.

You can select the saved metadata file using the bot's existing `playlist_file`
attachment option. The standalone exporter does not issue playback commands;
the Discord commands can also consume the converted data and queue it automatically.

## Privacy and troubleshooting

The tool reads only the playlist you request. Export files contain your playlist
metadata; share them only with your intended audience. `.env` and `exports/` are
ignored by Git. Delete the exported files to remove local copies, and revoke the
app at https://www.spotify.com/account/apps/ to disconnect Spotify access.

Missing access: check Premium, user access, playlist ownership/collaboration, and
read scopes. Redirect mismatch: use the exact URI above, not `localhost`.
Port 8888 in use: close another exporter or application using that port.
Rate limits: short Retry-After delays are retried; long delays are reported.

Official references:
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- https://developer.spotify.com/policy (user playlist metadata portability, section III.9)
