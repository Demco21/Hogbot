import discord
from discord.ext import commands
from config import ADMIN_USER_ID

class EspnCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="nfldump")
    async def espn(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.espn_service.dump_regular_season_games(self.bot.state.current_nfl_season)
        except Exception as e:
            logger.error(f"Error in espn command: {e}")

    @commands.command(name="games")
    async def games(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.nfl_service.post_schedule_current_week()
        except Exception as e:
            logger.error(f"Error in games command: {e}")

    @commands.command(name="gamesupd")
    async def gamesupd(self, ctx):
        try:
            if ctx.author.id != ADMIN_USER_ID:
                return
            await self.bot.nfl_service.update_schedule_current_week()
        except Exception as e:
            logger.error(f"Error in gamesupd command: {e}")

async def setup(bot):
    await bot.add_cog(EspnCog(bot))