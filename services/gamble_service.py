from datetime import datetime, timedelta
from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random

class GambleService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member):
        escaped_name = member.name.replace("_", "\\_") # If player name contains _ then need to add backslash so Discord doesn't make it italic
        return f"{escaped_name}"

    async def roll(self, interaction: discord.Interaction):
        try:
            roll_result = random.randint(1, 100)
            await interaction.response.send_message(f"{self.get_name(interaction.user)} rolled a {roll_result}!")
        except Exception as e:
            logger.error(f"Error in roll method: {e}")
            await interaction.response.send_message("An error occurred while processing your roll.")

__all__ = ['GambleService']