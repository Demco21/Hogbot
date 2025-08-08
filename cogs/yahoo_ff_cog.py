import discord
from discord.ext import commands
from datetime import datetime, timedelta
from requests_oauthlib import OAuth2Session
import xml.etree.ElementTree as ET
import aiohttp
from logging_config import logger
from config import (
    YAHOO_CLIENT_ID, 
    YAHOO_CLIENT_SECRET, 
    YAHOO_LEAGUE_KEY
)

class YahooFFCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="test")
    async def matchup(self, ctx):
        team1_logo = "https://yahoofantasysports-res.cloudinary.com/image/upload/t_s192sq/fantasy-logos/e840c4a465ea5e6ab89728d1390972dc7685ceb5b3e1252be5d2f8cdb612ce46.jpg"
        team2_logo = "https://yahoofantasysports-res.cloudinary.com/image/upload/t_s192sq/fantasy-logos/e840c4a465ea5e6ab89728d1390972dc7685ceb5b3e1252be5d2f8cdb612ce46.jpg"
        
        embed = discord.Embed(
            title="🏈 Fantasy Matchup",
            description=(
                f"**Deece's Pieces** vs **Some Other Team**\n"
                f"🏈 Record: **3-1**    🏈 Record: **2-2**"
            ),
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=team1_logo)

        await ctx.send(embed=embed)

    @commands.command(name="auth")
    async def fantasy_auth(self, ctx):
        await self.bot.yahoo_ff_service.fantasy_auth(ctx)

    @commands.command(name="matchups")
    async def matchups(self, ctx):
        await self.bot.yahoo_ff_service.matchups(ctx)

    @commands.command(name="fantasy_test")
    async def fantasy_test(self, ctx):
        await self.bot.yahoo_ff_service.fantasy_test(ctx)

async def setup(bot):
    await bot.add_cog(YahooFFCog(bot))