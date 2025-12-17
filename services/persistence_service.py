from datetime import datetime, timedelta
import os
import json
from bot_state import BotState
from constants import TIME_DATA_FILE
from config import HOGBOT_SERVER_ID
from logging_config import logger

class PersistenceService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def restore_data(self):
        # Function to convert "H:MM:SS" strings to timedelta
        def string_to_timedelta(time_str):
            parts = time_str.split(':')
            days = int(parts[0])
            hours = int(parts[1])
            minutes = int(parts[2])
            seconds = int(parts[3])
            return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            
        try:
            # Read data from JSON file
            filepath = TIME_DATA_FILE
            if os.path.exists(filepath):
                logger.info(f"restoring data from file {filepath}")
                with open(filepath, "r") as file:
                    data = json.load(file)

                self.state.hogbot_start_date = data.get("hogbot_start_date", datetime.today().strftime("%m/%d/%Y"))
                self.state.current_chancellor_id = data.get("current_chancellor_id")

                # Restore dictionaries from JSON file
                self.state.lifetime_sums = {
                    member: string_to_timedelta(time_spent)
                    for member, time_spent in data.get("lifetime_sums", {}).items()
                }

                self.state.this_week_time_sums = {
                    member: string_to_timedelta(time_spent)
                    for member, time_spent in data.get("this_week_time_sums", {}).items()
                }

                self.state.scoreboard_msg = data.get("scoreboard_msg", {})
                self.state.roster_messages = data.get("roster_messages", {})
                self.state.nfl_games_msgs = data.get("nfl_games_msgs", {})

                member_wallets = data.get("member_wallets", {})
                self.state.member_wallets = {
                    int(member_id): int(balance)
                    for member_id, balance in member_wallets.items()
                }
                raw_balance_history = data.get("balance_history", {})
                self.state.balance_history = {
                    int(member_id): [int(b) for b in history]
                    for member_id, history in raw_balance_history.items()
                }
                raw_color_draws = data.get("first_round_color_draws", {})
                self.state.first_round_color_draws = {
                    int(member_id): {
                        "red": int(stats.get("red", 0)),
                        "black": int(stats.get("black", 0)),
                    }
                    for member_id, stats in raw_color_draws.items()
                }
                self.state.slots_progressive_jackpot = int(
                    data.get(
                        "slots_progressive_jackpot",
                        getattr(self.state, "slots_progressive_jackpot", 100_000),
                    )
                )

                raw_wrapped = data.get("wrapped", None)
                if raw_wrapped is None:
                    self.state.wrapped = {"members": {}, "richest": {"current_member_id": None, "current_started_at_ts": None, "durations_seconds": {}}}
                else:
                    members_raw = raw_wrapped.get("members", {}) or {}
                    richest_raw = raw_wrapped.get("richest", {}) or {}

                    # convert member ids back to ints
                    members_parsed = {
                        int(member_id): stats
                        for member_id, stats in members_raw.items()
                    }

                    durations_raw = richest_raw.get("durations_seconds", {}) or {}
                    durations_parsed = {
                        int(member_id): int(seconds)
                        for member_id, seconds in durations_raw.items()
                    }

                    current_member_id = richest_raw.get("current_member_id", None)
                    current_started_at_ts = richest_raw.get("current_started_at_ts", None)

                    self.state.wrapped = {
                        "members": members_parsed,
                        "richest": {
                            "current_member_id": int(current_member_id) if current_member_id is not None else None,
                            "current_started_at_ts": float(current_started_at_ts) if current_started_at_ts is not None else None,
                            "durations_seconds": durations_parsed,
                        }
                    }
                
            else:
                logger.warning(f"file {filepath} does not exist, creating new data file")
                self.state.hogbot_start_date = datetime.today().strftime("%m/%d/%Y")
                # await self.dump_data() # too afraid to call this here as it will overwrite the file.. wait until I make a backup job
        except Exception as e:
            logger.error(f"Error in restore_data: {e}")

    async def dump_data(self, ctx=None):
        # Convert timedelta objects to a consistent string format "H:MM:SS"
        def timedelta_to_string(td):
            total_seconds = int(td.total_seconds())
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{days}:{hours:02}:{minutes:02}:{seconds:02}"

        try:
            logger.info("Dumping data to JSON file")
            if ctx is None:
                guild = self.bot.get_guild(HOGBOT_SERVER_ID)
                self.bot.time_service.reset_active_timestamps(guild)
            else:
                self.bot.time_service.reset_active_timestamps(ctx.guild)
            
            data = {
                "lifetime_sums": {member: timedelta_to_string(time_spent) for member, time_spent in self.state.lifetime_sums.items()},
                "this_week_time_sums": {member: timedelta_to_string(time_spent) for member, time_spent in self.state.this_week_time_sums.items()},
                "hogbot_start_date": self.state.hogbot_start_date,
                "current_chancellor_id": self.state.current_chancellor_id,
                "scoreboard_msg": self.state.scoreboard_msg,
                "roster_messages": self.state.roster_messages,
                "nfl_games_msgs": self.state.nfl_games_msgs,
                "member_wallets": {
                    str(member_id): balance
                    for member_id, balance in self.state.member_wallets.items()
                },
                "balance_history": {
                    str(member_id): history
                    for member_id, history in self.state.balance_history.items()
                },
                "first_round_color_draws": {
                    str(member_id): stats
                    for member_id, stats in self.state.first_round_color_draws.items()
                },
                "slots_progressive_jackpot": getattr(self.state, "slots_progressive_jackpot", 100_000),
                "wrapped": {
                    "members": {
                        str(member_id): stats
                        for member_id, stats in getattr(self.state, "wrapped", {}).get("members", {}).items()
                    },
                    "richest": {
                        "current_member_id": getattr(self.state, "wrapped", {}).get("richest", {}).get("current_member_id", None),
                        "current_started_at_ts": getattr(self.state, "wrapped", {}).get("richest", {}).get("current_started_at_ts", None),
                        "durations_seconds": {
                            str(member_id): seconds
                            for member_id, seconds in getattr(self.state, "wrapped", {}).get("richest", {}).get("durations_seconds", {}).items()
                        },
                    },
                },

            }

            with open(TIME_DATA_FILE, "w") as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            logger.error(f"Error in dump_data: {e}")

__all__ = ['PersistenceService']