import asyncio
import base64
import binascii
import json
from dataclasses import dataclass
from pathlib import Path
import aiohttp
from dotenv import dotenv_values

class ImageGenerationError(ValueError):
    pass

@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    filename: str = 'generated-image.jpg'

def decode_image(payload, max_bytes):
    entries = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise ImageGenerationError('The image service returned no image. Try a different prompt.')
    encoded = entries[0].get('b64_json')
    if not isinstance(encoded, str) or len(encoded) > (max_bytes + 2) // 3 * 4:
        raise ImageGenerationError('The generated image exceeds the Discord upload limit or has invalid data.')
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ImageGenerationError('The image service returned invalid image data.') from None
    if not image or len(image) > max_bytes:
        raise ImageGenerationError('The generated image exceeds the Discord upload limit or has invalid data.')
    if not image.startswith(b'\xff\xd8\xff'):
        raise ImageGenerationError('The image service did not return the requested JPEG format.')
    return GeneratedImage(image)

def api_error(status, payload):
    error = payload.get('error', {}) if isinstance(payload, dict) else {}
    code = str(error.get('code') or '') if isinstance(error, dict) else ''
    if any(part in code for part in ('policy', 'moderation', 'safety')):
        return 'The image provider declined this prompt. Try a different prompt.'
    if status == 401:
        return 'The image API key was rejected. Update OPENAI_API_KEY in .env.'
    if status == 403:
        return 'This API account cannot use the image model. Check model access and any required organization verification.'
    if status == 429:
        return 'The image API is rate-limited or has no available quota. Check API billing and try later.'
    if status == 404:
        return 'The configured image model is unavailable to this API account. Check IMAGE_MODEL.'
    if status == 400:
        return 'The image service rejected the request. Check IMAGE_MODEL or try a different prompt.'
    return 'The image service is temporarily unavailable. Try again later.'

class ImageGenerator:
    def __init__(self, env_path: Path, fallback_key='', model='gpt-image-2.5-flare'):
        self.env_path, self.fallback_key, self.model = env_path, fallback_key, model
        self.lock = asyncio.Lock()

    async def generate(self, prompt, user_id, max_bytes=8 * 1024 * 1024):
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 4000:
            raise ImageGenerationError('Enter an image prompt of 1–4000 characters.')
        settings = dotenv_values(self.env_path)
        key = settings.get('OPENAI_API_KEY') or self.fallback_key
        model = settings.get('IMAGE_MODEL') or self.model
        if not key:
            raise ImageGenerationError('Image generation needs OPENAI_API_KEY in the bot’s .env. API usage is billed separately.')
        if self.lock.locked():
            raise ImageGenerationError('An image is already being generated. Try again when it finishes.')
        async with self.lock:
            try:
                payload = await self.request(key, {'model': model, 'prompt': prompt, 'n': 1,
                    'size': '1024x1024', 'quality': 'medium', 'output_format': 'jpeg',
                    'output_compression': 85, 'user': str(user_id)})
            except (asyncio.TimeoutError, aiohttp.ClientError):
                # Do not automatically retry a potentially billed generation request.
                raise ImageGenerationError('Image generation timed out or lost its connection. No automatic retry was made; check API usage before retrying.') from None
            return decode_image(payload, max_bytes)

    async def request(self, key, body):
        timeout = aiohttp.ClientTimeout(total=300, connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post('https://api.openai.com/v1/images/generations',
                    headers={'Authorization': 'Bearer ' + key}, json=body, allow_redirects=False) as response:
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > 16 * 1024 * 1024:
                        raise ImageGenerationError('The image service returned an oversized response.')
                    chunks.append(chunk)
                try:
                    payload = json.loads(b''.join(chunks))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise ImageGenerationError('The image service returned an invalid response. Try again later.') from None
                if response.status != 200:
                    raise ImageGenerationError(api_error(response.status, payload))
                return payload
