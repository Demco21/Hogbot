import discord
from discord.ext import commands
from config import ADMIN_USER_ID

class YahooFFCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="auth")
    async def fantasy_auth(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.yahoo_ff_service.fantasy_auth(ctx)

    @commands.command(name="matchups")
    async def matchups(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.yahoo_ff_service.get_matchups(ctx)

    @commands.command(name="standings")
    async def standings(self, ctx):
        if ctx.author.id != ADMIN_USER_ID:
            return
        await self.bot.yahoo_ff_service.post_standings_embeds(ctx)

async def setup(bot):
    await bot.add_cog(YahooFFCog(bot))