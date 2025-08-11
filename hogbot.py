import discord
import logging
import os
import json
import asyncio
from discord.ext import commands
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from collections import defaultdict

# Load environment variables from .env file
load_dotenv()

# Environment variables
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

# Set up bot config
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename='hogbot.log',
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
VALID_ARG_TYPES = ['voice', 'muted', 'deafened', 'streaming']
SUFFIXES = {
    VALID_ARG_TYPES[0]: KEY_SUFFIX_VOICE,
    VALID_ARG_TYPES[1]: KEY_SUFFIX_MUTE,
    VALID_ARG_TYPES[2]: KEY_SUFFIX_DEAFEN,
    VALID_ARG_TYPES[3]: KEY_SUFFIX_STREAM
}
MAX_MESSAGE_SIZE = 2000
APPROVALS_NEEDED = 2
POWER_DURATION = 60 * 15 # 15 minutes
DAY_OVERRIDES = {
    "monday": "🍺 Monday Beers",
    "tuesday": "🍺 Tuesday Beers",
    "wednesday": "🍺 Wednesday Beers",
    "thursday": "🍺 Thursday Beers",
    "friday": "🍺 Friday Beers",
    "saturday": "🍺 Saturday Beers",
    "sunday": "🍺 Sunday Beers"
}

#States
DEFAULT_STATE = 1
VOTING_STATE = 2
VOTE_APPROVED_STATE = 3

# Commands
THISWEEK_COMMAND = 'thisweek'
LIFETIME_COMMAND = 'lifetime'
DUMP_COMMAND = 'dump'
POWER_COMMAND = 'power'
APPROVE_COMMAND = 'approve'

timestamps = {} # Dictionary to store timestamps of state changes
lifetime_sums = {} # Dictionary to store total time spent
this_week_time_sums = {} # Dictionary to store weekly time spent
hogbot_start_date = 'some unknown date'
bot_state = DEFAULT_STATE
approvals = {}
current_chancellor_id = None

#startup function
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} at {datetime.now()}')
    scheduler.start()
    logger.info(f'Scheduler is on')
    await restore_data()

async def restore_data():
    # Function to convert "H:MM:SS" strings to timedelta
    def string_to_timedelta(time_str):
        parts = time_str.split(':')
        days = int(parts[0])
        hours = int(parts[1])
        minutes = int(parts[2])
        seconds = int(parts[3])
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        
    try:
        global lifetime_sums, this_week_time_sums, current_chancellor_id
        # Read data from JSON file
        filepath = "time_data.json"
        if os.path.exists(filepath):
            logger.info(f"restoring date from file {filepath}")
            with open(filepath, "r") as file:
                data = json.load(file)

            global hogbot_start_date
            hogbot_start_date = data.get("hogbot_start_date", datetime.today().strftime("%m/%d/%Y"))
            current_chancellor_id = data.get("current_chancellor_id")

            # Restore dictionaries from JSON file
            lifetime_sums = {
                member: string_to_timedelta(time_spent)
                for member, time_spent in data.get("lifetime_sums", {}).items()
            }

            this_week_time_sums = {
                member: string_to_timedelta(time_spent)
                for member, time_spent in data.get("this_week_time_sums", {}).items()
            }
        else:
            logger.warning(f"file {filepath} does not exist")
    except Exception as e:
        logger.error(f"Error in restore_data: {e}")

#captures member state changes
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
                time_spent = pop_timestamp_and_calculate(key)
                logger.info(f"{member.name} left {before.channel.name} after {time_spent}")
                after.self_mute = False
                after.self_deaf = False
                after.self_stream = False
            else:
                logger.info(f"{member.name} switched from {before.channel.name} to {after.channel.name}")
                if key not in timestamps:
                    timestamps[key] = datetime.now()

        # Handle boolean state changes
        handle_boolean_state_change(KEY_SUFFIX_MUTE, 'self_mute', after)
        handle_boolean_state_change(KEY_SUFFIX_DEAFEN, 'self_deaf', after)
        handle_boolean_state_change(KEY_SUFFIX_STREAM, 'self_stream', after)

    except Exception as e:
        logger.error(f"Error in on_voice_state_update: {e}")

def pop_timestamp_and_calculate(key):
    if key in timestamps:
        join_time = timestamps.pop(key)
        time_spent = datetime.now() - join_time
        if key not in lifetime_sums:
            lifetime_sums[key] = timedelta()
        lifetime_sums[key] += time_spent
        if key not in this_week_time_sums:
            this_week_time_sums[key] = timedelta()
        this_week_time_sums[key] += time_spent
        return time_spent

@bot.command(name=DUMP_COMMAND)
async def dump_data_command(ctx):
    await dump_data(ctx)

#dump current time sums dictionary into json file for data persistence
async def dump_data(ctx=None):

    # Convert timedelta objects to a consistent string format "H:MM:SS"
    def timedelta_to_string(td):
        total_seconds = int(td.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}:{hours:02}:{minutes:02}:{seconds:02}"

    try:
        global lifetime_sums, this_week_time_sums, hogbot_start_date, current_chancellor_id
        if ctx is None:
            guild = bot.get_guild(HOGBOT_SERVER_ID)
            reset_active_timestamps(guild)
        else:
            reset_active_timestamps(ctx.guild)
        # Prepare data for JSON serialization
        data = {
            "lifetime_sums": {member: timedelta_to_string(time_spent) for member, time_spent in lifetime_sums.items()},
            "this_week_time_sums": {member: timedelta_to_string(time_spent) for member, time_spent in this_week_time_sums.items()},
            "hogbot_start_date": hogbot_start_date,
            "current_chancellor_id": current_chancellor_id
        }
        # Write data to a JSON file
        with open("time_data.json", "w") as file:
            json.dump(data, file, indent=4)
    except Exception as e:
        logger.error(f"Error in dump_data: {e}")

#message discord with time sums starting from beginning of bot creation
@bot.command(name=LIFETIME_COMMAND)
async def lifetime_spent(ctx, arg: str = ''):
    if not arg:
        arg = VALID_ARG_TYPES[0]

    if arg not in VALID_ARG_TYPES:
        member = discord.utils.get(ctx.guild.members, name=arg)
        if member is None:
            await ctx.send(f"Invalid type! Please choose from '{VALID_ARG_TYPES[0]}', '{VALID_ARG_TYPES[1]}', '{VALID_ARG_TYPES[2]}', '{VALID_ARG_TYPES[3]}' or a valid member name.")
            return
        else:
            await time_spent_member(ctx, lifetime_sums, member)
    else:
        await time_spent_all_members(ctx, lifetime_sums, arg)

#message discord with time sums starting from beginning of the week
@bot.command(name=THISWEEK_COMMAND)
async def time_spent_this_week(ctx, arg: str = ''):
    if not arg:
        arg = VALID_ARG_TYPES[0]

    if arg not in VALID_ARG_TYPES:
        member = discord.utils.get(ctx.guild.members, name=arg)
        if member is None:
            await ctx.send("Invalid type! Please choose from 'voice', 'muted', 'deafened', 'streaming' or a valid member name.")
            return
        else:
            await time_spent_member(ctx, this_week_time_sums, member)
    else:
        await time_spent_all_members(ctx, this_week_time_sums, arg)

async def time_spent_member(ctx, time_sums, member: discord.Member):
    try:
        keys = {
            'channel': f'{member.id}{KEY_SUFFIX_VOICE}',
            'mute': f'{member.id}{KEY_SUFFIX_MUTE}',
            'deafen': f'{member.id}{KEY_SUFFIX_DEAFEN}',
            'stream': f'{member.id}{KEY_SUFFIX_STREAM}'
        }

        member_name = get_name(member)
        messages = {
            'channel': f"{member_name} has spent {{time_spent}} in voice channels.",
            'mute': f"{member_name} has spent {{time_spent}} muted.",
            'deafen': f"{member_name} has spent {{time_spent}} deafened.",
            'stream': f"{member_name} has spent {{time_spent}} streaming."
        }

        if ctx.command and ctx.command.name == LIFETIME_COMMAND:
            await ctx.send(f"Since {hogbot_start_date}:")
        else:
            await ctx.send(f"This week:")

        for key_type, key in keys.items():
            time_spent = timedelta()
            if key in time_sums:
                time_spent += time_sums[key]
            if key in timestamps:
                join_time = timestamps[key]
                time_spent += datetime.now() - join_time
            formatted_time = format_time_spent(time_spent)
            await ctx.send(messages[key_type].format(time_spent=formatted_time))
    except Exception as e:
        logger.error(f'Error in time_spent: {e}')


async def time_spent_all_members(ctx, time_sums, time_type: str = ''):
    try:
        if not time_type:
            time_type = 'voice'

        if time_type not in VALID_ARG_TYPES:
            await ctx.send("Invalid type! Please choose from 'voice', 'muted', 'deafened', or 'streaming'.")
            return

        suffix = SUFFIXES[time_type]
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
        if ctx.command and ctx.command.name == LIFETIME_COMMAND:
            message_header = f"Most {time_type} time spent since {hogbot_start_date}:"

        message_lines = [message_header]
        for key, time_spent in sorted_times:
            member_id = key.replace(suffix, '')
            member = ctx.guild.get_member(int(member_id))
            if member:
                member_name = get_name(member)
                formatted_time = format_time_spent(time_spent)
                message = f"{member_name}: {formatted_time}"
                total_size = sum(len(line) for line in message_lines) + len(message) + len(message_lines)
                if (total_size < MAX_MESSAGE_SIZE):
                    message_lines.append(message)
                else:
                    logger.info(f'MAX_MESSAGE_SIZE reached: {MAX_MESSAGE_SIZE}')
                    break

        await ctx.send("\n".join(message_lines))
        return sorted_times

    except Exception as e:
        logger.error(f"Error in time_spent_all_members: {e}")

@bot.command(name=POWER_COMMAND)
async def power(ctx):
    global bot_state, approvals
    chancellor_role = ctx.guild.get_role(CHANCELLOR_ROLE_ID)
    if chancellor_role not in ctx.author.roles:
        await ctx.send(f"Only the Chancellor can request for power.")
        return
    if bot_state == VOTING_STATE:
        await ctx.send(f"Waiting for {APPROVALS_NEEDED - len(approvals)} more approvals.")
        return
    if bot_state == VOTE_APPROVED_STATE:
        await ctx.send(f"You already have been approved of your powers.")
        return
    await ctx.send(f"Your Chancellor has requested approval to expand his powers. He will need {APPROVALS_NEEDED} votes from his council to be approved.\nType **!approve** to vote in favor of this expansion of power.")
    bot_state = VOTING_STATE

@bot.command(name=APPROVE_COMMAND)
async def approve(ctx):
    global bot_state, approvals, scheduler
    chancellor_role = ctx.guild.get_role(CHANCELLOR_ROLE_ID)
    mod_role = ctx.guild.get_role(MOD_ROLE_ID)
    power_role = ctx.guild.get_role(POWER_ROLE_ID)
    if bot_state == VOTE_APPROVED_STATE:
        await ctx.send("The Chancellor has already been approved for power.")
        return
    if bot_state != VOTING_STATE:
        await ctx.send("The Chancellor has not requested an expansion of his power. Type **!power** to request.")
        return
    if chancellor_role in ctx.author.roles:
        await ctx.send(f"The Chancellor cannot approve his own request for power.")
        return
    if mod_role not in ctx.author.roles:
        await ctx.send(f"Only Moderators can approve this request.")
        return
    if approvals.get(ctx.author):
        await ctx.send(f"You have already sent your approval ({len(approvals)}/{APPROVALS_NEEDED})")
        return
    approvals[ctx.author] = 1
    await ctx.send(f"Power request approved by {ctx.author.name} ({len(approvals)}/{APPROVALS_NEEDED})")
    if len(approvals) >= APPROVALS_NEEDED:
        await approve_power(ctx)
        approvals = {}
        bot_state = VOTE_APPROVED_STATE
        await asyncio.sleep(POWER_DURATION)
        await remove_role_for_all(ctx, power_role)
        await ctx.send("Chancellor has run out of power...")
        bot_state = DEFAULT_STATE

async def approve_power(ctx):
    if not current_chancellor_id:
        await ctx.send('No Chancellor ID found.')
        return

    logger.info(f'current chancellor id: {current_chancellor_id}')
    current_chancellor = ctx.guild.get_member(current_chancellor_id)

    if current_chancellor is None:
        logger.info('Chancellor not found!')
        return

    logger.info(f'power role id: {POWER_ROLE_ID}')
    power_role = ctx.guild.get_role(POWER_ROLE_ID)

    if power_role is None:
        logger.info('Power role not found!')
        return

    await remove_role_for_all(ctx, power_role)
    await current_chancellor.add_roles(power_role)
    await ctx.send(f'The request was approved, the Chancellor will get 15 minutes of power!')


async def appoint_chancellor(ctx, member_id):
    global current_chancellor_id
    member = ctx.guild.get_member(int(member_id))
    if member:
        logger.info(f'chancellor id: {CHANCELLOR_ROLE_ID}')
        chancellor = ctx.guild.get_role(CHANCELLOR_ROLE_ID)
        if chancellor is None:
            logger.info('Chancellor role not found!')
        else:
            await remove_role_for_all(ctx, chancellor)
            await member.add_roles(chancellor)
            current_chancellor_id = member.id
            await ctx.send(f'ALL HAIL OUR NEW CHANCELLOR, {get_name(member)} !')
    else:
        await ctx.send('No Chancellor found.')

async def remove_role_for_all(ctx, role):
    for member in ctx.guild.members:
        if role in member.roles:
            await member.remove_roles(role)

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

def reset_active_timestamps(guild):
    for member in guild.members:
        key = f"{member.id}{KEY_SUFFIX_VOICE}"
        if key in timestamps:
            pop_timestamp_and_calculate(key)
            timestamps[key] = datetime.now()
        key = f"{member.id}{KEY_SUFFIX_MUTE}"
        if key in timestamps:
            pop_timestamp_and_calculate(key)
            timestamps[key] = datetime.now()
        key = f"{member.id}{KEY_SUFFIX_DEAFEN}"
        if key in timestamps:
            pop_timestamp_and_calculate(key)
            timestamps[key] = datetime.now()
        key = f"{member.id}{KEY_SUFFIX_STREAM}"
        if key in timestamps:
            pop_timestamp_and_calculate(key)
            timestamps[key] = datetime.now()

def get_name(member):
    escaped_name = member.name.replace("_", "\\_") # If player name contains _ then need to add backslash so Discord doesn't make it italic
    return f"{escaped_name}"

def clear_this_week_time_sums():
    global this_week_time_sums
    this_week_time_sums = {}

async def change_channel_name():
    try:
        channel = bot.get_channel(CHANGE_CHANNEL_ID)

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

async def decide_chancellor():
    try:
        channel = bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)

        if not channel:
            logger.warning('Channel not found')
            return
        
        logger.info('Channel found')
        ctx_message = await channel.send('A new Chancellor is to be appointed...')
        ctx = await bot.get_context(ctx_message, cls=commands.Context)
        
        reset_active_timestamps(ctx.guild)
        sorted_times = await time_spent_all_members(ctx, this_week_time_sums)
        
        if not sorted_times:
            logger.info('No sorted times found')
            return
        
        chancellor = sorted_times[0]
        chancellor_id = chancellor[0].replace(KEY_SUFFIX_VOICE, '')
        logger.info(f'Chancellor ID found, announcing winner: {chancellor_id}')
        await appoint_chancellor(ctx, chancellor_id)
        clear_this_week_time_sums()
        
    except Exception as e:
        logger.error(f"Error in end_week: {e}")

async def end_week():
    logger.info(f'Scheduler end_week kicked off at {datetime.now()}')
    await decide_chancellor()

async def end_day():
    logger.info(f"Scheduler end_day kicked of at {datetime.now()}")
    await change_channel_name()

async def persistence_sync():
    logger.info(f"Scheduler persistence_sync kicked of at {datetime.now()}")
    await dump_data()

#set up scheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(end_week, CronTrigger(day_of_week='sun', hour=0, minute=0, timezone=timezone('America/New_York')))
scheduler.add_job(every_tuesday, CronTrigger(day_of_week='tue', hour=6, minute=0, timezone=timezone('America/New_York')))
scheduler.add_job(end_day, CronTrigger(hour=0, minute=0, timezone=timezone('America/New_York')))
scheduler.add_job(persistence_sync, CronTrigger(hour='*', minute=1, timezone=timezone('America/New_York')))

# Run the bot
bot.run(DISCORD_TOKEN)
