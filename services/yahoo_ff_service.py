from logging_config import logger
from bot_state import BotState
import discord
from discord.ext import commands
from datetime import datetime, timedelta
from requests_oauthlib import OAuth2Session
import xml.etree.ElementTree as ET
import aiohttp
from config import (
    YAHOO_CLIENT_ID, 
    YAHOO_CLIENT_SECRET, 
    YAHOO_LEAGUE_KEY
)

REDIRECT_URI = "https://localhost"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
WEEK = "1"  # You can make this dynamic later

class YahooFFService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def fantasy_auth(self, ctx):
        """Start Yahoo OAuth2 flow."""
        oauth = OAuth2Session(YAHOO_CLIENT_ID, redirect_uri=REDIRECT_URI)
        auth_url, _ = oauth.authorization_url(AUTH_URL)

        await ctx.send(f"Go here to authorize:\n{auth_url}")
        await ctx.send("Paste the full redirect URL you were sent back to.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        reply = await self.bot.wait_for("message", check=check)
        redirect_response = reply.content

        self.state.yahoo_token = oauth.fetch_token(
            TOKEN_URL,
            authorization_response=redirect_response,
            client_secret=YAHOO_CLIENT_SECRET
        )

        logger.info(f"Token received: {self.state.yahoo_token}")

        await ctx.send("✅ Authorized successfully!")

    async def matchups(self, ctx):
        if not self.state.yahoo_token or "access_token" not in self.state.yahoo_token:
            await ctx.send("❌ You need to authorize first with `/fantasy_auth`")
            return

        access_token = self.state.yahoo_token["access_token"]
        url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{YAHOO_LEAGUE_KEY}/scoreboard;week={WEEK}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/xml"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                logger.info(f"Yahoo Fantasy Matchups XML:\n{text}")
                await ctx.send("✅ Matchups XML response logged!")

    async def fantasy_test(self, ctx):
        """Test fantasy API access and see the raw response."""
        if not self.state.yahoo_token:
            await ctx.send("❌ Not authorized. Run !fantasy_auth first.")
            return

        oauth = OAuth2Session(YAHOO_CLIENT_ID, token=self.state.yahoo_token)
        url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games"

        headers = {"Accept": "application/json"}
        response = oauth.get(url, headers=headers)

        # Log raw response regardless of format
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Headers: {response.headers}")
        logger.info(f"Raw Response:\n{response.text}")

        # Handle different cases
        if response.status_code == 200:
            try:
                await ctx.send("✅ Yahoo Fantasy API responded successfully.")
                guid, game_key = self.get_latest_nfl_game(response.text)
                await ctx.send(f"✅ GUID: `{guid}`\n🏈 Game Key (NFL 2025): `{game_key}`")
            except Exception as e:
                await ctx.send(f"⚠️ Couldn't display response text: {e}")
        elif response.status_code == 403:
            await ctx.send("❌ 403 Forbidden – Token works, but you might not have access to this data.")
        else:
            await ctx.send(f"⚠️ Error {response.status_code}: {response.reason}")

    def get_latest_nfl_game(self, xml_text):
        ns = {'fantasy': 'http://fantasysports.yahooapis.com/fantasy/v2/base.rng'}
        root = ET.fromstring(xml_text)

        latest_game_key = None
        latest_season = 0
        guid = root.find('.//fantasy:guid', ns).text

        for game in root.findall('.//fantasy:game', ns):
            season_elem = game.find('fantasy:season', ns)
            code_elem = game.find('fantasy:code', ns)

            if season_elem is None or code_elem is None:
                continue

            season = int(season_elem.text)
            code = code_elem.text

            if code == 'nfl' and season == 2025:
                latest_game_key = game.find('fantasy:game_key', ns).text
                break  # Stop as soon as we find 2025

        return guid, latest_game_key

__all__ = ['YahooFFService']