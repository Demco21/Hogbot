import discord
from logging_config import logger
from datetime import datetime
import aiohttp
import os
import json
import asyncio
from zoneinfo import ZoneInfo
from bot_state import BotState
from config import ANNOUNCEMENTS_CHANNEL_ID
from constants import NFL_SCHEDULE_FILE
from config import (
    GIANTS_EMOJI_ID, JETS_EMOJI_ID, BILLS_EMOJI_ID, PATRIOTS_EMOJI_ID, DOLPHINS_EMOJI_ID,
    RAVENS_EMOJI_ID, BENGALS_EMOJI_ID, BROWNS_EMOJI_ID, STEELERS_EMOJI_ID, TITANS_EMOJI_ID,
    COLTS_EMOJI_ID, TEXANS_EMOJI_ID, JAGUARS_EMOJI_ID, CHIEFS_EMOJI_ID, BRONCOS_EMOJI_ID,
    CHARGERS_EMOJI_ID, RAIDERS_EMOJI_ID, EAGLES_EMOJI_ID, COWBOYS_EMOJI_ID, COMMANDERS_EMOJI_ID,
    PACKERS_EMOJI_ID, BEARS_EMOJI_ID, VIKINGS_EMOJI_ID, LIONS_EMOJI_ID, FALCONS_EMOJI_ID,
    SAINTS_EMOJI_ID, BUCCANEERS_EMOJI_ID, PANTHERS_EMOJI_ID, NINERS_EMOJI_ID, SEAHAWKS_EMOJI_ID,
    RAMS_EMOJI_ID, CARDINALS_EMOJI_ID
)

ESPN_EVENTS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "seasons/{year}/types/2/weeks/{week}/events?lang=en&region=us"
)

ESPN_STATUS_URL = (
    "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{game_id}/competitions/{game_id}/status?lang=en&region=us"
)

ESPN_ODDS_URL = (
    "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{game_id}/competitions/{game_id}/odds?lang=en&region=us"
)

ESPN_REG_SEASONS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "seasons/{year}/types/2/weeks/{week}/events?lang=en&region=us"
)

NY_TZ = ZoneInfo("America/New_York")

NFL_TEAM_LOGOS = {
    "New York Giants": {"logo_name": "giants", "logo_id": GIANTS_EMOJI_ID},
    "New York Jets": {"logo_name": "jets", "logo_id": JETS_EMOJI_ID},
    "Buffalo Bills": {"logo_name": "bills", "logo_id": BILLS_EMOJI_ID},
    "New England Patriots": {"logo_name": "patriots", "logo_id": PATRIOTS_EMOJI_ID},
    "Miami Dolphins": {"logo_name": "dolphins", "logo_id": DOLPHINS_EMOJI_ID},
    "Baltimore Ravens": {"logo_name": "ravens", "logo_id": RAVENS_EMOJI_ID},
    "Cincinnati Bengals": {"logo_name": "bengals", "logo_id": BENGALS_EMOJI_ID},
    "Cleveland Browns": {"logo_name": "browns", "logo_id": BROWNS_EMOJI_ID},
    "Pittsburgh Steelers": {"logo_name": "steelers", "logo_id": STEELERS_EMOJI_ID},
    "Tennessee Titans": {"logo_name": "titans", "logo_id": TITANS_EMOJI_ID},
    "Indianapolis Colts": {"logo_name": "colts", "logo_id": COLTS_EMOJI_ID},
    "Houston Texans": {"logo_name": "texans", "logo_id": TEXANS_EMOJI_ID},
    "Jacksonville Jaguars": {"logo_name": "jaguars", "logo_id": JAGUARS_EMOJI_ID},
    "Kansas City Chiefs": {"logo_name": "chiefs", "logo_id": CHIEFS_EMOJI_ID},
    "Denver Broncos": {"logo_name": "broncos", "logo_id": BRONCOS_EMOJI_ID},
    "Los Angeles Chargers": {"logo_name": "chargers", "logo_id": CHARGERS_EMOJI_ID},
    "Las Vegas Raiders": {"logo_name": "raiders", "logo_id": RAIDERS_EMOJI_ID},
    "Philadelphia Eagles": {"logo_name": "eagles", "logo_id": EAGLES_EMOJI_ID},
    "Dallas Cowboys": {"logo_name": "cowboys", "logo_id": COWBOYS_EMOJI_ID},
    "Washington Commanders": {"logo_name": "commanders", "logo_id": COMMANDERS_EMOJI_ID},
    "Green Bay Packers": {"logo_name": "packers", "logo_id": PACKERS_EMOJI_ID},
    "Chicago Bears": {"logo_name": "bears", "logo_id": BEARS_EMOJI_ID},
    "Minnesota Vikings": {"logo_name": "vikings", "logo_id": VIKINGS_EMOJI_ID},
    "Detroit Lions": {"logo_name": "lions", "logo_id": LIONS_EMOJI_ID},
    "Atlanta Falcons": {"logo_name": "falcons", "logo_id": FALCONS_EMOJI_ID},
    "New Orleans Saints": {"logo_name": "saints", "logo_id": SAINTS_EMOJI_ID},
    "Tampa Bay Buccaneers": {"logo_name": "buccaneers", "logo_id": BUCCANEERS_EMOJI_ID},
    "Carolina Panthers": {"logo_name": "panthers", "logo_id": PANTHERS_EMOJI_ID},
    "San Francisco 49ers": {"logo_name": "49ers", "logo_id": NINERS_EMOJI_ID},
    "Seattle Seahawks": {"logo_name": "seahawks", "logo_id": SEAHAWKS_EMOJI_ID},
    "Los Angeles Rams": {"logo_name": "rams", "logo_id": RAMS_EMOJI_ID},
    "Arizona Cardinals": {"logo_name": "cardinals", "logo_id": CARDINALS_EMOJI_ID}
}
NFL_LOGO = "https://upload.wikimedia.org/wikipedia/en/thumb/a/a2/National_Football_League_logo.svg/1200px-National_Football_League_logo.svg.png"

class ESPNService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    # --------------------- low-level helpers ---------------------

    async def fetch_json(self, session: aiohttp.ClientSession, url: str):
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    def parse_iso_utc_to_est(self, iso_dt: str) -> str:
        """Convert '2025-09-05T00:20Z' (UTC) to America/New_York ISO string."""
        dt_utc = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
        return dt_utc.astimezone(NY_TZ).isoformat()

    async def deref_if_needed(self, session: aiohttp.ClientSession, maybe_ref):
        """
        Resolve ESPN Core API $ref pointers:
          - dict with {"$ref": "..."}  -> fetch and return object
          - list of dicts with "$ref"  -> fetch each, return list of objects
          - otherwise return as-is
        """
        if isinstance(maybe_ref, dict) and "$ref" in maybe_ref:
            return await self.fetch_json(session, maybe_ref["$ref"])
        if isinstance(maybe_ref, list):
            out = []
            for item in maybe_ref:
                if isinstance(item, dict) and "$ref" in item:
                    out.append(await self.fetch_json(session, item["$ref"]))
                else:
                    out.append(item)
            return out
        return maybe_ref

    async def get_team_display(self, session: aiohttp.ClientSession, team_ref) -> dict:
        """Return best-effort team identification dict."""
        team = await self.deref_if_needed(session, team_ref)
        if not isinstance(team, dict):
            return {"id": None, "name": None, "abbreviation": None}

        return {
            "id": team.get("id"),
            "name": (
                team.get("displayName")
                or team.get("shortDisplayName")
                or team.get("name")
                or team.get("location")
            ),
            "abbreviation": team.get("abbreviation"),
        }

    async def get_broadcasts(self, session: aiohttp.ClientSession, broadcasts_ref) -> tuple[list, list]:
        """
        Returns (tv_networks, streaming_networks).
        """
        tv, streaming = [], []

        broadcasts = await self.deref_if_needed(session, broadcasts_ref)
        # logger.info(f"broadcasts:{broadcasts}")
        if not isinstance(broadcasts, dict):
            return tv, streaming

        items = broadcasts.get("items") or []
        expanded_items = []
        for it in items:
            if isinstance(it, dict) and "$ref" in it:
                expanded_items.append(await self.fetch_json(session, it["$ref"]))
            else:
                expanded_items.append(it)

        for b in expanded_items:
            btype_name = (b.get("type") or {}).get("shortName", "")
            station = (b.get("station") or "")

            if isinstance(btype_name, str) and btype_name.lower() in {"tv", "television"}:
                tv.append(station)
            elif isinstance(btype_name, str) and btype_name.lower() in {"streaming", "digital"}:
                streaming.append(station)

        def dedup(seq):
            seen, out = set(), []
            for x in seq:
                if x and x not in seen:
                    out.append(x)
                    seen.add(x)
            return out

        return dedup(tv), dedup(streaming)

    async def get_nfl_game_odds(self, game_id: str) -> dict[str, float | int | str | None]:
        url = ESPN_ODDS_URL.format(game_id=game_id)

        async with aiohttp.ClientSession() as session:
            index = await self.fetch_json(session, url)
            items = index.get("items") or []
            odds_list: list[dict] = []

            for item in items:
                odds = await self.deref_if_needed(session, item)
                if odds:
                    odds_list.append(odds)

            if not odds_list:
                return {
                    "over_under": None,
                    "home_ml": None,
                    "away_ml": None,
                    "spread": None,
                }

            # Pick provider with lowest priority
            def priority(o: dict) -> int:
                prov = o.get("provider") or {}
                try:
                    return int(prov.get("priority", 1_000_000))
                except Exception:
                    return 1_000_000

            odds_list.sort(key=priority)
            o = odds_list[0]

            # --- Over/Under ---
            over_under = o.get("overUnder")
            if over_under is None:
                total = (o.get("current") or {}).get("total") or {}
                try:
                    over_under = float(total.get("american")) if total.get("american") else None
                except Exception:
                    over_under = None

            # --- Moneylines ---
            def extract_moneyline(team_odds: dict) -> int | None:
                if not team_odds:
                    return None
                ml = team_odds.get("moneyLine")
                if ml is not None:
                    try:
                        return int(ml)
                    except Exception:
                        pass
                cur_ml = ((team_odds.get("current") or {}).get("moneyLine") or {}).get("alternateDisplayValue")
                if cur_ml:
                    try:
                        return int(cur_ml)
                    except Exception:
                        return None
                return None

            home_ml = extract_moneyline(o.get("homeTeamOdds"))
            away_ml = extract_moneyline(o.get("awayTeamOdds"))

            # --- Spread ---
            spread_val = o.get("spread")
            spread_str = None
            if spread_val is not None:
                # Determine which team is favorite
                team_ref = None
                if (o.get("homeTeamOdds") or {}).get("favorite"):
                    team_ref = o["homeTeamOdds"]["team"]["$ref"]
                elif (o.get("awayTeamOdds") or {}).get("favorite"):
                    team_ref = o["awayTeamOdds"]["team"]["$ref"]

                team_name = None
                if team_ref:
                    try:
                        team_obj = await self.deref_if_needed(session, {"$ref": team_ref})
                        team_name = team_obj.get("abbreviation") or team_obj.get("displayName")
                    except Exception:
                        pass

                if team_name:
                    spread_str = f"{team_name} {spread_val}"

            return {
                "over_under": over_under,  # float like 46.5
                "home_ml": home_ml,        # int like -290
                "away_ml": away_ml,        # int like 240
                "spread": spread_str,      # str like "PHI -6.5"
            }

    async def get_nfl_week_games(self, year: int, week: int) -> list[dict]:
        """
        Fetch all NFL games for a given season week from ESPN Core API and return:
        [
          {
            "home_team": "Philadelphia Eagles",
            "away_team": "Dallas Cowboys",
            "location": "Philadelphia, PA",
            "kickoff_est": "2025-09-04T20:20:00-04:00",
            "tv_networks": ["NBC"],
            "streaming_networks": ["Peacock"]
          },
          ...
        ]
        """
        url = ESPN_EVENTS_URL.format(year=year, week=week)
        async with aiohttp.ClientSession() as session:
            index = await self.fetch_json(session, url)
            # logger.info(f"index: {index}")
            items = index.get("items") or []
            games: list[dict] = []

            for item in items:
                # Each item is {"$ref": ".../events/{eventId}"}
                event = await self.deref_if_needed(session, item)
                # logger.info(f"event: {event}")
                if not isinstance(event, dict):
                    continue

                competitions = await self.deref_if_needed(session, event.get("competitions") or [])
                # logger.info(f"competitions: {competitions}")
                if not competitions:
                    continue
                comp = competitions[0]

                # kickoff in EST
                comp_date = comp.get("date") or event.get("date")
                kickoff_iso_est = self.parse_iso_utc_to_est(comp_date) if comp_date else None

                # competitors (home/away + team refs)
                competitors = await self.deref_if_needed(session, comp.get("competitors") or [])
                # logger.info(f"competitors: {competitors}")
                home_team = away_team = home_abbrv = away_abbrv = None
                for c in competitors:
                    team_info = await self.get_team_display(session, c.get("team"))
                    name = team_info["name"] or team_info["abbreviation"]
                    abbrvName = team_info["abbreviation"] or None
                    if c.get("homeAway") == "home":
                        home_team = name
                        home_abbrv = abbrvName
                    elif c.get("homeAway") == "away":
                        away_team = name
                        away_abbrv = abbrvName

                # venue / location
                venue = await self.deref_if_needed(session, comp.get("venue"))
                venue_name = city = state = None
                if isinstance(venue, dict):
                    venue_name = venue.get("fullName")
                    addr = venue.get("address") or {}
                    city = addr.get("city")
                    state = addr.get("state")
                    country = addr.get("country")
                if country == "USA":
                    location_parts = [p for p in (city, state) if p]
                else:
                    location_parts = [p for p in (city, country) if p]
                location = ", ".join(location_parts) if location_parts else None

                # status / odds / leaders / probabilities $ref
                game_id = comp.get("id") or ""

                # broadcasts
                tv_networks, streaming_networks = await self.get_broadcasts(session, comp.get("broadcasts"))

                games.append({
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_abbrv": home_abbrv,
                    "away_abbrv": away_abbrv,
                    "location": location,
                    "kickoff_est": kickoff_iso_est,
                    "tv_networks": tv_networks,
                    "streaming_networks": streaming_networks,
                    "game_id": game_id
                })
            
            logger.info(games)
            return games

    async def dump_regular_season_games(self, year: int, out_path: str | None = None) -> dict:
        """
        Build a season-wide dump using get_nfl_week_games for every regular-season week.
        Adds a "byes" map computed as teams not appearing in that week's games.
        Writes JSON to data/nfl_game_dump_{year}.json and returns the dict.

        Output format:
        {
          "year": 2025,
          "season_type": 2,
          "weeks": { "1": [ ...games... ], ... },
          "byes":  { "1": ["Pittsburgh Steelers", "Kansas City Chiefs"], ... }
        }
        """
        import asyncio
        import aiohttp
        import os
        import json

        logger.info("started dump_regular_season_games")
        out_path = out_path or f"data/nfl_game_dump_{year}.json"

        # 1) Find the number of regular-season weeks from ESPN Core (types/2)
        weeks_index_url = (
            f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
            f"seasons/{year}/types/2/weeks?lang=en&region=us"
        )
        week_count = 18  # sensible fallback
        try:
            async with aiohttp.ClientSession() as session:
                idx = await self.fetch_json(session, weeks_index_url)
                if isinstance(idx, dict) and "count" in idx:
                    week_count = int(idx["count"]) or 18
        except Exception as e:
            self.state.logger.warning if hasattr(self.state, "logger") else None
            # Continue with fallback
            logger.warning(f"Couldn't fetch weeks index for {year}; defaulting to {week_count} weeks: {e}")

        # 2) Fetch all weeks (with a small concurrency limit to be polite)
        sem = asyncio.Semaphore(6)

        async def fetch_week(w: int):
            async with sem:
                try:
                    games = await self.get_nfl_week_games(year, w)
                except Exception as e:
                    logger.exception(f"Failed to fetch games for week {w}: {e}")
                    games = []
                return w, games

        results = await asyncio.gather(*(fetch_week(w) for w in range(1, week_count + 1)))

        # 3) Assemble "weeks" structure
        weeks_dict: dict[str, list[dict]] = {str(week): games for week, games in sorted(results)}

        # 4) Compute byes: teams not present in that week's games
        all_teams = set(NFL_TEAM_LOGOS.keys())  # canonical 32 names
        byes: dict[str, list[str]] = {}

        for week_str, games in weeks_dict.items():
            present: set[str] = set()
            for g in games:
                home = g.get("home_team")
                away = g.get("away_team")
                if home:
                    present.add(home)
                if away:
                    present.add(away)

            # Only count teams we know about (full names) to avoid weird strings
            present_full = {t for t in present if t in all_teams}
            # Teams not present this week are on bye
            byes_week = sorted(all_teams - present_full)
            byes[week_str] = byes_week

        dump_obj = {
            "year": year,
            "season_type": 2,  # 2 = regular season in ESPN Core
            "weeks": weeks_dict,
            "byes": byes,
        }

        # 5) Write to file
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(dump_obj, f, indent=2, ensure_ascii=False)

        logger.info(f"Wrote NFL game dump to {out_path}")
        logger.info("end dump_regular_season_games")
        return dump_obj

__all__ = ["ESPNService"]
