import os
from dotenv import load_dotenv

load_dotenv()

ENV_TOKEN_SUFFIX = os.getenv('ENV')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN' + ENV_TOKEN_SUFFIX)
AFK_CHANNEL_ID = int(os.getenv('AFK_CHANNEL_ID'))
ANNOUNCEMENTS_CHANNEL_ID = int(os.getenv('ANNOUNCEMENTS_CHANNEL_ID'))
HOGBOT_USER_ID = int(os.getenv('HOGBOT_USER_ID'))
CHANCELLOR_ROLE_ID = int(os.getenv('CHANCELLOR_ROLE_ID'))
MOD_ROLE_ID = int(os.getenv('MOD_ROLE_ID'))
POWER_ROLE_ID = int(os.getenv('POWER_ROLE_ID'))
HOGBOT_SERVER_ID = int(os.getenv('HOGBOT_SERVER_ID'))
CHANGE_CHANNEL_ID = int(os.getenv('CHANGE_CHANNEL_ID'))