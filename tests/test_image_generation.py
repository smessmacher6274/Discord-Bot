import asyncio
import base64
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from services.image_generation import ImageGenerator, GeneratedImage, ImageGenerationError, decode_image, api_error
import main

JPEG = b'\xff\xd8\xffimage-bytes'

class ImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.env = Path(self.temp.name) / '.env'

    async def test_missing_key_and_invalid_prompt_do_not_request(self):
        generator = ImageGenerator(self.env)
        with patch.object(generator, 'request', AsyncMock()) as request:
            for prompt in ('', 'x' * 4001, 'Valid prompt'):
                with self.assertRaises(ImageGenerationError):
                    await generator.generate(prompt, 1)
        request.assert_not_called()

    async def test_key_can_be_added_without_restart(self):
        generator = ImageGenerator(self.env)
        self.env.write_text('OPENAI_API_KEY=local-test-key\nIMAGE_MODEL=gpt-image-2.5-flare\n')
        with patch.object(generator, 'request', AsyncMock(return_value={'data': [{'b64_json': base64.b64encode(JPEG).decode()}]})):
            result = await generator.generate('A dragon', 1)
        self.assertEqual(result.data, JPEG)
        self.assertEqual(result.filename, 'generated-image.jpg')

    async def test_busy_requests_and_timeouts_do_not_retry(self):
        generator = ImageGenerator(self.env, fallback_key='local-test-key')
        async with generator.lock:
            with self.assertRaisesRegex(ImageGenerationError, 'already'):
                await generator.generate('A dragon', 1)
        with patch.object(generator, 'request', AsyncMock(side_effect=asyncio.TimeoutError)) as request:
            with self.assertRaisesRegex(ImageGenerationError, 'No automatic retry'):
                await generator.generate('A dragon', 1)
        request.assert_awaited_once()
        self.assertFalse(generator.lock.locked())

    def test_invalid_and_oversized_image_responses(self):
        for payload in ({}, {'data': []}, {'data': [{'b64_json': 'invalid!'}]},
                        {'data': [{'b64_json': base64.b64encode(b'not-an-image').decode()}]},
                        {'data': [{'b64_json': base64.b64encode(JPEG * 100).decode()}]}):
            with self.assertRaises(ImageGenerationError):
                decode_image(payload, 100)

    def test_error_messages_do_not_expose_api_response(self):
        for status in (400, 401, 403, 404, 429, 500):
            message = api_error(status, {'error': {'message': 'private-key-and-prompt'}})
            self.assertNotIn('private-key', message)
        self.assertIn('declined', api_error(400, {'error': {'code': 'content_policy_violation'}}))

@unittest.skip('AI command disabled for deployment; tests retained for re-enabling it later.')
class ImageCommandTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, attach=True):
        return SimpleNamespace(user=SimpleNamespace(id=42), guild=SimpleNamespace(filesize_limit=10 * 1024 * 1024),
            app_permissions=SimpleNamespace(attach_files=attach),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))

    async def test_command_returns_image_without_voice(self):
        interaction = self.interaction()
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=True)), \
             patch.object(main.bot.images, 'generate', AsyncMock(return_value=GeneratedImage(JPEG))) as generate:
            await main.show_me.callback(interaction, 'A dragon')
        generate.assert_awaited_once_with('A dragon', 42, max_bytes=8 * 1024 * 1024)
        self.assertEqual(interaction.followup.send.call_args.kwargs['file'].filename, 'generated-image.jpg')

    async def test_unauthorized_user_cannot_spend_api_credit(self):
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=False)), \
             patch('main.config.IMAGE_ALLOWED_USER_IDS', set()), \
             patch.object(main.bot.images, 'generate', AsyncMock()) as generate:
            with self.assertRaisesRegex(ValueError, 'limited'):
                await main.show_me.callback(self.interaction(), 'A dragon')
        generate.assert_not_called()

    async def test_missing_attachment_permission_avoids_generation(self):
        with patch.object(main.bot, 'is_owner', AsyncMock(return_value=True)), \
             patch.object(main.bot.images, 'generate', AsyncMock()) as generate:
            with self.assertRaisesRegex(ValueError, 'Attach Files'):
                await main.show_me.callback(self.interaction(False), 'A dragon')
        generate.assert_not_called()

    async def test_allowed_user_can_generate(self):
        with patch('main.config.IMAGE_ALLOWED_USER_IDS', {42}), \
             patch.object(main.bot, 'is_owner', AsyncMock(return_value=False)), \
             patch.object(main.bot.images, 'generate', AsyncMock(return_value=GeneratedImage(JPEG))) as generate:
            await main.show_me.callback(self.interaction(), 'A dragon')
        generate.assert_awaited_once()

    def test_command_uses_computer_show_me_path(self):
        root = main.bot.tree.get_command('computer')
        self.assertIsNotNone(root)
        self.assertEqual(root.get_command('show').get_command('me').qualified_name, 'computer show me')
        self.assertIsNone(main.bot.tree.get_command('generateimage'))
