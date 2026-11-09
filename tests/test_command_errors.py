import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord import app_commands
import main


def http_error(code=10062, status=404):
    response = Mock(status=status, reason='Not Found')
    cls = discord.NotFound if status == 404 else discord.HTTPException
    return cls(response, {'code': code, 'message': 'Unavailable interaction'})


class CommandErrorTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, done=False):
        return SimpleNamespace(command=SimpleNamespace(qualified_name='turntimer roll'),
            created_at=discord.utils.utcnow() - timedelta(seconds=4),
            response=SimpleNamespace(is_done=Mock(return_value=done), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def test_expired_defer_is_not_retried(self):
        interaction = self.interaction()
        error = app_commands.CommandInvokeError(Mock(), http_error())
        with self.assertLogs(level='WARNING') as logs:
            await main.command_error(interaction, error)
        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        self.assertIn('turntimer roll', logs.output[0])
        self.assertIn('age_seconds=', logs.output[0])

    async def test_error_response_expiry_is_caught(self):
        for done in (False, True):
            interaction = self.interaction(done)
            sender = interaction.followup.send if done else interaction.response.send_message
            sender.side_effect = http_error()
            with self.assertLogs(level='WARNING'):
                await main.command_error(interaction, ValueError('Invalid input'))
            sender.assert_awaited_once()

    async def test_duplicate_acknowledgement_is_not_retried(self):
        interaction = self.interaction()
        with self.assertLogs(level='WARNING'):
            await main.command_error(interaction, http_error(40060, 400))
        interaction.response.send_message.assert_not_awaited()

    async def test_valid_errors_still_reach_player_privately(self):
        for done in (False, True):
            interaction = self.interaction(done)
            await main.command_error(interaction, ValueError('Choose a character'))
            sender = interaction.followup.send if done else interaction.response.send_message
            sender.assert_awaited_once_with('Choose a character', ephemeral=True)
