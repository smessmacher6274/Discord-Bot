import unittest
from unittest.mock import patch
import main

class DisabledImageTests(unittest.IsolatedAsyncioTestCase):
    def test_image_command_is_not_registered(self):
        self.assertIsNone(main.bot.tree.get_command('computer'))
        self.assertIsNone(main.bot.tree.get_command('generateimage'))
        self.assertIsNotNone(main.bot.tree.get_command('play'))
        self.assertIsNotNone(main.bot.tree.get_command('spotifyplaylist'))
        self.assertIsNotNone(main.bot.tree.get_command('shuffle'))

    def test_bot_does_not_initialize_image_client(self):
        with patch('services.image_generation.ImageGenerator') as image_client:
            bot = main.Bot()
        image_client.assert_not_called()
        self.assertFalse(hasattr(bot, 'images'))

    def test_config_does_not_load_image_settings(self):
        for setting in ('OPENAI_API_KEY', 'IMAGE_MODEL', 'IMAGE_ALLOWED_USER_IDS'):
            self.assertFalse(hasattr(main.config, setting))
