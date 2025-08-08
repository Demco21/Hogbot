from bot_state import BotState
from config import (
    ANNOUNCEMENTS_CHANNEL_ID,
    CHANCELLOR_ROLE_ID
)
from constants import KEY_SUFFIX_VOICE
from logging_config import logger
import discord
from discord.ext import commands

class ChancellorService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def decide_chancellor(self): 
        try:
            this_week_time_sums = self.state.this_week_time_sums
            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                logger.warning('Channel not found')
                return
            
            logger.info('Channel found')
            ctx_message = await channel.send('A new Chancellor is to be appointed...')
            ctx = await self.bot.get_context(ctx_message, cls=commands.Context)
            
            self.bot.time_service.reset_active_timestamps(ctx.guild)
            sorted_times = await self.bot.time_service.time_spent_all_members(ctx, this_week_time_sums)
            
            if not sorted_times:
                logger.info('No sorted times found')
                return
            
            chancellor = sorted_times[0]
            chancellor_id = chancellor[0].replace(KEY_SUFFIX_VOICE, '')
            logger.info(f'Chancellor ID found, announcing winner: {chancellor_id}')
            await self.appoint_chancellor(ctx, chancellor_id)
            self.state.this_week_time_sums.clear()
        except Exception as e:
            logger.error(f"Error in decide_chancellor: {e}")

    async def appoint_chancellor(self, ctx, member_id):

        async def remove_role_for_all(ctx, role):
            for member in ctx.guild.members:
                if role in member.roles:
                    await member.remove_roles(role)

        member = ctx.guild.get_member(int(member_id))
        if member:
            logger.info(f'chancellor id: {CHANCELLOR_ROLE_ID}')
            chancellor = ctx.guild.get_role(CHANCELLOR_ROLE_ID)
            if chancellor is None:
                logger.info('Chancellor role not found!')
            else:
                await remove_role_for_all(ctx, chancellor)
                await member.add_roles(chancellor)
                self.state.current_chancellor_id = member.id
                await ctx.send(f'ALL HAIL OUR NEW CHANCELLOR, {self.bot.time_service.get_name(member)} !')
        else:
            await ctx.send('No Chancellor found.')

__all__ = ['ChancellorService']