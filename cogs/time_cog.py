from constants import (
    VALID_ARG_TYPES,
    LIFETIME_COMMAND,
    THISWEEK_COMMAND,
    DUMP_COMMAND
)
from config import ADMIN_USER_ID, HOGBOT_SERVER_ID
import discord
from discord.ext import commands
from logging_config import logger
from discord import app_commands


class TimeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.bot.time_service.update_timestamps(member, before, after)

    @commands.command(name=LIFETIME_COMMAND)
    async def time_spent_lifetime_deprecated(self, ctx, arg: str = ''):
        await ctx.send(f"Prefix `!` commands were deprecated in favor of slash commands. Please use `/{LIFETIME_COMMAND}` to access this functionality.")

    @commands.command(name=THISWEEK_COMMAND)
    async def time_spent_this_week_deprecated(self, ctx, arg: str = ''):
        await ctx.send(f"Prefix `!` commands were deprecated in favor of slash commands. Please use `/{THISWEEK_COMMAND}` to access this functionality.")

    @app_commands.command(
        name=LIFETIME_COMMAND,
        description="Show time spent all-time for a member or all members."
    )
    @app_commands.describe(
        arg=f"Optional — Valid types are {VALID_ARG_TYPES} or a valid member username."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def lifetime_spent(self, interaction: discord.Interaction, arg: str = ''):
        if not arg:
            arg = VALID_ARG_TYPES[0]

        if arg not in VALID_ARG_TYPES:
            member = discord.utils.get(interaction.guild.members, name=arg)
            if member is None:
                await interaction.response.send_message(
                    f"Invalid type! Please choose from '{VALID_ARG_TYPES[0]}', "
                    f"'{VALID_ARG_TYPES[1]}', '{VALID_ARG_TYPES[2]}', '{VALID_ARG_TYPES[3]}' "
                    f"or a valid member name."
                )
                return
            else:
                await self.bot.time_service.time_spent_member(
                    interaction,
                    self.bot.state.lifetime_sums,
                    member
                )
        else:
            await self.bot.time_service.time_spent_all_members(
                interaction,
                self.bot.state.lifetime_sums,
                arg
            )

    @app_commands.command(
        name=THISWEEK_COMMAND,
        description="Show time spent this week for a member or all members."
    )
    @app_commands.describe(
        arg=f"Optional — Valid types are {VALID_ARG_TYPES} or a valid member username."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def time_spent_this_week(self, interaction: discord.Interaction, arg: str = ''):
        if not arg:
            arg = VALID_ARG_TYPES[0]

        if arg not in VALID_ARG_TYPES:
            member = discord.utils.get(interaction.guild.members, name=arg)
            if member is None:
                await interaction.response.send_message(
                    f"Invalid type! Please choose from '{VALID_ARG_TYPES[0]}', "
                    f"'{VALID_ARG_TYPES[1]}', '{VALID_ARG_TYPES[2]}', '{VALID_ARG_TYPES[3]}' "
                    f"or a valid member name."
                )
                return
            else:
                await self.bot.time_service.time_spent_member(
                    interaction,
                    self.bot.state.this_week_time_sums,
                    member
                )
        else:
            await self.bot.time_service.time_spent_all_members(
                interaction,
                self.bot.state.this_week_time_sums,
                arg
            )

    @app_commands.command(
        name="eric",
        description="Show how many days Eric has been sober since 12am 12/08/2025."
    )
    @app_commands.guilds(discord.Object(id=HOGBOT_SERVER_ID))
    async def eric(self, interaction: discord.Interaction):
        from datetime import datetime, timezone

        # Define Eric's sobriety start date (12:00 AM, Dec 8, 2025, UTC)
        start_date = datetime(2025, 12, 8, 0, 0, 0, tzinfo=timezone.utc)

        # Current UTC time
        now = datetime.now(timezone.utc)

        # Calculate days difference
        days_sober = (now - start_date).days

        # Send the message
        await interaction.response.send_message(f"Eric has been sober for **{days_sober} days** 🫡")

async def setup(bot):
    await bot.add_cog(TimeCog(bot))