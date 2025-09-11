import discord
from discord.ext import commands
from config import ADMIN_USER_ID

class YahooFFCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="auth")
    async def fantasy_auth(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.yahoo_ff_service.fantasy_auth(ctx)
        except Exception as e:
            logger.error(f"Error in auth command: {e}")

    @commands.command(name="matchups")
    async def matchups(self, ctx, week=None):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            if week:
                week = int(week)
            await self.bot.yahoo_ff_service.post_fantasy_matchups(None, week)
        except Exception as e:
            logger.error(f"Error in matchups command: {e}")

    @commands.command(name="matchupsupd")
    async def matchupsupd(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.yahoo_ff_service.update_fantasy_matchups()
        except Exception as e:
            logger.error(f"Error in matchupsupd command: {e}")

    @commands.command(name="standings")
    async def standings(self, ctx, week=None):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            if week:
                week = int(week)
            await self.bot.yahoo_ff_service.post_fantasy_standings(None, week)
        except Exception as e:
            logger.error(f"Error in standings command: {e}")

    @commands.command(name="standingsupd")
    async def standingsupd(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.yahoo_ff_service.update_fantasy_standings()
        except Exception as e:
            logger.error(f"Error in standingsupd command: {e}")

async def setup(bot):
    await bot.add_cog(YahooFFCog(bot))