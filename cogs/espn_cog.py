import discord
from discord.ext import commands
from config import ADMIN_USER_ID

class EspnCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="nfldump")
    async def espn(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.espn_service.dump_regular_season_games(self.bot.state.current_nfl_season)

    @commands.command(name="games")
    async def games(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.nfl_service.post_schedule_current_week()

    @commands.command(name="gamesupd")
    async def gamesupd(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.nfl_service.update_schedule_current_week()

async def setup(bot):
    await bot.add_cog(EspnCog(bot))