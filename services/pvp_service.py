import discord
from logging_config import logger
from bot_state import BotState
from discord.ext import commands
from datetime import datetime, timedelta
from config import PVP_DISABLED_ROLE_ID, PVP_ENABLED_ROLE_ID, MOD_ROLE_ID, HOGBOT_SERVER_ID
import re

# Matches all emoji glyphs
EMOJI_REGEX = re.compile(
    "[" 
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA70-\U0001FAFF"  # extended-A
    "]+" 
)

def remove_emojis(text: str) -> str:
    return EMOJI_REGEX.sub("", text).strip()

class PVPService:

    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member):
        escaped_name = member.display_name.replace("_", "\\_") # If player name contains _ then need to add backslash so Discord doesn't make it italic
        return f"{escaped_name}"

    async def enable_pvp(self, ctx):
        pvp_enabled_role = ctx.guild.get_role(PVP_ENABLED_ROLE_ID)
        pvp_disabled_role = ctx.guild.get_role(PVP_DISABLED_ROLE_ID)
        await ctx.author.remove_roles(pvp_disabled_role)
        await ctx.author.add_roles(pvp_enabled_role)
        await ctx.send(f"PVP has been enabled for {self.get_name(ctx.author)}.")

    async def disable_pvp(self, ctx):
        pvp_enabled_role = ctx.guild.get_role(PVP_ENABLED_ROLE_ID)
        pvp_disabled_role = ctx.guild.get_role(PVP_DISABLED_ROLE_ID)
        await ctx.author.remove_roles(pvp_enabled_role)
        await ctx.author.add_roles(pvp_disabled_role)
        self.state.pvp_disabled_members[ctx.author.id] = datetime.now()
        logger.info(f"Disabled PVP {self.state.pvp_disabled_members}")
        await ctx.send(f"PVP has been disabled for {self.get_name(ctx.author)} and will be re-enabled in 20 minutes.")

    async def check_reenable_pvp(self):
        try:
            now = datetime.now()
            to_reenable = []
            for member_id, disabled_time in self.state.pvp_disabled_members.items():
                if now - disabled_time >= timedelta(minutes=20):
                    to_reenable.append(member_id)

            for member_id in to_reenable:
                guild = self.bot.get_guild(HOGBOT_SERVER_ID)
                member = guild.get_member(member_id)
                if member:
                    pvp_enabled_role = guild.get_role(PVP_ENABLED_ROLE_ID)
                    pvp_disabled_role = guild.get_role(PVP_DISABLED_ROLE_ID)
                    mod_role = guild.get_role(MOD_ROLE_ID)
                    await member.remove_roles(pvp_disabled_role)
                    if mod_role in member.roles:
                        await member.add_roles(pvp_enabled_role)
                del self.state.pvp_disabled_members[member_id]
        except Exception as e:
            logger.error(f"Error in check_reenable_pvp: {e}")

    async def move(self, ctx, member: discord.Member, channel_arg: str):
        mod_role = ctx.guild.get_role(MOD_ROLE_ID)
        if not mod_role or mod_role not in ctx.author.roles:
            return await ctx.send("Only moderators can use this command.")

        # Clean and normalize the provided channel name
        channel_name = (
            channel_arg.strip()
            .strip('"')
            .strip("'")
            .lower()
        )

        # Look for voice channel whose name matches ignoring emojis
        channel = None
        for c in ctx.guild.voice_channels:
            cleaned = remove_emojis(c.name).lower()
            if cleaned == channel_name:
                channel = c
                break

        if channel is None:
            return await ctx.send(f"Voice channel '{channel_name}' not found.")

        # Move the member
        await member.move_to(channel)
        await ctx.send(f"Moved {member.display_name} to `{channel.name}`")

__all__ = ['PVPService']