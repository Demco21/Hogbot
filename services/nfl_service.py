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

    async def post_schedule(self):
        try:
            logger.info("Posting NFL schedule")
            eastern = timezone('America/New_York')
            now = datetime.now(eastern)

            try:
                with open(NFL_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    schedule = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load NFL schedule JSON: {e}")
                return

            first_game_date = datetime.strptime(schedule.get("first_game_date"), "%Y-%m-%d").date()
            last_game_date = datetime.strptime(schedule.get("last_game_date"), "%Y-%m-%d").date()
            today = now.date()

            # Skip if outside regular season
            if not ((first_game_date - timedelta(days=3)) <= today <= last_game_date):
                logger.info(f"Today {today} is outside the regular season ({first_game_date} to {last_game_date}). Skipping.")
                return

            current_nfl_week_num = self.get_current_nfl_week_num(schedule)
            if current_nfl_week_num is None:
                return
            
            nfl_week = next((week for week in schedule["weeks"] if week["nfl_week"] == current_nfl_week_num), None)

            if not nfl_week:
                logger.info(f"No NFL week found for NFL week {current_nfl_week_num}")
                return

            # Group games by date
            games_by_date = defaultdict(list)
            for game in nfl_week["games"]:
                games_by_date[game["date"]].append(game)

            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                logger.warning("Channel not found")
                return

            # Top-level NFL Week schedule embed
            week_embed = discord.Embed(
                title=f"🏈 Week {nfl_week['nfl_week']} Games",
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

                for game in games_by_date[date]:
                    away_emoji = f"<:{NFL_TEAM_LOGOS[game['away_team']]['logo_name']}:{NFL_TEAM_LOGOS[game['away_team']]['logo_id']}>"
                    home_emoji = f"<:{NFL_TEAM_LOGOS[game['home_team']]['logo_name']}:{NFL_TEAM_LOGOS[game['home_team']]['logo_id']}>"

                    game_line = (
                        f"{away_emoji} **{game['away_team']}** at "
                        f"{home_emoji} **{game['home_team']}**\n"
                        f"🕒 {game['time_est']} | 📺 {game['network']}"
                    )

                    special_location = game.get("special_location")
                    if special_location:
                        game_line += f"\n📍 {special_location}"

                    date_embed.add_field(name="\u200b", value=game_line, inline=False)

                await channel.send(embed=date_embed)

            # Byes
            if nfl_week.get("byes"):
                bye_embed = discord.Embed(
                    title="🛑 Teams on Bye",
                    color=discord.Color.red()
                )
                byes_with_emojis = [
                    f"<:{NFL_TEAM_LOGOS[team]['logo_name']}:{NFL_TEAM_LOGOS[team]['logo_id']}> **{team}**"
                    for team in nfl_week["byes"]
                ]
                bye_embed.description = ", ".join(byes_with_emojis)
                await channel.send(embed=bye_embed)

        except Exception as e:
            logger.error(f"Failed to post NFL schedule: {e}")

    def get_current_nfl_week_num(self, schedule) -> int | None:
        """
        Reads the NFL schedule JSON file and returns the nfl_week value for the first week
        where:
            - week["year"] == current year
            - current ISO calendar week <= week["calendar_week"]
        Returns None if no matching week is found or season has ended.
        """
        eastern = timezone("America/New_York")
        now = datetime.now(eastern)
        today = now.date()

        last_game_date = datetime.strptime(schedule["last_game_date"], "%Y-%m-%d").date()
        # Skip if season has ended
        if today > last_game_date:
            return None

        weekday = now.weekday()
        if weekday == 0:  # Monday
            effective_dt = now - timedelta(days=1)
        elif weekday == 1 and now.hour < 5:  # Tuesday before 5 AM
            effective_dt = now - timedelta(days=2)
        else:
            effective_dt = now


        eff_iso = effective_dt.isocalendar()  # returns (iso_year, iso_week, iso_weekday)
        effective_year = eff_iso[0]
        effective_week = eff_iso[1]

        current_year = today.year
        current_cal_week = today.isocalendar().week

        for week in schedule.get("weeks", []):
            if week["year"] == effective_year and effective_week <= week["calendar_week"]:
                return week["nfl_week"]

        logger.info(f"No NFL week found for year {effective_year} and week {effective_week}")
        return None

__all__ = ['NFLService']