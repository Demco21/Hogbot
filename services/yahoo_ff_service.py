from logging_config import logger
from bot_state import BotState
import discord
from discord.ext import commands
from datetime import datetime, timedelta
from requests_oauthlib import OAuth2Session
import xml.etree.ElementTree as ET
import aiohttp
import time
import json
import os
from config import (
    YAHOO_CLIENT_ID, 
    YAHOO_CLIENT_SECRET, 
    YAHOO_LEAGUE_KEY
)

REDIRECT_URI = "https://localhost"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
TOKEN_FILE = "data/yahoo_token.json"

class YahooFFService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

        # Load saved token if exists
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                self.state.yahoo_token = json.load(f)

    async def fantasy_auth(self, ctx):
        """Manual Yahoo OAuth2 flow (one-time setup)."""
        oauth = OAuth2Session(YAHOO_CLIENT_ID, redirect_uri=REDIRECT_URI)
        auth_url, _ = oauth.authorization_url(AUTH_URL)

        await ctx.send(f"Go here to authorize:\n{auth_url}")
        await ctx.send("Paste the full redirect URL you were sent back to.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        reply = await self.bot.wait_for("message", check=check)
        redirect_response = reply.content

        token = oauth.fetch_token(
            TOKEN_URL,
            authorization_response=redirect_response,
            client_secret=YAHOO_CLIENT_SECRET
        )

        # Add expiry timestamp for refresh logic
        token["expires_at"] = time.time() + int(token.get("expires_in", 0))

        # Save token to file
        with open(TOKEN_FILE, "w") as f:
            json.dump(token, f)

        self.state.yahoo_token = token

        logger.info(f"Yahoo OAuth token saved to {TOKEN_FILE}")
        await ctx.send("✅ Authorized successfully! Token saved for future use.")
    
    async def ensure_token(self):
        """Ensure we have a valid access token by refreshing if needed."""
        if not self.state.yahoo_token:
            raise RuntimeError("No token available. You must authorize once manually first.")

        # If token expired, refresh
        if self.state.yahoo_token.get("expires_at", 0) <= time.time():
            refresh_token = self.state.yahoo_token.get("refresh_token")
            async with aiohttp.ClientSession() as session:
                data = {
                    "client_id": YAHOO_CLIENT_ID,
                    "client_secret": YAHOO_CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
                async with session.post(TOKEN_URL, data=data) as resp:
                    new_token = await resp.json()
                    new_token["refresh_token"] = refresh_token  # Yahoo often doesn't return it again
                    new_token["expires_at"] = time.time() + int(new_token["expires_in"])
                    self.state.yahoo_token = new_token
                    with open(TOKEN_FILE, "w") as f:
                        json.dump(new_token, f)

    async def get_matchups(self, ctx, week):
        """Fetch and display all matchups in one embed with league info."""
        await self.ensure_token()
        access_token = self.state.yahoo_token["access_token"]

        url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{YAHOO_LEAGUE_KEY}/scoreboard;week={week}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/xml"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()

        # Parse XML to get league info + matchups
        league_name, league_logo, matchups = self.parse_league_and_matchups_xml(text)

        if not matchups:
            await ctx.send("⚠️ No matchups found.")
            return

        embed = discord.Embed(
            title="🏈 Fantasy Matchups",
            description=f"Week {week} Matchups for **{league_name}**",
            color=discord.Color.blue()
        )
        if league_logo:
            embed.set_thumbnail(url=league_logo)

        # Add one field per matchup
        for home_name, home_points, home_logo, away_name, away_points, away_logo in matchups:
            matchup_text = f"**{home_name}** ({home_points:.2f})  vs  **{away_name}** ({away_points:.2f})"
            embed.add_field(name="\u200b", value=matchup_text, inline=False)

        await ctx.send(embed=embed)


    def parse_league_and_matchups_xml(self, xml_text):
        """Parse XML for league name, league logo, and all matchups with team info."""
        root = ET.fromstring(xml_text)
        ns = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

        # League info
        league = root.find(".//y:league", ns)
        league_name = league.find("y:name", ns).text if league is not None else "Unknown League"
        league_logo = None
        if league is not None:
            logo_el = league.find("y:logo_url", ns)
            league_logo = logo_el.text if logo_el is not None else None

        matchups = []

        for matchup in root.findall(".//y:matchup", ns):
            teams = matchup.findall(".//y:team", ns)
            if len(teams) < 2:
                continue

            def extract_team_info(team_elem):
                name_el = team_elem.find("y:name", ns)
                name = name_el.text if name_el is not None else "Unknown"

                pts_el = team_elem.find("y:team_points/y:total", ns)
                try:
                    points = float(pts_el.text) if pts_el is not None else 0.0
                except (ValueError, TypeError):
                    points = 0.0

                # Logo URL (prefer 'large' size)
                logo_url = None
                logos = team_elem.findall("y:team_logos/y:team_logo", ns)
                for logo in logos:
                    size_el = logo.find("y:size", ns)
                    url_el = logo.find("y:url", ns)
                    if size_el is not None and size_el.text == "large" and url_el is not None:
                        logo_url = url_el.text
                        break
                if not logo_url and logos:
                    url_el = logos[0].find("y:url", ns)
                    logo_url = url_el.text if url_el is not None else None

                return name, points, logo_url or ""

            home_name, home_points, home_logo = extract_team_info(teams[0])
            away_name, away_points, away_logo = extract_team_info(teams[1])

            matchups.append((home_name, home_points, home_logo, away_name, away_points, away_logo))

        return league_name, league_logo, matchups

__all__ = ['YahooFFService']