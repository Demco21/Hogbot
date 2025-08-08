from config import CHANGE_CHANNEL_ID
from constants import DAY_OVERRIDES
import discord
from bot_state import BotState
from logging_config import logger
from datetime import datetime

class ChannelChangeService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def change_channel_name(self):
        try:
            channel = self.bot.get_channel(CHANGE_CHANNEL_ID)

            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                logger.error("Channel ID does not point to a text or voice channel.")
                return

            # Determine what to name the channel
            today = datetime.now().strftime("%A")
            new_name = DAY_OVERRIDES.get(today.lower(), f"404 Beers Not Found")

            # Rename the channel
            await channel.edit(name=new_name)
            logger.info(f"Renamed channel to: {new_name}")

        except Exception as e:
            logger.error(f"Error in change_channel_name: {e}")

__all__ = ['ChannelChangeService']