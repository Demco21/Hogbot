import discord
import logging
from discord.ext import commands
from datetime import datetime, timedelta

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
KEY_SUFFIX_CHANNEL = '_channel'
KEY_SUFFIX_MUTE = '_mute'
KEY_SUFFIX_DEAFEN = '_deafen'
KEY_SUFFIX_STREAM = '_stream'

# Dictionary to store timestamps of state changes
timestamps = {}
# Dictionary to store total time spent
time_sums = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):

    def handle_state_change(key_suffix, state_name, before, after):
        key = f"{member.id}{key_suffix}"
        if getattr(after, state_name) and key not in timestamps:
            timestamps[key] = datetime.now()
            logger.info(f"{member.name} {state_name} at {timestamps[key]}")
        elif not getattr(after, state_name) and key in timestamps:
            start_time = timestamps.pop(key)
            time_spent = datetime.now() - start_time
            if key not in time_sums:
                time_sums[key] = timedelta()
            time_sums[key] += time_spent
            logger.info(f"{member.name} {state_name} ended after {time_spent}")

    # Channel has changed
    if before.channel != after.channel:
        key = f"{member.id}{KEY_SUFFIX_CHANNEL}"
        if before.channel is None:
            timestamps[key] = datetime.now()
            logger.info(f"{member.name} joined {after.channel.name} at {timestamps[key]}")
        elif after.channel is None:
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
    handle_state_change(KEY_SUFFIX_MUTE, 'self_mute', before, after)
    handle_state_change(KEY_SUFFIX_DEAFEN, 'self_deaf', before, after)
    handle_state_change(KEY_SUFFIX_STREAM, 'self_stream', before, after)

@bot.command(name='time_spent')
async def time_spent(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    keys = {
        'channel': f'{member.id}{KEY_SUFFIX_CHANNEL}',
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
        if key in time_sums:
            time_spent = time_sums[key]
            await ctx.send(messages[key_type].format(time_spent=time_spent))

# Run the bot
bot.run('') #add your discord secret here
