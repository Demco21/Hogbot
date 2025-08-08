from datetime import datetime, timedelta
import os
import json
from bot_state import BotState
from constants import (
    VALID_ARG_TYPES, 
    SUFFIXES, 
    MAX_MESSAGE_SIZE, 
    LIFETIME_COMMAND, 
    KEY_SUFFIX_VOICE,
    KEY_SUFFIX_DEAFEN,
    KEY_SUFFIX_MUTE,
    KEY_SUFFIX_STREAM,
    TIME_DATA_FILE,
    DAY_OVERRIDES
)
from config import (
    AFK_CHANNEL_ID,
    ANNOUNCEMENTS_CHANNEL_ID,
    CHANCELLOR_ROLE_ID,
    HOGBOT_SERVER_ID
)
from logging_config import logger
import discord
from discord.ext import commands

class TimeService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member):
            escaped_name = member.name.replace("_", "\\_") # If player name contains _ then need to add backslash so Discord doesn't make it italic
            return f"{escaped_name}"

    def pop_timestamp_and_calculate(self, key):
            timestamps = self.state.timestamps
            lifetime_sums = self.state.lifetime_sums
            this_week_time_sums = self.state.this_week_time_sums
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

    async def time_spent_all_members(self, ctx, time_sums, time_type: str = ''):
        try:
            if not time_type:
                time_type = 'voice'

            if time_type not in VALID_ARG_TYPES:
                await ctx.send("Invalid type! Please choose from 'voice', 'muted', 'deafened', or 'streaming'.")
                return

            suffix = SUFFIXES[time_type]
            filtered_time_sums = {key: value for key, value in time_sums.items() if key.endswith(suffix)}
            filtered_timestamps = {key: value for key, value in self.state.timestamps.items() if key.endswith(suffix)}

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
                message_header = f"Most {time_type} time spent since {self.state.hogbot_start_date}:"

            message_lines = [message_header]
            for key, time_spent in sorted_times:
                member_id = key.replace(suffix, '')
                member = ctx.guild.get_member(int(member_id))
                if member:
                    member_name = self.get_name(member)
                    formatted_time = self.format_time_spent(time_spent)
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

    async def time_spent_member(self, ctx, time_sums, member: discord.Member):
        try:
            keys = {
                'channel': f'{member.id}{KEY_SUFFIX_VOICE}',
                'mute': f'{member.id}{KEY_SUFFIX_MUTE}',
                'deafen': f'{member.id}{KEY_SUFFIX_DEAFEN}',
                'stream': f'{member.id}{KEY_SUFFIX_STREAM}'
            }

            member_name = self.get_name(member)
            messages = {
                'channel': f"{member_name} has spent {{time_spent}} in voice channels.",
                'mute': f"{member_name} has spent {{time_spent}} muted.",
                'deafen': f"{member_name} has spent {{time_spent}} deafened.",
                'stream': f"{member_name} has spent {{time_spent}} streaming."
            }

            if ctx.command and ctx.command.name == LIFETIME_COMMAND:
                await ctx.send(f"Since {self.state.hogbot_start_date}:")
            else:
                await ctx.send(f"This week:")

            for key_type, key in keys.items():
                time_spent = timedelta()
                if key in time_sums:
                    time_spent += time_sums[key]
                if key in self.state.timestamps:
                    join_time = self.state.timestamps[key]
                    time_spent += datetime.now() - join_time
                formatted_time = self.format_time_spent(time_spent)
                await ctx.send(messages[key_type].format(time_spent=formatted_time))
        except Exception as e:
            logger.error(f'Error in time_spent_member: {e}')

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
            else:
                logger.warning(f"file {filepath} does not exist, creating new data file")
                self.state.hogbot_start_date = datetime.today().strftime("%m/%d/%Y")
                # await self.dump_data() # too afraid to call this here as it will overwrite the file.. wait until I make a backup job
        except Exception as e:
            logger.error(f"Error in restore_data: {e}")

    def format_time_spent(self, time_spent):
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

    async def update_timestamps(self, member, before, after):
        try:
            timestamps = self.state.timestamps
            lifetime_sums = self.state.lifetime_sums
            this_week_time_sums = self.state.this_week_time_sums

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
                    time_spent = self.pop_timestamp_and_calculate(key)
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
            logger.error(f"Error in update_timestamps: {e}")

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
                self.reset_active_timestamps(guild)
            else:
                self.reset_active_timestamps(ctx.guild)
            
            data = {
                "lifetime_sums": {member: timedelta_to_string(time_spent) for member, time_spent in self.state.lifetime_sums.items()},
                "this_week_time_sums": {member: timedelta_to_string(time_spent) for member, time_spent in self.state.this_week_time_sums.items()},
                "hogbot_start_date": self.state.hogbot_start_date,
                "current_chancellor_id": self.state.current_chancellor_id
            }

            with open(TIME_DATA_FILE, "w") as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            logger.error(f"Error in dump_data: {e}")

    def reset_active_timestamps(self, guild):
        timestamps = self.state.timestamps
        for member in guild.members:
            key = f"{member.id}{KEY_SUFFIX_VOICE}"
            if key in timestamps:
                self.pop_timestamp_and_calculate(key)
                timestamps[key] = datetime.now()
            key = f"{member.id}{KEY_SUFFIX_MUTE}"
            if key in timestamps:
                self.pop_timestamp_and_calculate(key)
                timestamps[key] = datetime.now()
            key = f"{member.id}{KEY_SUFFIX_DEAFEN}"
            if key in timestamps:
                self.pop_timestamp_and_calculate(key)
                timestamps[key] = datetime.now()
            key = f"{member.id}{KEY_SUFFIX_STREAM}"
            if key in timestamps:
                self.pop_timestamp_and_calculate(key)
                timestamps[key] = datetime.now()

    async def decide_chancellor(self):

        def clear_this_week_time_sums():
                self.state.this_week_time_sums.clear()
        
        try:
            this_week_time_sums = self.state.this_week_time_sums
            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                logger.warning('Channel not found')
                return
            
            logger.info('Channel found')
            ctx_message = await channel.send('A new Chancellor is to be appointed...')
            ctx = await self.bot.get_context(ctx_message, cls=commands.Context)
            
            self.reset_active_timestamps(ctx.guild)
            sorted_times = await self.time_spent_all_members(ctx, this_week_time_sums)
            
            if not sorted_times:
                logger.info('No sorted times found')
                return
            
            chancellor = sorted_times[0]
            chancellor_id = chancellor[0].replace(KEY_SUFFIX_VOICE, '')
            logger.info(f'Chancellor ID found, announcing winner: {chancellor_id}')
            await self.appoint_chancellor(ctx, chancellor_id)
            clear_this_week_time_sums()
        except Exception as e:
            logger.error(f"Error in decide_chancellor: {e}")

    async def appoint_chancellor(self, ctx, member_id):

        async def remove_role_for_all(ctx, role):
            for member in ctx.guild.members:
                if role in member.roles:
                    await member.remove_roles(role)

        current_chancellor_id = self.state.current_chancellor_id
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
                await ctx.send(f'ALL HAIL OUR NEW CHANCELLOR, {self.get_name(member)} !')
        else:
            await ctx.send('No Chancellor found.')

__all__ = ['TimeService']