import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID') or 0)
FFMPEG = os.getenv('FFMPEG_PATH', 'ffmpeg')
CATALOG = ROOT / os.getenv('CATALOG_PATH', 'catalog.json')
AUDIO_ROOT = (ROOT / os.getenv('AUDIO_ROOT', 'audio')).resolve()
YOUTUBE_NODE_PATH = os.getenv('YOUTUBE_NODE_PATH') or None
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '').strip()
DND_SHEET_ID = os.getenv('DND_SHEET_ID', '')
DND_CHARACTERS_GID = os.getenv('DND_CHARACTERS_GID', '0')
DND_ABILITIES_GID = os.getenv('DND_ABILITIES_GID', '592372328')
DND_CHARACTER_ABILITIES_GID = os.getenv('DND_CHARACTER_ABILITIES_GID', '1938479340')
DND_SKILLS_GID = os.getenv('DND_SKILLS_GID', '')
DND_DAMAGE_RANGES_GID = os.getenv('DND_DAMAGE_RANGES_GID', '404740668')
DND_RELICS_GID = os.getenv('DND_RELICS_GID', '')
DND_CHARACTER_RELICS_GID = os.getenv('DND_CHARACTER_RELICS_GID', '')
# OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
# IMAGE_MODEL = os.getenv('IMAGE_MODEL', 'gpt-image-2.5-flare')
# IMAGE_ALLOWED_USER_IDS = {int(value.strip()) for value in os.getenv('IMAGE_ALLOWED_USER_IDS', '').split(',') if value.strip()}
