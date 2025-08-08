import discord
from discord.ext import commands
from logging_config import logger
from bot_state import BotState
from services.time_service import TimeService
from services.channel_change_service import ChannelChangeService
from services.nfl_service import NFLService
from services.chancellor_service import ChancellorService
from services.yahoo_ff_service import YahooFFService
from config import DISCORD_TOKEN
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
import asyncio

class HogBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.all())
        self.state = BotState()
        self.time_service = TimeService(self.state, self)
        self.nfl_service = NFLService(self.state, self)
        self.channel_change_service = ChannelChangeService(self.state, self)
        self.chancellor_service = ChancellorService(self.state, self)
        self.yahoo_ff_service = YahooFFService(self.state, self)

    async def setup_hook(self):
        await self.load_extension("cogs.time_cog")
        await self.load_extension("cogs.yahoo_ff_cog")

bot = HogBot()

@bot.event
async def on_ready():
    try:
        logger.info(f'Starting bot {bot.user}')
        setup_scheduler(bot)
        logger.info(f'Set up scheduler')
        await bot.time_service.restore_data()
        logger.info(f'Restored data')
    except Exception as e:
        logger.error(f"Error on startup: {e}")

def setup_scheduler(bot):
    nfl_job = bot.nfl_service.post_schedule
    change_channel_job = bot.channel_change_service.change_channel_name
    dump_data_job = bot.time_service.dump_data
    decide_chancellor_job = bot.chancellor_service.decide_chancellor

    scheduler = AsyncIOScheduler()
    scheduler.add_job(nfl_job, CronTrigger(day_of_week='tue', hour=6, minute=0, timezone=timezone('America/New_York')))
    scheduler.add_job(change_channel_job, CronTrigger(hour=0, minute=0, timezone=timezone('America/New_York')))
    scheduler.add_job(dump_data_job, CronTrigger(hour='*', minute=1, timezone=timezone('America/New_York')))
    scheduler.add_job(decide_chancellor_job, CronTrigger(day_of_week='sun', hour=0, minute=0, timezone=timezone('America/New_York')))
    scheduler.start()

@bot.command(name='decide_chancellor')
async def dump_data_command(ctx):
    await bot.chancellor_service.decide_chancellor()

@bot.command(name='channel_change')
async def dump_data_command(ctx):
    await bot.channel_change_service.change_channel_name()

bot.run(DISCORD_TOKEN)