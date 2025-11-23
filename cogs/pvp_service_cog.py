import discord
from discord.ext import commands
from config import MOD_ROLE_ID, PVP_DISABLED_ROLE_ID
from logging_config import logger

class PVPServiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # @commands.command(name="enablepvp")
    # async def enable_pvp(self, ctx):
    #     try:
    #         mod_role = ctx.guild.get_role(MOD_ROLE_ID)
    #         if mod_role in ctx.author.roles:
    #             await self.bot.pvp_service.enable_pvp(ctx)
    #         else:
    #             await ctx.send("Only moderators can use this command.")
    #     except Exception as e:
    #         logger.error(f"Error in enable pvp command: {e}")

    # @commands.command(name="disablepvp")
    # async def disable_pvp(self, ctx):
    #     try:
    #         mod_role = ctx.guild.get_role(MOD_ROLE_ID)
    #         if mod_role in ctx.author.roles:
    #             await self.bot.pvp_service.disable_pvp(ctx)
    #         else:
    #             await ctx.send("Only moderators can use this command.")
    #     except Exception as e:
    #         logger.error(f"Error in disable pvp command: {e}")
    
    # @commands.command(name="move")
    # async def move(self, ctx, member: discord.Member, *, channel_arg: str):
    #     try:
    #         mod_role = ctx.guild.get_role(MOD_ROLE_ID)
    #         pvp_disabled_role = ctx.guild.get_role(PVP_DISABLED_ROLE_ID)
    #         if mod_role not in ctx.author.roles:
    #             return await ctx.send("Only moderators can use this command.")
    #         if pvp_disabled_role in ctx.author.roles:
    #             return await ctx.send("You cannot move members while your PVP is disabled.")
    #         if pvp_disabled_role in member.roles:
    #             return await ctx.send("You cannot move members whose PVP is disabled.")
    #         await self.bot.pvp_service.move(ctx, member, channel_arg)
    #     except Exception as e:
    #         logger.error(f"Error in move member command: {e}")

async def setup(bot):
    await bot.add_cog(PVPServiceCog(bot))