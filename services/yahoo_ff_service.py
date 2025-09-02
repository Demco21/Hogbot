from logging_config import logger
from bot_state import BotState
import discord
from discord.ext import commands
from datetime import datetime, timezone as dt_timezone
from requests_oauthlib import OAuth2Session
from typing import Optional, Any, Dict, List, Tuple
import xml.etree.ElementTree as ET
import aiohttp
import time
import asyncio
import json
import os
import random
from config import (
    YAHOO_CLIENT_ID,
    YAHOO_CLIENT_SECRET,
    YAHOO_LEAGUE_KEY,
    ANNOUNCEMENTS_CHANNEL_ID,
    FANTASY_FOOTBALL_CHANNEL_ID
)
from constants import (
    YAHOO_TOKEN_FILE,
    WINNER_PHRASES_FILE,
)

# ---------------------------------------------------------------------------
# OAuth endpoints
# ---------------------------------------------------------------------------
REDIRECT_URI = "https://localhost"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


class YahooFFService:
    """
    Yahoo Fantasy Football service (XML-only rewrite, Python 3.8).
    
    Public method names and overall behavior kept the same as the existing
    JSON-based service so callers don't need to change. Internally, we now
    parse Yahoo's native XML instead of using their XML->JSON shim.
    """

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

        # Load saved token if exists
        if os.path.exists(YAHOO_TOKEN_FILE):
            with open(YAHOO_TOKEN_FILE, "r") as f:
                self.state.yahoo_token = json.load(f)

    # -------------------------------------------------------------------
    # OAuth
    # -------------------------------------------------------------------
    async def fantasy_auth(self, ctx):
        """Manual Yahoo OAuth2 flow (one-time setup)."""
        try:
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
                client_secret=YAHOO_CLIENT_SECRET,
            )

            # Add expiry timestamp for refresh logic
            token["expires_at"] = time.time() + int(token.get("expires_in", 0))

            # Save token to file
            with open(YAHOO_TOKEN_FILE, "w") as f:
                json.dump(token, f)

            self.state.yahoo_token = token

            logger.info("Yahoo OAuth token saved")
            await ctx.send("✅ Authorized successfully! Token saved for future use.")
        except Exception as e:
            logger.error(f"Error during Yahoo OAuth: {e}")
            await ctx.send("❌ Authorization failed, please try again.")

    async def ensure_token(self):
        """Ensure a valid access token by refreshing if needed."""
        if not self.state.yahoo_token:
            raise RuntimeError("No token available. You must authorize once manually first.")

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
                    new_token["expires_at"] = time.time() + int(new_token.get("expires_in", 0) or 0)
                    self.state.yahoo_token = new_token
                    with open(YAHOO_TOKEN_FILE, "w") as f:
                        json.dump(new_token, f)

    # -------------------------------------------------------------------
    # XML helpers (namespace-agnostic; Yahoo sometimes wraps tags)
    # -------------------------------------------------------------------
    @staticmethod
    def _tag(t):
        return t.split('}', 1)[-1] if t and '}' in t else t

    @staticmethod
    def _child(node, name):
        if node is None:
            return None
        for c in list(node):
            if YahooFFService._tag(c.tag) == name:
                return c
        return None

    @staticmethod
    def _children(node, name):
        if node is None:
            return []
        out = []
        for c in list(node):
            if YahooFFService._tag(c.tag) == name:
                out.append(c)
        return out

    @staticmethod
    def _text(node, name, default=None):
        if node is None:
            return default
        c = YahooFFService._child(node, name)
        return c.text if c is not None else default

    @staticmethod
    def _iter_desc(node, name):
        out = []
        if node is None:
            return out
        for el in node.iter():
            if YahooFFService._tag(el.tag) == name:
                out.append(el)
        return out

    @staticmethod
    def _to_float(x, default=0.0):
        try:
            if x in (None, "", "-"):
                return float(default)
            return float(x)
        except (TypeError, ValueError):
            return float(default)

    # -------------------------------------------------------------------
    # Scoreboard / Matchups
    # -------------------------------------------------------------------
    async def post_fantasy_matchups(self, ctx=None, week=None):
        """
        Fetch the league scoreboard (XML) and post a single embed listing all matchups.
        Crowns the leader with 🏆. Colors reflect preevent/inprogress/postevent.
        """
        try:
            await self.ensure_token()
            access_token = self.state.yahoo_token["access_token"]

            if week is None:
                week = getattr(self.bot, "current_nfl_week", None)
                if week is None:
                    return

            async def get_scoreboard_xml(week):
                url = (
                    f"https://fantasysports.yahooapis.com/fantasy/v2/"
                    f"league/{YAHOO_LEAGUE_KEY}/scoreboard;week={week}"
                )
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/xml",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Scoreboard call failed ({resp.status}): {body}")
                        return await resp.text()

            scoreboard_xml = await get_scoreboard_xml(week)
            embed, matchups = await self.get_matchups_embed(ctx, week, scoreboard_xml)
            channel = ctx.channel if ctx else self.bot.get_channel(FANTASY_FOOTBALL_CHANNEL_ID)

            if embed is None:
                if channel:
                    await channel.send(f"⚠️ No matchups found for week {week}.")
                return

            def need_to_announce_winner():
                if self.state.scoreboard_msg and self.state.scoreboard_msg.get("week") != week:
                    return True
                return False

            if need_to_announce_winner():
                logger.info(f"Announcing winner for week {self.state.scoreboard_msg.get('week')}")
                last_week = week - 1
                scoreboard_xml_last_week = await get_scoreboard_xml(last_week)
                embed_last_week, matchups_last_week = await self.get_matchups_embed(ctx, last_week, scoreboard_xml_last_week)
                if need_to_announce_winner():
                    await self.announce_winner(matchups_last_week)

            msg = await channel.send(embed=embed)
            self.state.scoreboard_msg = {
                "channel_id": channel.id,
                "message_id": msg.id,
                "week": week
            }
        except Exception as e:
            logger.exception(f"Error fetching XML matchups for week {week}: {e}")
            if ctx:
                await ctx.send(f"⚠️ Could not fetch matchups: {e}")

    async def update_fantasy_matchups(self, ctx=None, week=None):
        """
        Fetch the league scoreboard (XML) and post a single embed listing all matchups.
        Crowns the leader with 🏆. Colors reflect preevent/inprogress/postevent.
        """
        try:
            await self.ensure_token()
            access_token = self.state.yahoo_token["access_token"]

            if week is None:
                week = getattr(self.bot, "current_nfl_week", None)
                if week is None:
                    return

            async def get_scoreboard_xml(week):
                url = (
                    f"https://fantasysports.yahooapis.com/fantasy/v2/"
                    f"league/{YAHOO_LEAGUE_KEY}/scoreboard;week={week}"
                )
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/xml",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Scoreboard call failed ({resp.status}): {body}")
                        return await resp.text()

            scoreboard_xml = await get_scoreboard_xml(week)
            embed, matchups = await self.get_matchups_embed(ctx, week, scoreboard_xml)

            if embed is None:
                if channel:
                    logger.info(f"⚠️ No matchups found for week {week}.")
                return

            updated = await self.update_embed(embed, self.state.scoreboard_msg)
            if updated:
                logger.info(f"Successfully updated fantasy matchups for week {week}")
            else:
                logger.error(f"Failed to update fantasy matchups for week {week}")
        except Exception as e:
            logger.exception(f"Error fetching XML matchups for week {week}: {e}")
            if ctx:
                await ctx.send(f"⚠️ Could not fetch matchups: {e}")
    # -------------------------------------------------------------------
    # Embeds
    # -------------------------------------------------------------------
    async def get_matchups_embed(self, ctx, week, xml_text):
        root = ET.fromstring(xml_text)

        # League meta
        league_el = self._iter_desc(root, "league")
        if not league_el:
            return
        league_el = league_el[0]
        league_name = self._text(league_el, "name") or "League"
        league_logo = self._text(league_el, "logo_url")

        scoreboard_el = self._child(league_el, "scoreboard")
        matchups_el = self._child(scoreboard_el, "matchups") if scoreboard_el is not None else None
        if matchups_el is None:
            return None

        matchups = []
        statuses = set()

        for m in self._children(matchups_el, "matchup"):
            status = self._text(m, "status", "unknown")
            statuses.add(status)

            teams_el = self._child(m, "teams")
            teams = self._children(teams_el, "team") if teams_el is not None else []
            if len(teams) != 2:
                continue

            def parse_team(team_el):
                name = self._text(team_el, "name", "Unknown Team")

                # logo
                logo_url = None
                team_logos = self._child(team_el, "team_logos")
                if team_logos is not None:
                    first = None
                    large = None
                    for tl in self._children(team_logos, "team_logo"):
                        url = self._text(tl, "url")
                        size = self._text(tl, "size")
                        if url and first is None:
                            first = url
                        if url and size and size.lower() == "large":
                            large = url
                    logo_url = large or first

                # points (either <team_points total=".."> OR <team_points><total>..)</n                    pts = 0.0
                tp = self._child(team_el, "team_points")
                if tp is not None:
                    total_attr = tp.attrib.get("total") if hasattr(tp, "attrib") else None
                    pts = self._to_float(total_attr if total_attr is not None else self._text(tp, "total"))

                wp = None
                wp_txt = self._text(team_el, "win_probability")
                if wp_txt is not None:
                    try:
                        wp = float(wp_txt)
                    except Exception:
                        wp = None

                return name, pts, logo_url, wp

            t1_name, t1_pts, t1_logo, t1_wp = parse_team(teams[0])
            t2_name, t2_pts, t2_logo, t2_wp = parse_team(teams[1])

            matchups.append({
                "t1_name": t1_name, "t1_pts": t1_pts, "t1_logo": t1_logo, "t1_wp": t1_wp,
                "t2_name": t2_name, "t2_pts": t2_pts, "t2_logo": t2_logo, "t2_wp": t2_wp,
                "status": status,
            })

        color = discord.Color.blurple()
        if statuses == {"preevent"}:
            color = discord.Color.dark_grey()
        elif "inprogress" in statuses:
            color = discord.Color.gold()
        elif statuses == {"postevent"}:
            color = discord.Color.green()

        embed = discord.Embed(title=f"🏈 {league_name} — Week {week} Matchups", color=color)
        if league_logo:
            embed.set_thumbnail(url=league_logo)

        if not matchups:
            return None

        for m in matchups:
            a = f"**{m['t1_name']}** ({m['t1_pts']:.2f})"
            b = f"**{m['t2_name']}** ({m['t2_pts']:.2f})"
            if abs(m["t1_pts"] - m["t2_pts"]) < 1e-9:
                line = f"{a} vs {b}"
            elif m["t1_pts"] > m["t2_pts"]:
                line = f"🏆 {a} vs {b}"
            else:
                line = f"{a} vs 🏆 {b}"

            if m["status"] == "preevent":
                wp_a = f"{int(m['t1_wp']*100)}%" if isinstance(m["t1_wp"], float) else "—"
                wp_b = f"{int(m['t2_wp']*100)}%" if isinstance(m["t2_wp"], float) else "—"
                line += f"\nWP: {wp_a} vs {wp_b}"

            embed.add_field(name="", value=line, inline=False)
        
        return embed, matchups
    
    async def update_embed(self, new_embed, info):
        try:
            if not info:
                return False
            channel = self.bot.get_channel(info["channel_id"]) or await self.bot.fetch_channel(info["channel_id"])
            msg = await channel.fetch_message(info["message_id"])

            new_embed.timestamp = datetime.now(dt_timezone.utc)
            new_embed.set_footer(text="Last updated")

            await msg.edit(embed=new_embed)
            return True
        except Exception as e:
            logger.error(f"Error updating scoreboard embed: {e}")
            return False

    async def get_standings_embeds(self, ctx, week, team_rosters, teams):
        def get_overall_game_state(roster):
            if not roster:
                return "waiting"
            states = [p.get("game_state") for p in roster]
            if states and all(s == "finished" for s in states):
                return "finished"
            if any(s == "in_progress" for s in states):
                return "active"
            return "waiting"

        embed_map = {}
        for t in teams:
            record = f"{t['wins']}-{t['losses']}" + (f"-{t['ties']}" if t['ties'] else "")
            embed = discord.Embed(
                title=t["name"],
                description=f"Manager: **{t['nickname']}**\nRecord: **{record}**",
            )
            if t.get("logo_url"):
                embed.set_thumbnail(url=t["logo_url"])
            embed.add_field(name="Points For", value=f"{t['points_for']:.2f}", inline=True)
            embed.add_field(name="Points Against", value=f"{t['points_against']:.2f}", inline=True)
            embed.add_field(name="", value=f"", inline=False)

            team_key = t["team_key"]
            roster = team_rosters.get(team_key, [])
            game_state = get_overall_game_state(roster)

            if game_state == "finished":
                embed.color = discord.Color.green()
            elif game_state == "active":
                embed.color = discord.Color.gold()
            else:
                embed.color = discord.Color.dark_grey()
            
            def _format_pts(pts):
                if pts is None:
                    return "ERR"
                else:
                    return f"{pts:.2f}"
            
            def _format_status(status=None):
                if not status:
                    return ""
                return f"`({status})`"

            def _format_pos(pos=None):
                pos_map = {
                    "QB": "🏈 QB",
                    "WR": "🎯 WR",
                    "RB": "🐂 RB",
                    "TE": "🪢 TE",
                    "W/R/T": "⚡ W/R/T",
                    "K": "👟 K",
                    "DEF": "🛡️ DEF",
                    "BN": "🪑 BN"
                }
                return pos_map.get(pos, pos)

            total_team_pts = 0.00
            # Starters first
            for p in roster:
                pos = p.get("position") or "—"
                if pos != "BN":
                    pts = p.get("total_points", None)
                    if pts is not None:
                        total_team_pts += pts
                    player_name = p.get("full_name") or "Unknown"
                    status = p.get("status") or ""
                    value = f"{player_name} {_format_status(status)}"
                    embed_name = f"{_format_pos(pos)}   {_format_pts(pts)}"
                    embed.add_field(name=embed_name, value=value, inline=True)

            # Bench
            for p in roster:
                pos = p.get("position") or "—"
                if pos == "BN":
                    pts = p.get("total_points", 0.0) or 0.0
                    player_name = p.get("full_name") or "Unknown"
                    status = p.get("status") or ""
                    value = f"{player_name} {_format_status(status)}"
                    embed_name = f"{_format_pos(pos)}   {_format_pts(pts)}"
                    embed.add_field(name=embed_name, value=value, inline=True)

            embed.add_field(name=f"Total Score: {total_team_pts:.2f}",value="", inline=False)
            embed_map[team_key] = embed
        return embed_map

    async def announce_winner(self, matchups):
        def get_random_winner_phrase(file_path=WINNER_PHRASES_FILE):
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Winner phrases file not found: {file_path}")
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            phrases = data.get("phrases")
            if not phrases or not isinstance(phrases, list):
                raise ValueError(f"No valid 'phrases' list found in {file_path}")
            return random.choice(phrases)

        if not matchups:
            logger.error("No matchups to announce winners for.")
            return
        channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
        for m in matchups:
            embed = discord.Embed(color=discord.Color.green())
            if abs(m["t1_pts"] - m["t2_pts"]) < 1e-9:
                if m["t1_logo"]:
                    embed.set_thumbnail(url=m["t1_logo"]) 
                embed.description = "### 🏆 " + get_random_winner_phrase() % ("**"+m["t1_name"]+"**", "**"+m["t2_name"]+"**")
            elif m["t1_pts"] > m["t2_pts"]:
                if m["t1_logo"]:
                    embed.set_thumbnail(url=m["t1_logo"]) 
                embed.description = "### 🏆 " + get_random_winner_phrase() % (m["t1_name"], m["t2_name"]) 
            else:
                if m["t2_logo"]:
                    embed.set_thumbnail(url=m["t2_logo"]) 
                embed.description = "### 🏆 " + get_random_winner_phrase() % (m["t2_name"], m["t1_name"]) 
            await channel.send(embed=embed)

    # -------------------------------------------------------------------
    # Standings + Rosters (with weekly points)
    # -------------------------------------------------------------------
    async def post_fantasy_standings(self, ctx=None, week=None):
        if week is None:
            week = getattr(self.bot, "current_nfl_week", None)
            if week is None:
                return

        teams, league_name, league_logo_url, current_week, team_rosters = await self.fetch_all_fantasy_standings_info(week)

        if not team_rosters:
            await self._send_text(ctx, "⚠️ No team rosters found.")
            return

        channel = ctx.channel if ctx else self.bot.get_channel(FANTASY_FOOTBALL_CHANNEL_ID)
        if not channel:
            return

        roster_messages = self.state.roster_messages or {}
        if not roster_messages.get('week'):
            roster_messages['week'] = None

        if roster_messages['week'] != week:
            embed = discord.Embed(
                title=f"{league_name} Standings",
                description=f"### Heading into week {week}",
                color=discord.Color.red(),
            )
            if league_logo_url:
                embed.set_thumbnail(url=league_logo_url)
            await channel.send(embed=embed)
            roster_messages['week'] = week

        embed_map = await self.get_standings_embeds(ctx, week, team_rosters, teams)
        roster_messages = self.state.roster_messages
        updated = False
        for team_key, embed in embed_map.items():
            msg = await channel.send(embed=embed)
            roster_messages[team_key] = {
                "channel_id": channel.id,
                "message_id": msg.id,
                "week": week,
            }
            self.state.roster_messages = roster_messages

        await asyncio.sleep(5)

    async def update_fantasy_standings(self, ctx=None, week=None):
        if week is None:
            week = getattr(self.bot, "current_nfl_week", None)
            if week is None:
                return

        teams, league_name, league_logo_url, current_week, team_rosters = await self.fetch_all_fantasy_standings_info(week)

        if not team_rosters:
            await self._send_text(ctx, "⚠️ No team rosters found.")
            return

        roster_messages = self.state.roster_messages or None
        if not roster_messages:
            logger.warning("no roster messages to update")
            return

        embed_map = await self.get_standings_embeds(ctx, week, team_rosters, teams)
        updated = False
        for team_key, embed in embed_map.items():
            if roster_messages.get(team_key):
                logger.info(f"Updating existing roster embed for team {team_key} week {week}")
                updated = await self.update_embed(embed, roster_messages[team_key])
            if not updated:
                logger.error("failed to update embed")
            await asyncio.sleep(5)

    async def fetch_all_fantasy_standings_info(self, week):
        await self.ensure_token()
        access_token = self.state.yahoo_token["access_token"]
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/xml"}

        # 1) Standings (XML)
        standings_url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{YAHOO_LEAGUE_KEY}/standings"
        async with aiohttp.ClientSession() as session:
            async with session.get(standings_url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Standings call failed ({resp.status}): {body}")
                standings_xml = await resp.text()

            teams, league_name, league_logo_url, current_week = await self.parse_standings_xml(standings_xml)
            if not teams:
                await self._send_text(ctx, "⚠️ No teams found in team_standings.")
                return

            # 2) Rosters (XML)
            team_keys = ",".join(t["team_key"] for t in teams if "team_key" in t)
            roster_url = (
                f"https://fantasysports.yahooapis.com/fantasy/v2/"
                f"teams;team_keys={team_keys}/roster;week={week}/players"
            )
            async with session.get(roster_url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Teams/roster call failed ({resp.status}): {body}")
                roster_xml = await resp.text()

            # logger.info(f"roster xml: {roster_xml}")
            roster_root = ET.fromstring(roster_xml)
            roster_map, all_player_keys = self._parse_roster_xml(roster_root)

            # 3) Weekly stats/points for those players (XML)
            points_by_key = {}
            if all_player_keys:
                chunk = 25
                keys_list = list(all_player_keys)
                for i in range(0, len(keys_list), chunk):
                    sub = keys_list[i:i+chunk]
                    stats_url = (
                        f"https://fantasysports.yahooapis.com/fantasy/v2/"
                        f"league/{YAHOO_LEAGUE_KEY}/players;player_keys={','.join(sub)}/stats;type=week;week={week}"
                    )
                    async with session.get(stats_url, headers=headers) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Players stats call failed ({resp.status}): {body}")
                        stats_xml = await resp.text()
                    # logger.info(f"player stats xml: {stats_xml}")
                    stats_root = ET.fromstring(stats_xml)

                    # Prefer player_points; if missing, compute via modifiers
                    pts = self._build_points_index(stats_root)
                    missing = [k for k in sub if k not in pts]
                    if missing:
                        for k in missing:
                            pts[k] = None
                    points_by_key.update(pts)

            team_rosters = self._merge_points_into_roster(roster_map, points_by_key)
        return teams, league_name, league_logo_url, current_week, team_rosters
        
    # -------------------------------------------------------------------
    # XML parsing helpers for standings/roster
    # -------------------------------------------------------------------
    async def parse_standings_xml(self, xml_text):  # name kept for compatibility
        """Parse standings XML; return (teams_list, league_name, league_logo_url, current_week)."""
        # logger.info(f"standings: {xml_text}")
        root = ET.fromstring(xml_text)
        league_el = self._iter_desc(root, "league")
        if not league_el:
            return [], None, None, None
        league_el = league_el[0]

        league_name = self._text(league_el, "name")
        league_logo_url = self._text(league_el, "logo_url")
        current_week = self._text(league_el, "current_week")

        standings_el = self._child(league_el, "standings")
        if standings_el is None:
            return [], league_name, league_logo_url, current_week
        teams_el = self._child(standings_el, "teams")
        if teams_el is None:
            return [], league_name, league_logo_url, current_week

        teams = []
        for team_el in self._children(teams_el, "team"):
            name = self._text(team_el, "name", "Unknown Team")
            team_key = self._text(team_el, "team_key")

            # logo
            logo_url = None
            team_logos = self._child(team_el, "team_logos")
            if team_logos is not None:
                first = None
                large = None
                for tl in self._children(team_logos, "team_logo"):
                    url = self._text(tl, "url")
                    size = self._text(tl, "size")
                    if url and first is None:
                        first = url
                    if url and size and size.lower() == "large":
                        large = url
                logo_url = large or first

            # manager nickname
            nickname = "—"
            managers = self._child(team_el, "managers")
            if managers is not None:
                mgr = self._child(managers, "manager")
                if mgr is not None:
                    nickname = self._text(mgr, "nickname", nickname)

            team_standings = self._child(team_el, "team_standings")
            points_for = self._to_float(self._text(team_standings, "points_for") if team_standings is not None else None)
            points_against = self._to_float(self._text(team_standings, "points_against") if team_standings is not None else None)

            rank = 9999
            if team_standings is not None:
                try:
                    rank = int(self._text(team_standings, "rank") or 9999)
                except Exception:
                    rank = 9999

            wins = losses = ties = 0
            if team_standings is not None:
                outcomes = self._child(team_standings, "outcome_totals")
                if outcomes is not None:
                    try:
                        wins = int(self._text(outcomes, "wins") or 0)
                        losses = int(self._text(outcomes, "losses") or 0)
                        ties = int(self._text(outcomes, "ties") or 0)
                    except Exception:
                        wins = losses = ties = 0

            teams.append({
                "team_key": team_key,
                "name": name,
                "nickname": nickname,
                "logo_url": logo_url,
                "points_for": points_for,
                "points_against": points_against,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "rank": rank,
            })

        teams.sort(key=lambda t: t["rank"])  # match previous ordering
        return teams, league_name, league_logo_url, current_week

    def _parse_roster_xml(self, roster_root):
        """Parse roster XML into {team_key: [players...]} and collect player_keys."""
        roster_map = {}
        all_player_keys = []

        teams_els = self._iter_desc(roster_root, "teams")
        if not teams_els:
            return roster_map, all_player_keys
        teams_el = teams_els[0]

        for team_el in self._children(teams_el, "team"):
            team_key = self._text(team_el, "team_key")
            if not team_key:
                roster_map[team_key] = []
                continue

            out_players = []
            roster_el = self._child(team_el, "roster")
            players_el = self._child(roster_el, "players") if roster_el is not None else None
            if players_el is None:
                roster_map[team_key] = out_players
                continue

            for p in self._children(players_el, "player"):
                pkey = self._text(p, "player_key")
                pid = self._text(p, "player_id")
                name_el = self._child(p, "name")
                full = self._text(name_el, "full") if name_el is not None else None
                display_pos = self._text(p, "display_position")
                sel_pos_el = self._child(p, "selected_position")
                sel_pos = self._text(sel_pos_el, "position") if sel_pos_el is not None else None
                status = self._text(p, "status")
                injury_note = self._text(p, "injury_note")

                out_players.append({
                    "player_key": pkey,
                    "player_id": pid,
                    "full_name": full,
                    "position": sel_pos or display_pos,
                    "status": status,
                    "injury_note": injury_note,
                    "total_points": 0.0,
                    "game_state": "waiting",
                })

                if pkey:
                    all_player_keys.append(pkey)

            roster_map[team_key] = out_players

        return roster_map, all_player_keys

    def _build_points_index(self, stats_root):
        """Return {player_key: total_points} using <player_points><total> when present."""
        idx = {}
        for p in self._iter_desc(stats_root, "player"):
            pkey = self._text(p, "player_key")
            ppoints = self._child(p, "player_points")
            if pkey and ppoints is not None:
                total = self._text(ppoints, "total")
                if total is not None:
                    idx[pkey] = self._to_float(total)
        return idx

    def _merge_points_into_roster(self, roster_map_basic, points_by_key):
        for team_key, players in roster_map_basic.items():
            for p in players:
                pkey = p.get("player_key")
                pts = points_by_key.get(pkey, 0.0)
                p["total_points"] = pts
                p["game_state"] = "in_progress" if pts and pts > 0 else "waiting"
        return roster_map_basic

    # -------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------
    async def _send_text(self, ctx, msg):
        if ctx is not None and ctx.channel:
            await ctx.send(msg)
        else:
            ch = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if ch:
                await ch.send(msg)


__all__ = ["YahooFFService"]
