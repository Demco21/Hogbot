from datetime import datetime, timedelta

class BotState:
    def __init__(self):
        self.timestamps = {}
        self.lifetime_sums = {}
        self.this_week_time_sums = {}
        self.hogbot_start_date = None
        self.bot_state = 1
        self.approvals = {}
        self.current_chancellor_id = None
        self.yahoo_token = None
        self.roster_messages = {}
        self.scoreboard_msg = {}
        self.current_nfl_week = 1
        self.current_nfl_season = 2025
        self.nfl_season_started = False
        self.nfl_games_msgs = {}
        self.pvp_disabled_members = {}
        self.member_wallets = {}

    def reset_week(self):
        self.this_week_time_sums = {}

__all__ = ['BotState']