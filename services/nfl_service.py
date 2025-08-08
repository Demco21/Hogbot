from logging_config import logger
from pytz import timezone
from datetime import datetime
import json
from collections import defaultdict
from bot_state import BotState
from config import ANNOUNCEMENTS_CHANNEL_ID
from constants import NFL_SCHEDULE_FILE

class NFLService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def post_schedule(self):
        try:
            logger.info(f"Posting NFL schedule")
            eastern = timezone('America/New_York')
            now = datetime.now(eastern)

            try:
                with open(NFL_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    schedule = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load NFL schedule JSON: {e}")
                return

            first_week_date = datetime.strptime(schedule.get("first_week_date"), "%Y-%m-%d").date()
            last_game_date = datetime.strptime(schedule.get("last_game_date"), "%Y-%m-%d").date()
            today = now.date()

            # Check if today is within the season's range
            if not (first_week_date <= today <= last_game_date):
                logger.info(f"Today {today} is outside the regular season ({first_week_date} to {last_game_date}). Skipping.")
                return

            current_cal_week = now.isocalendar().week
            nfl_week = next((week for week in schedule["weeks"] if week["calendar_week"] == current_cal_week), None)

            if not nfl_week:
                logger.info("No NFL games scheduled for this calendar week.")
                return

            # Group games by date
            games_by_date = defaultdict(list)
            for game in nfl_week["games"]:
                games_by_date[game["date"]].append(game)

            msg_lines = [f"**NFL Week {nfl_week['nfl_week']} Schedule:**\n"]

            # Sort the dates
            for date in sorted(games_by_date.keys()):
                dt = datetime.strptime(date, "%Y-%m-%d")
                date_header = dt.strftime("%A, %B %d")  # e.g., "Sunday, September 07"
                msg_lines.append(f"**{date_header}**")

                for game in games_by_date[date]:
                    line = f"{game['away_team']} at {game['home_team']} at {game['time_est']} on {game['network']}"
                    msg_lines.append(line)

                msg_lines.append("")  # Empty line between date blocks

            # Add byes, if any
            if nfl_week.get("byes"):
                byes = ", ".join(nfl_week["byes"])
                msg_lines.append(f"**Teams on Bye:** {byes}")

            message = "\n".join(msg_lines)

            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)

            if not channel:
                logger.warning('Channel not found')
                return
            
            logger.info('Channel found')
            await channel.send(message)
        except Exception as e:
            logger.error(f"Failed to post NFL schedule: {e}")

__all__ = ['NFLService']