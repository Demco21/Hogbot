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

    @commands.command(name="auth")
    async def fantasy_auth(self, ctx):
        await self.bot.yahoo_ff_service.fantasy_auth(ctx)

    @commands.command(name="matchups")
    async def matchups(self, ctx):
        await self.bot.yahoo_ff_service.get_matchups(ctx, 1)

async def setup(bot):
    await bot.add_cog(YahooFFCog(bot))