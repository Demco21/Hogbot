from datetime import datetime, timedelta
import os
import json
from bot_state import BotState
from constants import (
    VALID_ARG_TYPES, 
    SUFFIXES, 
    LIFETIME_COMMAND, 
    KEY_SUFFIX_VOICE,
    KEY_SUFFIX_DEAFEN,
    KEY_SUFFIX_MUTE,
    KEY_SUFFIX_STREAM
)
from config import AFK_CHANNEL_ID
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

    async def time_spent_all_members(self, interaction, time_sums, time_type: str = 'voice'):
        try:
            if time_type not in VALID_ARG_TYPES:
                await interaction.response.send_message("Invalid type! Please choose from 'voice', 'muted', 'deafened', or 'streaming'.")
                return
            sorted_times = self.get_sorted_times(time_sums, time_type)
            await self.announce_time_spent_all_members(interaction, sorted_times, time_type)
        except Exception as e:
            logger.error(f"Error in time_spent_all_members: {e}")


    def get_sorted_times(self, time_sums, time_type: str = 'voice'):
        if time_type not in VALID_ARG_TYPES:
                logger.error(f"Invalid type: {time_type} Please choose from 'voice', 'muted', 'deafened', or 'streaming'.")
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
        return sorted_times

    async def announce_time_spent_all_members(self, interaction, sorted_times, time_type: str = "voice"):
        try:
            if not sorted_times:
                await interaction.response.send_message(f"No data found for {time_type}.")
                return

            # ----- Header text -----
            if interaction and interaction.command and interaction.command.name == LIFETIME_COMMAND:
                title = f"Most {time_type} time spent since {self.state.hogbot_start_date}"
            else:
                title = f"Most {time_type} time spent this week"

            type_label = time_type.capitalize()

            # ----- Build embed -----
            embed = discord.Embed(
                title=title,
                description=f"Leaderboard by {type_label} time",
                color=discord.Color.gold()
            )

            lines = []
            rank = 1
            MAX_FIELD_LEN = 1024
            current_len = 0

            for key, time_spent in sorted_times:
                # Extract member ID
                try:
                    raw_member_id = key.split("_", 1)[0]
                    member_id = int(raw_member_id)
                except (ValueError, IndexError):
                    continue

                member = interaction.guild.get_member(member_id)
                if not member:
                    continue

                member_display = member.mention
                formatted_time = self.format_time_spent(time_spent)

                # Line format: "1. demco21 - 1m 2s"
                line = f"{rank}. {member_display} - {formatted_time}"

                # Check for Discord embed 1024-char limit
                extra_len = len(line) + (1 if lines else 0)
                if current_len + extra_len > MAX_FIELD_LEN:
                    break

                lines.append(line)
                current_len += extra_len
                rank += 1

            if not lines:
                await interaction.response.send_message(f"No data found for {time_type}.")
                return

            embed.add_field(
                name="",
                value="\n".join(lines),
                inline=False
            )

            embed.set_footer(text="Hogbot activity tracker")
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in announce_time_spent_all_members: {e}", exc_info=True)

    async def time_spent_member(self, interaction, time_sums, member: discord.Member):
        try:
            # Keys for this member in your tracking dicts
            keys = {
                "channel": f"{member.id}{KEY_SUFFIX_VOICE}",
                "mute": f"{member.id}{KEY_SUFFIX_MUTE}",
                "deafen": f"{member.id}{KEY_SUFFIX_DEAFEN}",
                "stream": f"{member.id}{KEY_SUFFIX_STREAM}",
            }

            # Use mention for title and readable name for fallback
            member_display = member.mention
            member_name = self.get_name(member)

            # Human-friendly labels
            labels = {
                "channel": "Voice Channels",
                "mute": "Muted",
                "deafen": "Deafened",
                "stream": "Streaming",
            }

            # Header text based on command (weekly vs lifetime)
            if interaction and interaction.command and interaction.command.name == LIFETIME_COMMAND:
                timeframe_text = f"Since {self.state.hogbot_start_date}"
            else:
                timeframe_text = "This week"

            # ----- Build embed -----
            embed = discord.Embed(
                title=f"Time Spent {timeframe_text}",
                description=member_display,
                color=discord.Color.gold()
            )

            # Calculate time for each category and add as simple fields
            for key_type, key in keys.items():
                time_spent = timedelta()

                # Add stored total time
                if key in time_sums:
                    time_spent += time_sums[key]

                # Add active session time (if still ongoing)
                if key in self.state.timestamps:
                    join_time = self.state.timestamps[key]
                    time_spent += datetime.now() - join_time

                formatted_time = self.format_time_spent(time_spent)

                embed.add_field(
                    name="",
                    value=f"**{labels[key_type]}:** {formatted_time}",
                    inline=False
                )

            embed.set_footer(text="Hogbot activity tracker")

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error in time_spent_member: {e}", exc_info=True)

    def format_time_spent(self, time_spent):
        total_seconds = int(time_spent.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        formatted_time_parts = []
        if days > 0:
            formatted_time_parts.append(f"{days}d")
        if hours > 0:
            formatted_time_parts.append(f"{hours}hr")
        if minutes > 0:
            formatted_time_parts.append(f"{minutes}m")
        formatted_time_parts.append(f"{seconds}s")

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

__all__ = ['TimeService']