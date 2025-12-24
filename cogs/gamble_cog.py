from config import HOGBOT_SERVER_ID, CASINO_CHANNEL_ID
import discord
from discord.ext import commands
from logging_config import logger
from discord import app_commands


class GambleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_in_allowed_channel(self, interaction: discord.Interaction):
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
            await self.bot.gamble_service.roll(interaction, from_value, to_value)
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
            await self.bot.gamble_service.my_wallet(interaction)
        except Exception as e:
            logger.error(f"Error in mywallet command: {e}")

    
    @app_commands.command(
        name="loan",
        description="Loan Hog Coins to another player."
    )
    @app_commands.describe(
        target="The player who will receive the loan.",
        amount="Amount of Hog Coins to loan."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def loan(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        """Slash command entrypoint for /loan."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            await self.bot.gamble_service.loan(interaction, target, amount)
        except Exception as e:
            logger.error(f"Error in loan command: {e}")


    @app_commands.command(
        name="leaderboard",
        description="Show the top Hog Coin holders."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def leaderboard(self, interaction: discord.Interaction):
        """Slash command entrypoint for /leaderboard."""
        try:
            # Restrict to casino channel like /ridethebus and /loan
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            await self.bot.gamble_service.leaderboard(interaction)
        except Exception as e:
            logger.error(f"Error in leaderboard command: {e}")


    @app_commands.command(
        name="ceelo",
        description="Start a Cee-Lo lobby with a set buy-in."
    )
    @app_commands.describe(
        buy_in="Amount of Hog Coins each player must contribute to the pot."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def ceelo(self, interaction: discord.Interaction, buy_in: int):
        """Slash command entrypoint for /ceelo."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            await self.bot.cee_lo_service.ceelo(interaction, buy_in)
        except Exception as e:
            logger.error(f"Error in ceelo command: {e}")


    @app_commands.command(
        name="beg",
        description="Beg for a few Hog Coins when you're completely broke."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def beg(self, interaction: discord.Interaction):
        """Slash command entrypoint for /beg."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            await self.bot.gamble_service.beg(interaction)
        except Exception as e:
            logger.error(f"Error in beg command: {e}")


    @app_commands.command(
        name="stats",
        description="Show your Hog Coin balance trend over the last 100 rounds."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def stats(self, interaction: discord.Interaction, member: discord.Member = None):
        """Show a player's balance progression as a graph."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the casino channel.",
                    ephemeral=True
                )
                return

            target = member or interaction.user
            await self.bot.gamble_service.show_balance_graph(interaction, target)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")

    @app_commands.command(
        name="slots",
        description="Spin the Hog Pen slot machine."
    )
    @app_commands.describe(
        bet="Amount to bet (between 100 and 10000 Hog Coins). Leave blank for 100."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def slots(
        self,
        interaction: discord.Interaction,
        bet: app_commands.Range[int, 100, 10000] = 100,
    ):
        """Slash command entrypoint for /slots with adjustable bet."""
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            # Pass the bet value through to the SlotsService
            await self.bot.slots_service.slots(interaction, bet)
        except Exception as e:
            logger.error(f"Error in slots command: {e}")

    @app_commands.command(
        name="blackjack",
        description="Play a solo hand of American casino blackjack."
    )
    @app_commands.describe(
        bet="Amount to bet (minimum 100 Hog Coins)."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def blackjack(self, interaction: discord.Interaction, bet: int = 100):
        try:
            if not self.is_in_allowed_channel(interaction):
                await interaction.response.send_message(
                    "🚫 This command can only be used in the designated casino channel.",
                    ephemeral=True
                )
                return

            await self.bot.blackjack_service.blackjack(interaction, bet)
        except Exception as e:
            logger.error(f"Error in blackjack command: {e}")

async def setup(bot):
    await bot.add_cog(GambleCog(bot))
