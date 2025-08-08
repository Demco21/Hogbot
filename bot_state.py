from datetime import datetime, timedelta

class BotState:
    def __init__(self):
        self.timestamps = {}
        self.lifetime_sums = {}
        self.this_week_time_sums = {}
        self.hogbot_start_date = None
        self.bot_state = 1  # DEFAULT_STATE
        self.approvals = {}
        self.current_chancellor_id = None

    def reset_week(self):
        self.this_week_time_sums = {}

__all__ = ['BotState']