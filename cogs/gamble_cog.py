from config import HOGBOT_SERVER_ID
import discord
from discord.ext import commands
from logging_config import logger
from discord import app_commands


class GambleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="roll",
        description="Rolls a die from 1 - 100 by default."
    )
    @app_commands.describe(
        from_value="The lowest number you can roll (default 1).",
        to_value="The highest number you can roll (default 100)."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def roll(self, interaction: discord.Interaction, from_value: int = 1, to_value: int = 100):
        try:
            await self.bot.gamble_service.roll(interaction, from_value, to_value)
        except Exception as e:
            logger.error(f"Error in roll command: {e}")

async def setup(bot):
    await bot.add_cog(GambleCog(bot))