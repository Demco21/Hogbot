from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random

class RollService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member: discord.abc.User) -> str:
        # Escape underscores so Discord doesn't do italics
        escaped_name = member.name.replace("_", "\\_")
        return escaped_name

    async def roll(self, interaction: discord.Interaction, from_value: int = 1, to_value: int = 100):
        """Handle a /roll-style command and send a polished result embed."""
        roller_display = interaction.user.mention

        try:
            if from_value > to_value:
                error_msg = "Invalid roll range!"
                if interaction.response.is_done():
                    await interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(error_msg, ephemeral=True)
                return

            roll_result = random.randint(from_value, to_value)

            # Determine correct article ("a" or "an")
            first_digit = str(roll_result)[0]
            article = "an" if first_digit in {"8"} else "a"

            embed = discord.Embed(
                title=f"🎲 Roll From {from_value} to {to_value}",
                description=f"{roller_display} rolled {article} **{roll_result}**!",
                color=discord.Color.blurple(),
            )

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)

            logger.info(f"User {interaction.user} rolled {roll_result}")

        except Exception as e:
            logger.error("Error in roll method", exc_info=True)

            error_msg = "An error occurred while processing your roll. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

__all__ = ['RollService']
