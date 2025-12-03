from config import HOGBOT_SERVER_ID, CASINO_CHANNEL_ID
import discord
from discord.ext import commands
from logging_config import logger
from discord import app_commands


class GambleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_in_allowed_channel(self, interaction: discord.Interaction) -> bool:
        """Utility method to check if command is used in the allowed channel."""
        return interaction.channel and interaction.channel.id == CASINO_CHANNEL_ID

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
            await self.bot.roll_service.roll(interaction, from_value, to_value)
        except Exception as e:
            logger.error(f"Error in roll command: {e}")

    @app_commands.command(
        name="ridethebus",
        description="Play a high-risk, high-reward casino card game."
    )
    @app_commands.describe(
        bet="Amount of chips you're wagering on this run."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def ride_the_bus(self, interaction: discord.Interaction, bet: int):
        """Slash command entrypoint for /ridethebus."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    f"🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return
            await self.bot.ride_the_bus_service.ride_the_bus(interaction, bet)
        except Exception as e:
            logger.error(f"Error in ridethebus command: {e}")

    @app_commands.command(
        name="mywallet",
        description="Show your current Hog Coin balance."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def my_wallet(self, interaction: discord.Interaction):
        try:
            await self.bot.ride_the_bus_service.my_wallet(interaction)
        except Exception as e:
            logger.error(f"Error in ridethebus command: {e}")

async def setup(bot):
    await bot.add_cog(GambleCog(bot))
