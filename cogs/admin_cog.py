import discord
from discord.ext import commands
from config import ADMIN_USER_ID
from logging_config import logger

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="nfldump")
    async def espn(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.espn_service.dump_regular_season_games(self.bot.state.current_nfl_season)
        except Exception as e:
            logger.error(f"Error in espn command: {e}")

    @commands.command(name="games")
    async def games(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.nfl_service.post_schedule_current_week()
        except Exception as e:
            logger.error(f"Error in games command: {e}")

    @commands.command(name="gamesupd")
    async def gamesupd(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.nfl_service.update_schedule_current_week()
        except Exception as e:
            logger.error(f"Error in gamesupd command: {e}")

    @commands.command(name="dump")
    async def dump_data_command(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.time_service.dump_data(ctx)
        except Exception as e:
            logger.error(f"Error in dump command: {e}")

    @commands.command(name="auth")
    async def fantasy_auth(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.yahoo_ff_service.fantasy_auth(ctx)
        except Exception as e:
            logger.error(f"Error in auth command: {e}")

    @commands.command(name="matchups")
    async def matchups(self, ctx, week=None):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
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
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.yahoo_ff_service.update_fantasy_matchups()
        except Exception as e:
            logger.error(f"Error in matchupsupd command: {e}")

    @commands.command(name="standings")
    async def standings(self, ctx, week=None):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
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
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.yahoo_ff_service.update_fantasy_standings()
        except Exception as e:
            logger.error(f"Error in standingsupd command: {e}")

    @commands.command(name="decidechancellor")
    async def decide_chancellor(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                ctx.send("You do not have permission to use this command.")
                return
            await self.bot.chancellor_service.decide_chancellor()
        except Exception as e:
            logger.error(f"Error in decide_chancellor command: {e}")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))