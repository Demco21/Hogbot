import discord
import logging
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get the value of the DISCORD_TOKEN variable
env_token_suffix = os.getenv('ENV')
discord_token = os.getenv('DISCORD_TOKEN' + env_token_suffix)

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
KEY_SUFFIX_VOICE = '_voice'
KEY_SUFFIX_MUTE = '_mute'
KEY_SUFFIX_DEAFEN = '_deafen'
KEY_SUFFIX_STREAM = '_stream'
AFK_CHANNEL_NAME = os.getenv('AFK_CHANNEL_NAME')

# Dictionary to store timestamps of state changes
timestamps = {}
# Dictionary to store total time spent
time_sums = {}

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):

    def handle_boolean_state_change(key_suffix, state_attr, state):
        key = f"{member.id}{key_suffix}"
        if getattr(state, state_attr) and key not in timestamps:
            timestamps[key] = datetime.now()
            logger.info(f"{member.name} {state_attr} started at {timestamps[key]}")
        elif not getattr(state, state_attr) and key in timestamps:
            start_time = timestamps.pop(key)
            time_spent = datetime.now() - start_time
            if key not in time_sums:
                time_sums[key] = timedelta()
            time_sums[key] += time_spent
            logger.info(f"{member.name} {state_attr} ended after {time_spent}")

    # Channel has changed
    if before.channel != after.channel:
        key = f"{member.id}{KEY_SUFFIX_VOICE}"
        #just connected to server in non-AFK channel, so start voice timer
        if before.channel is None and after.channel.name != AFK_CHANNEL_NAME:
            timestamps[key] = datetime.now()
            logger.info(f"{member.name} joined {after.channel.name} at {timestamps[key]}")
        #switched from AFK channel into non-AFK channel, so start voice timer
        elif before.channel is not None and before.channel.name == AFK_CHANNEL_NAME and after.channel is not None:
            timestamps[key] = datetime.now()
            logger.info(f"{member.name} joined {after.channel.name} at {timestamps[key]}")
        #disconnected from server or joined AFK channel, so stop all timers
        elif after.channel is None or after.channel.name == AFK_CHANNEL_NAME:
            if key in timestamps:
                join_time = timestamps.pop(key)
                time_spent = datetime.now() - join_time
                if key not in time_sums:
                    time_sums[key] = timedelta()
                time_sums[key] += time_spent
                logger.info(f"{member.name} left {before.channel.name} after {time_spent}")
            after.self_mute = False
            after.self_deaf = False
            after.self_stream = False
        else:
            logger.info(f"{member.name} switched from {before.channel.name} to {after.channel.name}")

    # Handle state changes
    handle_boolean_state_change(KEY_SUFFIX_MUTE, 'self_mute', after)
    handle_boolean_state_change(KEY_SUFFIX_DEAFEN, 'self_deaf', after)
    handle_boolean_state_change(KEY_SUFFIX_STREAM, 'self_stream', after)

@bot.command(name='time_spent')
async def time_spent(ctx, member: discord.Member = None):
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

@bot.command(name='most_time_spent')
async def most_time_spent(ctx, time_type: str = None):
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

    message_lines = [f"Most {time_type} time spent:"]
    for key, time_spent in sorted_times:
        member_id = key.replace(suffix, '')
        member = ctx.guild.get_member(int(member_id))
        if member:
            formatted_time = format_time_spent(time_spent)
            message_lines.append(f"{member.name}: {formatted_time}")

    await ctx.send("\n".join(message_lines))

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

# Run the bot
bot.run(discord_token)
