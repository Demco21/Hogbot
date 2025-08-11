from constants import (
    VALID_ARG_TYPES,
    LIFETIME_COMMAND,
    THISWEEK_COMMAND,
    DUMP_COMMAND
)
from config import ADMIN_USER_ID
import discord
from discord.ext import commands
from logging_config import logger

class TimeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.bot.time_service.update_timestamps(member, before, after)

    @commands.command(name=LIFETIME_COMMAND)
    async def lifetime_spent(self, ctx, arg: str = ''):
        if not arg:
            arg = VALID_ARG_TYPES[0]

        if arg not in VALID_ARG_TYPES:
            member = discord.utils.get(ctx.guild.members, name=arg)
            if member is None:
                await ctx.send(f"Invalid type! Please choose from '{VALID_ARG_TYPES[0]}', '{VALID_ARG_TYPES[1]}', '{VALID_ARG_TYPES[2]}', '{VALID_ARG_TYPES[3]}' or a valid member name.")
                return
            else:
                await self.bot.time_service.time_spent_member(ctx, self.bot.state.lifetime_sums, member)
        else:
            await self.bot.time_service.time_spent_all_members(ctx, self.bot.state.lifetime_sums, arg)

    @commands.command(name=THISWEEK_COMMAND)
    async def time_spent_this_week(self, ctx, arg: str = ''):
        if not arg:
            arg = VALID_ARG_TYPES[0]

        if arg not in VALID_ARG_TYPES:
            member = discord.utils.get(ctx.guild.members, name=arg)
            if member is None:
                await ctx.send(f"Invalid type! Please choose from '{VALID_ARG_TYPES[0]}', '{VALID_ARG_TYPES[1]}', '{VALID_ARG_TYPES[2]}', '{VALID_ARG_TYPES[3]}' or a valid member name.")
                return
            else:
                await self.bot.time_service.time_spent_member(ctx, self.bot.state.this_week_time_sums, member)
        else:
            await self.bot.time_service.time_spent_all_members(ctx, self.bot.state.this_week_time_sums, arg)

    @commands.command(name=DUMP_COMMAND)
    async def dump_data_command(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.time_service.dump_data(ctx)

async def setup(bot):
    await bot.add_cog(TimeCog(bot))