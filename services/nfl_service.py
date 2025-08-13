import discord
from logging_config import logger
from pytz import timezone
from datetime import datetime, timedelta
import json
from collections import defaultdict
from bot_state import BotState
from config import ANNOUNCEMENTS_CHANNEL_ID
from constants import NFL_SCHEDULE_FILE
from config import (
    GIANTS_EMOJI_ID,
    JETS_EMOJI_ID,
    BILLS_EMOJI_ID,
    PATRIOTS_EMOJI_ID,
    DOLPHINS_EMOJI_ID,
    RAVENS_EMOJI_ID,
    BENGALS_EMOJI_ID,
    BROWNS_EMOJI_ID,
    STEELERS_EMOJI_ID,
    TITANS_EMOJI_ID,
    COLTS_EMOJI_ID,
    TEXANS_EMOJI_ID,
    JAGUARS_EMOJI_ID,
    CHIEFS_EMOJI_ID,
    BRONCOS_EMOJI_ID,
    CHARGERS_EMOJI_ID,
    RAIDERS_EMOJI_ID,
    EAGLES_EMOJI_ID,
    COWBOYS_EMOJI_ID,
    COMMANDERS_EMOJI_ID,
    PACKERS_EMOJI_ID,
    BEARS_EMOJI_ID,
    VIKINGS_EMOJI_ID,
    LIONS_EMOJI_ID,
    FALCONS_EMOJI_ID,
    SAINTS_EMOJI_ID,
    BUCCANEERS_EMOJI_ID,
    PANTHERS_EMOJI_ID,
    NINERS_EMOJI_ID,
    SEAHAWKS_EMOJI_ID,
    RAMS_EMOJI_ID,
    CARDINALS_EMOJI_ID
)

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

class NFLService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def _parse_est_date(self, iso_str: str) -> datetime:
        # kickoff_est looks like "2025-09-04T20:20:00-04:00"
        return datetime.fromisoformat(iso_str)

    def _games_date_span(self, weeks_dict: dict[str, list[dict]]) -> dict[int, tuple[datetime, datetime]]:
        """Return {week: (min_dt, max_dt)} using kickoff_est datetimes in EST."""
        spans = {}
        for wk_str, games in weeks_dict.items():
            times = []
            for g in games or []:
                k = g.get("kickoff_est")
                if k:
                    try:
                        times.append(self._parse_est_date(k))
                    except Exception:
                        continue
            if times:
                spans[int(wk_str)] = (min(times), max(times))
        return spans

    def _current_effective_dt(self) -> datetime:
        eastern = timezone("America/New_York")
        now = datetime.now(eastern)
        weekday = now.weekday()
        if weekday == 0:  # Monday => still consider as Sunday night for "current week"
            return now - timedelta(days=1)
        if weekday == 1 and now.hour < 5:  # early Tuesday => still prior week
            return now - timedelta(days=2)
        return now

    def get_current_nfl_week_num(self, nfl_schedule: dict) -> int | None:
        weeks = nfl_schedule.get("weeks") or {}
        if not isinstance(weeks, dict) or not weeks:
            return None

        spans = self._games_date_span(weeks)
        if not spans:
            return None

        eff = self._current_effective_dt().date()

        for wk in sorted(spans):
            start_dt, end_dt = spans[wk]
            if (start_dt.date() - timedelta(days=3)) <= eff <= end_dt.date():
                logger.info(f"Current effective date {eff} falls in week {wk} span {start_dt.date()}–{end_dt.date()}")
                return wk
        
        for wk in sorted(spans):
            if eff <= spans[wk][1].date():
                logger.info(f"Choosing next upcoming week {wk} for date {eff}")
                return wk
        last_wk = max(spans)
        logger.info(f"After last scheduled game window; defaulting to week {last_wk}")
        return last_wk

    def _group_new_games_by_date(self, week_games: list[dict]) -> dict[str, list[dict]]:
        """Group new-format games (with kickoff_est) by YYYY-MM-DD in EST."""
        by_date: dict[str, list[dict]] = defaultdict(list)
        for g in week_games:
            k = g.get("kickoff_est")
            if not k:
                continue
            try:
                dt = self._parse_est_date(k)
            except Exception:
                continue
            by_date[dt.date().isoformat()].append(g)
        return by_date

    async def post_schedule_current_week(self):
        try:
            eastern = timezone('America/New_York')
            now = datetime.now(eastern)
            # now = eastern.localize(datetime(2025, 9, 1, 0, 0, 0))  # Sept 1, 2025 at 12:00 AM ET # for testing

            try:
                with open(NFL_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"Loaded schedule file: {NFL_SCHEDULE_FILE}")
            except Exception as e:
                logger.error(f"Failed to load schedule JSON: {e}")
                return

            weeks: dict = data.get("weeks", {})
            byes_map: dict = data.get("byes", {}) or {}

            # compute season bounds for skip check (min/max kickoff_est)
            all_times = []
            for wk, games in weeks.items():
                for g in games or []:
                    k = g.get("kickoff_est")
                    if k:
                        try:
                            all_times.append(self._parse_est_date(k))
                        except Exception:
                            pass
            if not all_times:
                logger.info("No games found in schedule; skipping.")
                return

            first_game_date = min(all_times).date()
            last_game_date = max(all_times).date()
            today = now.date()

            if not ((first_game_date - timedelta(days=3)) <= today <= last_game_date):
                logger.info(f"Today {today} is outside the regular season ({first_game_date} to {last_game_date}). Skipping.")
                return

            current_week = self.get_current_nfl_week_num(data)
            if current_week is None:
                logger.info("Could not determine current NFL week from schedule; skipping.")
                return

            week_key = str(current_week)
            week_games = weeks.get(week_key, [])
            bye_teams = byes_map.get(week_key) or []
            await self.post_schedule(current_week, week_games, bye_teams)
        except Exception as e:
            logger.error(f"Failed to post NFL schedule for current week: {e}")

    async def post_schedule(self, week, games, bye_teams):
        try:
            logger.info("Posting NFL schedule")
            games_by_date = self._group_new_games_by_date(games)

            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                logger.warning("Channel not found")
                return

            # Top-level embed
            week_embed = discord.Embed(
                title=f"🏈 Week {week} Games",
                color=discord.Color.gold()
            )
            week_embed.set_thumbnail(url=NFL_LOGO)
            await channel.send(embed=week_embed)

            # One embed per date
            for date in sorted(games_by_date.keys()):
                dt = datetime.strptime(date, "%Y-%m-%d")
                date_header = dt.strftime("%A, %B %d")

                date_embed = discord.Embed(
                    title=f"📅 {date_header}",
                    color=discord.Color.blue()
                )

                for g in sorted(games_by_date[date], key=lambda x: x.get("kickoff_est", "")):
                    away_team = g.get("away_team")
                    home_team = g.get("home_team")
                    away_emoji = f"<:{NFL_TEAM_LOGOS[away_team]['logo_name']}:{NFL_TEAM_LOGOS[away_team]['logo_id']}>" if away_team in NFL_TEAM_LOGOS else ""
                    home_emoji = f"<:{NFL_TEAM_LOGOS[home_team]['logo_name']}:{NFL_TEAM_LOGOS[home_team]['logo_id']}>" if home_team in NFL_TEAM_LOGOS else ""

                    # time from kickoff_est
                    try:
                        kdt = self._parse_est_date(g["kickoff_est"])
                        time_str = kdt.strftime("%I:%M %p").lstrip("0")
                    except Exception:
                        time_str = "TBD"

                    tv_list = g.get("tv_networks") or []
                    stream_list = g.get("streaming_networks") or []
                    parts = [f"🕒 {time_str}"]
                    if tv_list:
                        parts.append(f"📺 {', '.join(tv_list)}")
                    if stream_list:
                        parts.append(f"💻 {', '.join(stream_list)}")

                    game_line = (
                        f"{away_emoji} **{away_team}** at "
                        f"{home_emoji} **{home_team}**\n"
                        f"{' | '.join(parts)}"
                    )

                    location = g.get("location")
                    if location:
                        game_line += f"\n📍 {location}"

                    date_embed.add_field(name="\u200b", value=game_line, inline=False)

                await channel.send(embed=date_embed)

            if bye_teams:
                bye_embed = discord.Embed(
                    title="🛑 Teams on Bye",
                    color=discord.Color.red()
                )
                byes_with_emojis = [
                    f"<:{NFL_TEAM_LOGOS[t]['logo_name']}:{NFL_TEAM_LOGOS[t]['logo_id']}> **{t}**"
                    if t in NFL_TEAM_LOGOS else f"**{t}**"
                    for t in bye_teams
                ]
                bye_embed.description = ", ".join(byes_with_emojis)
                await channel.send(embed=bye_embed)

        except Exception as e:
            logger.error(f"Failed to post NFL schedule: {e}")

__all__ = ['NFLService']