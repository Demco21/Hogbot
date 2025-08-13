from logging_config import logger
from bot_state import BotState
import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone as dt_timezone
from requests_oauthlib import OAuth2Session
from typing import Optional, Any, Dict, List
import xml.etree.ElementTree as ET
import aiohttp
import time
import asyncio
from pytz import timezone
import json
import os
import random
from config import (
    YAHOO_CLIENT_ID, 
    YAHOO_CLIENT_SECRET, 
    YAHOO_LEAGUE_KEY,
    ANNOUNCEMENTS_CHANNEL_ID
)
from constants import (
    NFL_SCHEDULE_FILE,
    YAHOO_TOKEN_FILE,
    WINNER_PHRASES_FILE
)

REDIRECT_URI = "https://localhost"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

class YahooFFService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

        # Load saved token if exists
        if os.path.exists(YAHOO_TOKEN_FILE):
            with open(YAHOO_TOKEN_FILE, "r") as f:
                self.state.yahoo_token = json.load(f)

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
                client_secret=YAHOO_CLIENT_SECRET
            )

            # Add expiry timestamp for refresh logic
            token["expires_at"] = time.time() + int(token.get("expires_in", 0))

            # Save token to file
            with open(YAHOO_TOKEN_FILE, "w") as f:
                json.dump(token, f)

            self.state.yahoo_token = token

            logger.info(f"Yahoo OAuth token saved to {YAHOO_TOKEN_FILE}")
            await ctx.send("✅ Authorized successfully! Token saved for future use.")
        except Exception as e:
            logger.error(f"Error during Yahoo OAuth: {e}")
            await ctx.send(f"❌ Authorization failed please try again.")
    
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
                    with open(YAHOO_TOKEN_FILE, "w") as f:
                        json.dump(new_token, f)

    async def get_matchups(self, ctx=None, week: Optional[int] = None):
        """
        Fetch the league scoreboard as JSON and post a single embed listing all matchups.
        - Crowns the leader with 🏆
        - Works for preevent/inprogress/postevent
        - Optional `week` arg; if None we derive from your schedule file
        """
        try:
            # ---------------------------------------------------------
            # Token
            # ---------------------------------------------------------
            await self.ensure_token()
            access_token = self.state.yahoo_token["access_token"]

            # ---------------------------------------------------------
            # Resolve week using local nfl schedule
            # ---------------------------------------------------------
            def _resolve_week_from_schedule() -> Optional[int]:
                try:
                    with open(NFL_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                        schedule = json.load(f)
                    # your existing helper on the bot:
                    return self.bot.nfl_service.get_current_nfl_week_num(schedule)
                except Exception as e:
                    logger.info(f"Could not resolve week from schedule: {e}")
                    return None

            if week is None:
                week = _resolve_week_from_schedule()
                if week is None:
                    return

            logger.info(f"Fetching matchups for week {week}")
            
            url = (
                f"https://fantasysports.yahooapis.com/fantasy/v2/"
                f"league/{YAHOO_LEAGUE_KEY}/scoreboard;week={week}?format=json"
            )
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }

            # ---------------------------------------------------------
            # Fetch JSON
            # ---------------------------------------------------------
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Scoreboard call failed ({resp.status}): {body}")
                    data = await resp.json()

            # ---------------------------------------------------------
            # Helpers for Yahoo’s XML->JSON shape
            # ---------------------------------------------------------
            def find_first(container: Any, key: str) -> Any:
                """Return the first value for `key` found anywhere inside a dict/list."""
                if isinstance(container, dict):
                    if key in container:
                        return container[key]
                    for v in container.values():
                        found = find_first(v, key)
                        if found is not None:
                            return found
                elif isinstance(container, list):
                    for item in container:
                        found = find_first(item, key)
                        if found is not None:
                            return found
                return None

            def extract_league_meta(fc: Dict[str, Any]) -> Dict[str, Any]:
                league = fc.get("league")
                name, logo, current_week = None, None, None
                if isinstance(league, list):
                    for item in league:
                        if isinstance(item, dict):
                            if name is None and "name" in item:
                                name = item.get("name")
                            if logo is None and "logo_url" in item:
                                logo = item.get("logo_url")
                            if current_week is None and "current_week" in item:
                                current_week = item.get("current_week")
                elif isinstance(league, dict):
                    name = league.get("name")
                    logo = league.get("logo_url")
                    current_week = league.get("current_week")
                return {"name": name, "logo_url": logo, "current_week": current_week}

            def extract_team_block(team_block: Any):
                """
                team_block is typically a list:
                [ <meta_list>, { 'win_probability'?, 'team_points': {...}, 'team_projected_points': {...} } ... ]
                Return: (name, points, logo_url, win_probability)
                """
                # meta_list
                meta_list = team_block[0] if isinstance(team_block, list) and team_block else []
                name = "Unknown Team"
                logo_url = None

                # name + logo
                if isinstance(meta_list, list):
                    for item in meta_list:
                        if isinstance(item, dict) and "name" in item:
                            name = item["name"]
                        if isinstance(item, dict) and "team_logos" in item:
                            logos = item["team_logos"]
                            if isinstance(logos, list):
                                first = None
                                large = None
                                for entry in logos:
                                    tl = entry.get("team_logo") if isinstance(entry, dict) else None
                                    if isinstance(tl, dict):
                                        url = tl.get("url")
                                        size = tl.get("size")
                                        if url and first is None:
                                            first = url
                                        if url and size == "large":
                                            large = url
                                logo_url = large or first

                # points + win_probability
                pts = 0.0
                wp = None
                if isinstance(team_block, list):
                    for part in team_block:
                        if isinstance(part, dict):
                            if "team_points" in part:
                                total = part["team_points"].get("total")
                                try:
                                    pts = float(total) if total not in (None, "") else 0.0
                                except (TypeError, ValueError):
                                    pts = 0.0
                            if "win_probability" in part:  # 0..1
                                try:
                                    wp = float(part["win_probability"])
                                except (TypeError, ValueError):
                                    wp = None

                return name, pts, logo_url, wp

            # ---------------------------------------------------------
            # Walk JSON: fantasy_content -> league -> scoreboard -> matchups -> teams
            # ---------------------------------------------------------
            fc = data.get("fantasy_content", {})
            league_meta = extract_league_meta(fc)

            scoreboard = find_first(fc.get("league"), "scoreboard")
            if not scoreboard:
                channel = ctx.channel if ctx else self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
                if channel:
                    await channel.send(f"⚠️ No scoreboard found for week {week}.")
                return

            matchups_container = find_first(scoreboard, "matchups")
            if not isinstance(matchups_container, dict):
                channel = ctx.channel if ctx else self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
                if channel:
                    await channel.send(f"⚠️ No matchups found for week {week}.")
                return

            raw_matchups: List[Dict[str, Any]] = []
            for v in matchups_container.values():
                if isinstance(v, dict) and "matchup" in v:
                    raw_matchups.append(v["matchup"])

            matchups: List[Dict[str, Any]] = []
            overall_statuses = set()

            for m in raw_matchups:
                status = m.get("status")  # 'preevent' | 'inprogress' | 'postevent'
                if status:
                    overall_statuses.add(status)

                teams_container = find_first(m, "teams")
                if not isinstance(teams_container, dict):
                    continue

                team_blocks = []
                for tv in teams_container.values():
                    if isinstance(tv, dict) and "team" in tv:
                        team_blocks.append(tv["team"])
                if len(team_blocks) != 2:
                    continue

                t1_name, t1_pts, t1_logo, t1_wp = extract_team_block(team_blocks[0])
                t2_name, t2_pts, t2_logo, t2_wp = extract_team_block(team_blocks[1])

                matchups.append({
                    "t1_name": t1_name, "t1_pts": t1_pts, "t1_logo": t1_logo, "t1_wp": t1_wp,
                    "t2_name": t2_name, "t2_pts": t2_pts, "t2_logo": t2_logo, "t2_wp": t2_wp,
                    "status": status or "unknown",
                })

            # ---------------------------------------------------------
            # Build and send embed
            # ---------------------------------------------------------
            channel = ctx.channel if ctx else self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                return

            league_name = league_meta.get("name") or "League"
            league_logo = league_meta.get("logo_url")

            # Color by aggregate status
            color = discord.Color.blurple()
            if "preevent" in overall_statuses and len(overall_statuses) == 1:
                color = discord.Color.dark_grey()
            elif "inprogress" in overall_statuses:
                color = discord.Color.gold()
            elif "postevent" in overall_statuses and len(overall_statuses) == 1:
                color = discord.Color.green()

            embed = discord.Embed(
                title=f"🏈 {league_name} — Week {week} Matchups",
                color=color
            )
            if league_logo:
                embed.set_thumbnail(url=league_logo)

            if not matchups:
                embed.description = "No matchups found."
                await channel.send(embed=embed)
                return

            for i, m in enumerate(matchups, 1):
                a = f"**{m['t1_name']}** ({m['t1_pts']:.2f})"
                b = f"**{m['t2_name']}** ({m['t2_pts']:.2f})"

                if abs(m["t1_pts"] - m["t2_pts"]) < 1e-9:
                    line = f"{a} vs {b}"
                elif m["t1_pts"] > m["t2_pts"]:
                    line = f"🏆 {a} vs {b}"
                else:
                    line = f"{a} vs 🏆 {b}"

                # Pre-game win probability (if present), helpful before kickoff
                if m["status"] == "preevent":
                    wp_a = f"{int(m['t1_wp']*100)}%" if isinstance(m["t1_wp"], float) else "—"
                    wp_b = f"{int(m['t2_wp']*100)}%" if isinstance(m["t2_wp"], float) else "—"
                    line += f"\nWP: {wp_a} vs {wp_b}"

                embed.add_field(name=f"", value=line, inline=False)

            def need_to_announce_winner() -> bool:
                if "postevent" in overall_statuses and len(overall_statuses) == 1:
                    if self.state.scoreboard_msg.get("winner_announced") is not True:
                        self.state.scoreboard_msg["winner_announced"] = True
                        return True
                return False
            
            if self.state.scoreboard_msg:
                if self.state.scoreboard_msg.get("week") == week:
                    logger.info(f"Updating existing scoreboard embed for week {week}")
                    updated = await self.update_embed(embed, self.state.scoreboard_msg)
                    if need_to_announce_winner():
                        await self.announce_winner(matchups, channel)
                    if updated:
                        return

            msg = await channel.send(embed=embed)

            self.state.scoreboard_msg = {
                "channel_id": channel.id,
                "message_id": msg.id,
                "week": week,
                "winner_announced": False
            }

        except Exception as e:
            logger.exception(f"Error fetching JSON matchups for week {week}: {e}")
            if ctx:
                await ctx.send(f"⚠️ Could not fetch matchups: {e}")

    async def update_embed(self, new_embed, info):
        try:
            if not info:
                return

            channel = self.bot.get_channel(info["channel_id"]) or await self.bot.fetch_channel(info["channel_id"])
            msg = await channel.fetch_message(info["message_id"])

            # Always use UTC for Discord timestamp
            new_embed.timestamp = datetime.now(dt_timezone.utc)

            # Also change footer text so the payload is guaranteed different (even if same-second)
            # If you prefer local time in the footer, format it here and still keep timestamp in UTC.
            new_embed.set_footer(text=f"Last updated")

            await msg.edit(embed=new_embed)
            return True
        except Exception as e:
            logger.error(f"Error updating scoreboard embed: {e}")
            return False

    async def announce_winner(self, matchups, channel):

        def get_random_winner_phrase(file_path: str = WINNER_PHRASES_FILE) -> str:
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

        for i, m in enumerate(matchups, 1):
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
    
    async def test_api(self, ctx = None):
        try:
            await self.ensure_token()
            access_token = self.state.yahoo_token["access_token"]
            # url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/461.l.550581/scoreboard;week=1"
            # url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/461.l.550581/standings?format=json"
            url = f"https://fantasysports.yahooapis.com/fantasy/v2/teams;team_keys=461.l.550581.t.1,461.l.550581.t.2/roster;week=1/players;stats?format=json"
            # url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/461.l.550581/standings?format=json"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    text = await response.text()

            logger.info(f"{url} API response:\n{text}")
        except Exception as e:
            logger.error(f"Error fetching matchups: {e}")

    async def post_standings_embeds(self, ctx=None, week=None):
        await self.ensure_token()
        access_token = self.state.yahoo_token["access_token"]

        # ---------------------------------------------------------
        # Resolve week using local nfl schedule
        # ---------------------------------------------------------
        def _resolve_week_from_schedule() -> Optional[int]:
            try:
                with open(NFL_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    schedule = json.load(f)
                # your existing helper on the bot:
                return self.bot.nfl_service.get_current_nfl_week_num(schedule)
            except Exception as e:
                logger.info(f"Could not resolve week from schedule: {e}")
                return None

        if week is None:
            week = _resolve_week_from_schedule()
            if week is None:
                return
        
        url = (
            f"https://fantasysports.yahooapis.com/fantasy/v2/"
            f"league/{YAHOO_LEAGUE_KEY}/standings?format=json"
        )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # --- fetch JSON ---
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Standings call failed ({resp.status}): {body}")
                data = await resp.json()
        
        teams, league_name, league_logo_url, current_week = await self.parse_standings_json(data)

        if not teams:
            await self._send_text(ctx, "⚠️ No teams found in team_standings.")
            return

        team_keys = ",".join(t["team_key"] for t in teams if "team_key" in t)
        url = f"https://fantasysports.yahooapis.com/fantasy/v2/teams;team_keys={team_keys}/roster;week={week}/players;stats?format=json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"teams call failed ({resp.status}): {body}")
                data = await resp.json()
                text = await resp.text()
        
        team_rosters = await self.parse_roster_json(data)

        if not team_rosters:
            await self._send_text(ctx, "⚠️ No team rosters found.")
            return

        channel = ctx.channel if ctx else self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
        if not channel:
            return
        
        roster_messages = self.state.roster_messages or {}

        if not roster_messages.get('week'):
            roster_messages['week'] = None

        if roster_messages['week'] != week: 
            embed = discord.Embed(
                title=f"{league_name} Standings",
                description=f"### Heading into week {week}",
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=league_logo_url)
            await channel.send(embed=embed)
            roster_messages['week'] = week

        def get_overall_game_state(roster):
            if not roster:
                return "waiting"
            
            states = [p.get("game_state") for p in roster]

            if all(state == "finished" for state in states):
                return "finished"
            elif any(state == "in_progress" for state in states):
                return "active"
            else:
                return "waiting"
            
        for t in teams:
            record = f"{t['wins']}-{t['losses']}" + (f"-{t['ties']}" if t["ties"] else "")
            embed = discord.Embed(
                title=t["name"],
                description=f"Manager: **{t['nickname']}**\nRecord: **{record}**",
            )
            if t["logo_url"]:
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

            if roster:
                for p in roster:
                    pos = p.get("position") or "—"
                    pts = p.get("total_points", 0.0) or 0.0
                    name = p.get("full_name") or "Unknown"
                    status = p.get("status") or ""
                    embed.add_field(
                        name=f"{pos}   pts:{pts:.2f}",
                        value=f"{name} {status}",
                        inline=True
                    )
            
            updated = False
            if roster_messages.get(team_key):
                info = roster_messages[team_key]
                if info.get("week") == week:
                    logger.info(f"Updating existing roster embed for team {t['name']} week {week}")
                    updated = await self.update_embed(embed, info)
            
            if not updated:
                msg = await channel.send(embed=embed)
                roster_messages[team_key] = {
                    "channel_id": channel.id,
                    "message_id": msg.id,
                    "week": week
                }
                self.state.roster_messages = roster_messages

            await asyncio.sleep(5)

    async def parse_standings_json(self, data):
        # logger.info(json.dumps(data, indent=2))
        # --- parse JSON (Yahoo XML->JSON is messy) ---
        # Navigate: fantasy_content -> league (list) -> standings -> teams (dict with numeric keys)
        fantasy_content = data.get("fantasy_content", {})
        league_list = fantasy_content.get("league", [])

        # Find the object that has "standings"
        standings_obj = None
        for part in league_list:
            if isinstance(part, dict) and "standings" in part:
                standings_obj = part["standings"]
                break
        if not standings_obj:
            await self._send_text(ctx, "⚠️ Could not find standings in response.")
            return

        if isinstance(standings_obj, list):
            standings_obj = standings_obj[0] if standings_obj else {}

        teams_container = standings_obj.get("teams") or {}
        # teams_container has numeric keys and a "count"
        teams = []
        for k, v in teams_container.items():
            if k == "count":
                continue
            if not isinstance(v, dict):
                continue
            team_block = v.get("team")
            if not team_block:
                continue
            teams.append(team_block)

        # Helper to pull values from that first meta list (list of dicts)
        def from_meta(meta_list, key):
            if not isinstance(meta_list, list):
                return None
            for item in meta_list:
                if isinstance(item, dict) and key in item:
                    return item[key]
            return None

        def get_logo_url(meta_list):
            logos = from_meta(meta_list, "team_logos")
            if isinstance(logos, list):
                large = None
                first = None
                for entry in logos:
                    if not isinstance(entry, dict):
                        continue
                    tl = entry.get("team_logo")
                    if isinstance(tl, dict):
                        url = tl.get("url")
                        size = tl.get("size")
                        if first is None and url:
                            first = url
                        if size == "large" and url:
                            large = url
                return large or first
            return None

        def get_manager_nickname(meta_list):
            managers = from_meta(meta_list, "managers")
            if isinstance(managers, list) and managers:
                mgr = managers[0].get("manager") if isinstance(managers[0], dict) else None
                if isinstance(mgr, dict):
                    return mgr.get("nickname")
            return None

        def extract_league_meta(league):
            if isinstance(league, list):
                for item in league:
                    if isinstance(item, dict) and ("name" in item or "logo_url" in item):
                        return item.get("name"), item.get("logo_url"), item.get("current_week")
            elif isinstance(league, dict):  # rare, but just in case
                return league.get("name"), league.get("logo_url"), league.get("current_week")
            return None, None, None

        league_name, league_logo_url, current_week = extract_league_meta(league_list)

        # Build a clean list of team dicts
        clean_team_dicts = []
        for team_block in teams:
            meta_list = team_block[0] if len(team_block) > 0 else []
            team_points_obj = team_block[1].get("team_points") if len(team_block) > 1 and isinstance(team_block[1], dict) else {}
            team_standings = team_block[2].get("team_standings") if len(team_block) > 2 and isinstance(team_block[2], dict) else {}

            name = from_meta(meta_list, "name") or "Unknown Team"
            team_key = from_meta(meta_list, "team_key") or None
            logo_url = get_logo_url(meta_list)

            nickname = get_manager_nickname(meta_list) or "—"

            # Prefer team_standings points_for/against for season totals
            points_for = team_standings.get("points_for", "0") if isinstance(team_standings, dict) else "0"
            points_against = team_standings.get("points_against", "0") if isinstance(team_standings, dict) else "0"
            try:
                points_for = float(points_for) if points_for not in (None, "") else 0.0
            except ValueError:
                points_for = 0.0
            try:
                points_against = float(points_against) if points_against not in (None, "") else 0.0
            except ValueError:
                points_against = 0.0

            outcomes = team_standings.get("outcome_totals", {}) if isinstance(team_standings, dict) else {}
            wins = int(outcomes.get("wins", 0) or 0)
            losses = int(outcomes.get("losses", 0) or 0)
            ties = int(outcomes.get("ties", 0) or 0)

            # Rank can help ordering
            try:
                rank = int(team_standings.get("rank", 9999) or 9999)
            except ValueError:
                rank = 9999

            clean_team_dicts.append({
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
        
        clean_team_dicts.sort(key=lambda t: t["rank"])
        return clean_team_dicts, league_name, league_logo_url, current_week

    async def parse_roster_json(self, data):
        # --- parse JSON (Yahoo XML->JSON is messy) ---
        #logger.info(json.dumps(data, indent=2))
        fantasy_content = data.get("fantasy_content", {})
        teams_container = fantasy_content.get("teams") or {}

        if not isinstance(teams_container, dict):
            league_list = fantasy_content.get("league", [])
            standings_obj = None
            for part in league_list:
                if isinstance(part, dict) and "standings" in part:
                    standings_obj = part["standings"]
                    break
            if isinstance(standings_obj, list):
                standings_obj = standings_obj[0] if standings_obj else {}
            teams_container = (standings_obj or {}).get("teams") or {}

        teams = []
        for k, v in teams_container.items():
            if k == "count":
                continue
            if not isinstance(v, dict):
                continue
            team_block = v.get("team")
            if not team_block:
                continue
            teams.append(team_block)

        # Helpers -----------------------------------------------------------------
        def from_meta(meta_list, key):
            if not isinstance(meta_list, list):
                return None
            for item in meta_list:
                if isinstance(item, dict) and key in item:
                    return item[key]
            return None

        def get_subdict(meta_list, key):
            val = from_meta(meta_list, key)
            return val if isinstance(val, dict) else {}

        def find_roster_obj(team_block):
            if not isinstance(team_block, list):
                return {}
            for item in team_block:
                if isinstance(item, dict) and "roster" in item and isinstance(item["roster"], dict):
                    return item["roster"]
            return {}

        def extract_players_list(roster_obj):
            node0 = roster_obj.get("0")
            if isinstance(node0, dict):
                players = node0.get("players")
                if isinstance(players, list):
                    return players

            players = roster_obj.get("players")
            if isinstance(players, list):
                return players

            if isinstance(players, dict):
                out = []
                try:
                    count = int(players.get("count", 0) or 0)
                except (TypeError, ValueError):
                    count = 0
                for i in range(count):
                    node = players.get(str(i))
                    if isinstance(node, dict):
                        out.append(node)
                return out

            return []

        # Parse a boolean-like value robustly (Yahoo often uses "1"/"0" or "true"/"false")
        def as_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return v != 0
            if isinstance(v, str):
                return v.strip().lower() in {"1", "true", "yes", "y"}
            return False

        # Find a value by scanning the list-of-dicts for any of several candidate keys
        def scan_for(meta_list, candidate_keys):
            if not isinstance(meta_list, list):
                return None
            for item in meta_list:
                if isinstance(item, dict):
                    for k in candidate_keys:
                        if k in item:
                            return item[k]
            return None

        # Derive a per-player game_state from whatever Yahoo provides, else heuristics
        def derive_player_game_state(p_list, total_points, week):
            # Try explicit flags first (these names show up in some sports/feeds)
            # If none of these are present in your league’s sport/feed, they’ll be None.
            explicit_is_playing = scan_for(p_list, ["is_playing", "in_game", "is_live"])
            explicit_started     = scan_for(p_list, ["game_started", "started", "has_started"])
            explicit_finished    = scan_for(p_list, ["game_finished", "completed", "has_finished"])

            # Bye-week hint (NFL often nests bye weeks under a dict)
            bye_obj  = get_subdict(p_list, "bye_weeks") or get_subdict(p_list, "bye_week")
            on_bye   = False
            if isinstance(bye_obj, dict):
                # common shapes: {"week": "7"} or {"0": {"week": "7"}}
                bye_week = bye_obj.get("week")
                if bye_week is None and "0" in bye_obj and isinstance(bye_obj["0"], dict):
                    bye_week = bye_obj["0"].get("week")
                try:
                    on_bye = (int(bye_week) == int(week))
                except (TypeError, ValueError):
                    on_bye = False

            # 1) Use explicit finished flag if present
            if explicit_finished is not None:
                return "finished" if as_bool(explicit_finished) else "in_progress"  # if explicitly not finished but flagged, treat as live

            # 2) Use explicit is_playing flag
            if explicit_is_playing is not None:
                return "in_progress" if as_bool(explicit_is_playing) else "not_started"

            # 3) Use explicit started flag
            if explicit_started is not None:
                return "in_progress" if as_bool(explicit_started) else "not_started"

            # 4) Bye week ⇒ not started (won’t play)
            if on_bye:
                return "not_started"

            # 5) Heuristics when nothing else is available:
            #    - If weekly points are strictly > 0 early in week, could be in-progress or finished.
            #    - We can’t reliably split those without kickoff/end timestamps, so:
            #      * If points == 0.0 → probably not started (or goose egg, but safe)
            #      * If points > 0.0 → mark as unknown; caller can refine later with scoreboard/schedule
            if total_points == 0.0:
                return "not_started"

            return "unknown"

        roster_by_team = {}

        # Try to read the requested week from the payload if present (caller already passes ?week={week})
        # If not available, set to None and heuristics won’t use bye logic.
        requested_week = None
        try:
            meta_game = fantasy_content.get("game", {})
            if isinstance(meta_game, dict):
                requested_week = int(meta_game.get("week")) if meta_game.get("week") is not None else None
        except Exception:
            requested_week = None

        # If not found above, accept a 'week' helper nested in teams -> roster
        if requested_week is None:
            # many payloads embed roster week at roster["week"]
            # we’ll just fill it per-team when available
            pass

        for team_block in teams:
            meta_list = team_block[0] if len(team_block) > 0 else []
            team_key = from_meta(meta_list, "team_key")
            if not team_key:
                team_key = from_meta(team_block if isinstance(team_block, list) else [], "team_key")
            if not team_key:
                continue

            roster_obj = find_roster_obj(team_block)
            # fallback: grab week off this roster if available
            this_roster_week = requested_week
            try:
                if this_roster_week is None:
                    w = roster_obj.get("week")
                    if isinstance(w, (str, int)):
                        this_roster_week = int(w)
            except Exception:
                pass

            players_nodes = extract_players_list(roster_obj)
            players_list = []

            for p in players_nodes:
                p_list = p.get("player", [])
                if not isinstance(p_list, list):
                    continue

                name_obj = get_subdict(p_list, "name")
                full_name = name_obj.get("full") if isinstance(name_obj, dict) else None

                player_id = from_meta(p_list, "player_id")

                selected_pos = get_subdict(p_list, "selected_position")
                position = selected_pos.get("position") if selected_pos else None
                if not position:
                    position = from_meta(p_list, "display_position")

                status = from_meta(p_list, "status")
                injury_note = from_meta(p_list, "injury_note")

                points_obj = get_subdict(p_list, "player_points")
                total_points_raw = points_obj.get("total") if isinstance(points_obj, dict) else None
                try:
                    total_points = float(total_points_raw) if total_points_raw not in (None, "") else 0.0
                except (TypeError, ValueError):
                    total_points = 0.0

                game_state = derive_player_game_state(
                    p_list,
                    total_points=total_points,
                    week=this_roster_week
                )

                players_list.append({
                    "full_name": full_name,
                    "player_id": player_id,
                    "position": position,
                    "status": status,
                    "injury_note": injury_note,
                    "total_points": total_points,
                    "game_state": game_state,
                })

            roster_by_team[team_key] = players_list

        return roster_by_team

    async def _send_text(self, ctx, msg: str):
        if ctx is not None and ctx.channel:
            await ctx.send(msg)
        else:
            ch = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if ch:
                await ch.send(msg)

__all__ = ['YahooFFService']