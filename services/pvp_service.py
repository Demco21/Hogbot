import discord
from logging_config import logger
from bot_state import BotState
from discord.ext import commands
from datetime import datetime, timedelta
from config import PVP_DISABLED_ROLE_ID, PVP_ENABLED_ROLE_ID, MOD_ROLE_ID, HOGBOT_SERVER_ID
import re

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
        await ctx.send(f"PVP has been disabled for {self.get_name(ctx.author)} and will be re-enabled in 1 hour.")

    async def check_reenable_pvp(self):
        try:
            now = datetime.now()
            to_reenable = []
            for member_id, disabled_time in self.state.pvp_disabled_members.items():
                if now - disabled_time >= timedelta(hours=1):
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

        def clean_channel_name(name: str) -> str:
            # remove emojis and non-word characters
            name = re.sub(r"[^\w\s]", "", name)       # removes punctuation and special symbols
            name = re.sub(r"[\u2600-\u26FF\u2700-\u27BF]+", "", name)  # extra symbol ranges
            name = name.strip().lower()
            return name

        mod_role = ctx.guild.get_role(MOD_ROLE_ID)
        if not mod_role or mod_role not in ctx.author.roles:
            return await ctx.send("Only moderators can use this command.")

        # clean / normalize user input
        channel_name = clean_channel_name(channel_arg)

        if not channel_name:
            return await ctx.send("You need to provide a channel name.")

        # find first voice channel where the cleaned input is contained in the cleaned channel name
        target_channel = None
        for vc in ctx.guild.voice_channels:
            cleaned_vc_name = clean_channel_name(vc.name)
            if channel_name in cleaned_vc_name:
                target_channel = vc
                break

        if target_channel is None:
            return await ctx.send(f"Voice channel containing '{channel_name}' not found.")

        await member.move_to(target_channel)
        await ctx.send(f"Moved {member.display_name} to `{target_channel.name}`")

__all__ = ['PVPService']