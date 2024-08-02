import discord
import logging
import os
from discord.ext import commands, tasks
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Load environment variables from .env file
load_dotenv()

# Environment variables
ENV_TOKEN_SUFFIX = os.getenv('ENV')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN' + ENV_TOKEN_SUFFIX)
AFK_CHANNEL_ID = os.getenv('AFK_CHANNEL_ID')
HOGBOT_CHANNEL_ID = int(os.getenv('HOGBOT_CHANNEL_ID'))
HOGBOT_USER_ID = int(os.getenv('HOGBOT_USER_ID'))
CHANCELLOR_ROLE_ID = int(os.getenv('CHANCELLOR_ROLE_ID'))

# Set up bot config
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename='discord.log',
    mode='a',
    maxBytes=5*1024*1024,  # 5 MB
    backupCount=2,         # Keep up to 2 backup files
    encoding='utf-8',
    delay=0
)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Constants
KEY_SUFFIX_VOICE = '_voice'
KEY_SUFFIX_MUTE = '_mute'
KEY_SUFFIX_DEAFEN = '_deafen'
KEY_SUFFIX_STREAM = '_stream'

timestamps = {} # Dictionary to store timestamps of state changes
lifetime_sums = {} # Dictionary to store total time spent
this_week_time_sums = {} # Dictionary to store weekly time spent

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} at {datetime.now()}')
    scheduler.start()
    logger.info(f'Scheduler is on')

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        def handle_boolean_state_change(key_suffix, state_attr, state):
            key = f"{member.id}{key_suffix}"
            if getattr(state, state_attr) and key not in timestamps:
                timestamps[key] = datetime.now()
                logger.info(f"{member.name} {state_attr} started at {timestamps[key]}")
            elif not getattr(state, state_attr) and key in timestamps:
                start_time = timestamps.pop(key)
                time_spent = datetime.now() - start_time
                if key not in lifetime_sums:
                    lifetime_sums[key] = timedelta()
                lifetime_sums[key] += time_spent
                if key not in this_week_time_sums:
                    this_week_time_sums[key] = timedelta()
                this_week_time_sums[key] += time_spent
                logger.info(f"{member.name} {state_attr} ended after {time_spent}")

        # Channel has changed
        if before.channel != after.channel:
            key = f"{member.id}{KEY_SUFFIX_VOICE}"
            # just connected to server in non-AFK channel, so start voice timer
            if before.channel is None and after.channel and after.channel.id != AFK_CHANNEL_ID:
                timestamps[key] = datetime.now()
                logger.info(f"{member.name} joined {after.channel.name} at {timestamps[key]}")
            # switched from AFK channel into non-AFK channel, so start voice timer
            elif before.channel and before.channel.id == AFK_CHANNEL_ID and after.channel:
                timestamps[key] = datetime.now()
                logger.info(f"{member.name} joined {after.channel.name} at {timestamps[key]}")
            # disconnected from server or joined AFK channel, so stop all timers
            elif after.channel is None or (after.channel and after.channel.id == AFK_CHANNEL_ID):
                if key in timestamps:
                    join_time = timestamps.pop(key)
                    time_spent = datetime.now() - join_time
                    if key not in lifetime_sums:
                        lifetime_sums[key] = timedelta()
                    lifetime_sums[key] += time_spent
                    if key not in this_week_time_sums:
                        this_week_time_sums[key] = timedelta()
                    this_week_time_sums[key] += time_spent
                    logger.info(f"{member.name} left {before.channel.name} after {time_spent}")
                after.self_mute = False
                after.self_deaf = False
                after.self_stream = False
            else:
                logger.info(f"{member.name} switched from {before.channel.name} to {after.channel.name}")

        # Handle boolean state changes
        handle_boolean_state_change(KEY_SUFFIX_MUTE, 'self_mute', after)
        handle_boolean_state_change(KEY_SUFFIX_DEAFEN, 'self_deaf', after)
        handle_boolean_state_change(KEY_SUFFIX_STREAM, 'self_stream', after)

    except Exception as e:
        logger.error(f"Error in on_voice_state_update: {e}")

@bot.command(name='lifetime_spent')
async def lifetime_spent(ctx, member: discord.Member = None):
    await time_spent(ctx, lifetime_sums, member)

@bot.command(name='time_spent_this_week')
async def time_spent_this_week(ctx, member: discord.Member = None):
    await time_spent(ctx, this_week_time_sums, member)

async def time_spent(ctx, time_sums, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    keys = {
        'channel': f'{member.id}{KEY_SUFFIX_VOICE}',
        'mute': f'{member.id}{KEY_SUFFIX_MUTE}',
        'deafen': f'{member.id}{KEY_SUFFIX_DEAFEN}',
        'stream': f'{member.id}{KEY_SUFFIX_STREAM}'
    }

    messages = {
        'channel': f"{member.name} has spent {{time_spent}} in voice channels.",
        'mute': f"{member.name} has spent {{time_spent}} muted.",
        'deafen': f"{member.name} has spent {{time_spent}} deafened.",
        'stream': f"{member.name} has spent {{time_spent}} streaming."
    }

    for key_type, key in keys.items():
        time_spent = timedelta()
        if key in time_sums:
            time_spent += time_sums[key]
        if key in timestamps:
            join_time = timestamps[key]
            time_spent += datetime.now() - join_time
        formatted_time = format_time_spent(time_spent)
        await ctx.send(messages[key_type].format(time_spent=formatted_time))

@bot.command(name='list_this_week')
async def list_this_week(ctx, time_type: str = None):
    await list_time_spent(ctx, this_week_time_sums, time_type)

@bot.command(name='list_lifetime')
async def list_this_week(ctx, time_type: str = None):
    await list_time_spent(ctx, lifetime_sums, time_type)

async def list_time_spent(ctx, time_sums, time_type: str = None):
    try:
        if time_type is None:
            time_type = 'voice'
        valid_types = ['voice', 'muted', 'deafened', 'streaming']
        suffixes = {
            'voice': KEY_SUFFIX_VOICE,
            'muted': KEY_SUFFIX_MUTE,
            'deafened': KEY_SUFFIX_DEAFEN,
            'streaming': KEY_SUFFIX_STREAM
        }

        if time_type not in valid_types:
            await ctx.send("Invalid type! Please choose from 'voice', 'muted', 'deafened', or 'streaming'.")
            return

        suffix = suffixes[time_type]
        filtered_time_sums = {key: value for key, value in time_sums.items() if key.endswith(suffix)}
        filtered_timestamps = {key: value for key, value in timestamps.items() if key.endswith(suffix)}

        for key, timestamp in filtered_timestamps.items():
            if key not in filtered_time_sums:
                filtered_time_sums[key] = datetime.now() - timestamp
            else:
                filtered_time_sums[key] += datetime.now() - timestamp

        sorted_times = sorted(filtered_time_sums.items(), key=lambda item: item[1], reverse=True)

        if not sorted_times:
            await ctx.send(f"No data found for {time_type}.")
            return

        message_header = f"Most {time_type} time spent this week:"
        if ctx.command and ctx.command.name == 'list_lifetime':
            message_header = f"Most {time_type} time spent for life:"

        message_lines = [message_header]
        for key, time_spent in sorted_times:
            member_id = key.replace(suffix, '')
            member = ctx.guild.get_member(int(member_id))
            if member:
                formatted_time = format_time_spent(time_spent)
                message_lines.append(f"{member.name}: {formatted_time}")

        await ctx.send("\n".join(message_lines))

        # check if called by hogbot then we know it is scheduled job and we can check the winner
        if ctx.author.id == HOGBOT_USER_ID:
            logger.info('hogbot id detected, announce winner')
            await announce_winner(ctx, sorted_times, suffix)

    except Exception as e:
        logger.error(f"Error in list_time_spent: {e}")

async def announce_winner(ctx, sorted_times, suffix):
    winner = sorted_times[0]
    key = winner[0]
    member_id = key.replace(suffix, '')
    member = ctx.guild.get_member(int(member_id))
    if member:
        logger.info(f'chancellor id: {CHANCELLOR_ROLE_ID}')
        chancellor = ctx.guild.get_role(CHANCELLOR_ROLE_ID)
        if chancellor is None:
            logger.info('Chancellor role not found!')
        elif chancellor not in member.roles:
            await member.add_roles(chancellor)
            await ctx.send(f'ALL HAIL OUR NEW CHANCELLOR, {member.name} !')
    else:
        await ctx.send('No Chancellor found.')

def format_time_spent(time_spent):
    total_seconds = int(time_spent.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    formatted_time_parts = []
    if days > 0:
        formatted_time_parts.append(f"{days} Day(s)")
    if hours > 0:
        formatted_time_parts.append(f"{hours} Hour(s)")
    if minutes > 0:
        formatted_time_parts.append(f"{minutes} Minute(s)")
    formatted_time_parts.append(f"{seconds} Second(s)")

    formatted_time = " ".join(formatted_time_parts)
    return formatted_time

async def scheduled_chancellor():
    try:
        logger.info(f'scheduler kicked off at {datetime.now()} looking for channel {HOGBOT_CHANNEL_ID}')
        channel = bot.get_channel(HOGBOT_CHANNEL_ID)
        if channel:
            logger.info('channel found')
            ctx = await bot.get_context(await channel.send('A new Chancellor is to be appointed...'), cls=commands.Context)
            await list_time_spent(ctx, this_week_time_sums)
        else:
            logger.info('channel not found')
    except Exception as e:
        logger.error(f"Error in scheduled_chancellor: {e}")

#set up scheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(scheduled_chancellor, CronTrigger(day_of_week='fri', hour=17, minute=16))

# Run the bot
bot.run(DISCORD_TOKEN)
