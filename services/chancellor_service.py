from bot_state import BotState
from config import (
    ANNOUNCEMENTS_CHANNEL_ID,
    CHANCELLOR_ROLE_ID,
    HOGBOT_SERVER_ID,
    ADMIN_USER_ID
)
from constants import KEY_SUFFIX_VOICE
from logging_config import logger
import discord
from discord.ext import commands
import random
from typing import List, Tuple, Dict, Any

class ChancellorService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member):
        escaped_name = member.name.replace("_", "\\_") # If player name contains _ then need to add backslash so Discord doesn't make it italic
        return f"{escaped_name}"

    async def decide_chancellor(self): 
        try:
            this_week_time_sums = self.state.this_week_time_sums
            logger.info(f'This week time sums: {this_week_time_sums}')
            channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
            if not channel:
                logger.warning('Channel not found')
                return
            
            logger.info('Channel found')
            guild = self.bot.get_guild(HOGBOT_SERVER_ID)
            
            self.bot.time_service.reset_active_timestamps(guild)
            sorted_times = self.bot.time_service.get_sorted_times(this_week_time_sums)

            if not sorted_times:
                logger.info("No time data found for this week.")
                sorted_times = []
            else:
                sorted_times = [item for item in sorted_times if item[0].split("_", 1)[0] != str(ADMIN_USER_ID)]

            server_booster_ids = await self.get_server_boosters(guild)

            if not server_booster_ids:
                logger.info("No server boosters found for this week.")
                server_booster_ids = []
            else:
                server_booster_ids = [member_id for member_id in server_booster_ids if member_id != str(ADMIN_USER_ID)]

            # If both are empty, stop here
            if not sorted_times and not server_booster_ids:
                logger.info("No sorted times or server boosters found. Skipping roll-off.")
                return

            top_five = sorted_times[:5] if sorted_times else []
            top_five_member_ids = [key.split("_", 1)[0] for key, _ in top_five] if top_five else []

            all_member_ids = []

            for member_id in top_five_member_ids:
                all_member_ids.append({"member_id": member_id, "source": "top_five"})

                # If this same member is also a booster, add them again right after
                if member_id in server_booster_ids:
                    all_member_ids.append({"member_id": member_id, "source": "server_booster"})

            # Now add boosters that weren’t in the top_five list
            for booster_id in server_booster_ids:
                if booster_id not in top_five_member_ids:
                    all_member_ids.append({"member_id": booster_id, "source": "server_booster"})

            winner_id, history = self.roll_off(all_member_ids)

            logger.info(f'Chancellor winner ID: {winner_id}')
            logger.info(f'Roll-off history: {history}')

            await self.send_roll_results_embed(channel, winner_id, history)
            await self.appoint_chancellor(guild, winner_id)
            self.state.this_week_time_sums.clear()
        except Exception as e:
            logger.error(f"Error in decide_chancellor: {e}")

    
    def roll_off(self, all_member_ids: List[Dict[str, str]], max_roll: int = 100):
        if not all_member_ids:
            raise ValueError("No member IDs provided for roll-off.")

        history: List[List[Dict[str, Any]]] = []
        contenders = list(all_member_ids)  # copy so we don't mutate the original

        MAX_ROUNDS = 5  # safety cap

        for _ in range(MAX_ROUNDS):
            round_results: List[Dict[str, Any]] = []
            highest = 0

            # Roll for each current contender
            for contender in contenders:
                member_id = contender["member_id"]
                source = contender.get("source", "unknown")

                roll = random.randint(1, max_roll)
                round_results.append({
                    "member_id": member_id,
                    "source": source,
                    "roll": roll
                })

                if roll > highest:
                    highest = roll

            history.append(round_results)

            # Find everyone who hit the highest roll
            tied_contenders = [
                contender for contender in round_results
                if contender["roll"] == highest
            ]

            # If exactly one winner, we're done
            if len(tied_contenders) == 1:
                winner = tied_contenders[0]
                return winner, history

            # Otherwise, reroll only among tied members
            contenders = tied_contenders

        # If somehow we hit MAX_ROUNDS, just pick one of the remaining contenders
        winner = contenders[0]
        return winner, history

    async def get_server_boosters(self, guild):
        booster_role = discord.utils.get(guild.roles, name="Server Booster")
        if booster_role:
            booster_ids = [str(member.id) for member in guild.members if booster_role in member.roles]
        else:
            booster_ids = []
        return booster_ids

    async def send_roll_results_embed(
        self,
        channel: discord.TextChannel,
        winner: Dict[str, Any],
        history: List[List[Dict[str, Any]]]
    ):
        try:
            guild = channel.guild

            # ----- Resolve winner -----
            winner_member_id_str = str(winner.get("member_id"))
            try:
                winner_id_int = int(winner_member_id_str)
            except (TypeError, ValueError):
                winner_id_int = None

            winner_member = guild.get_member(winner_id_int) if winner_id_int else None
            winner_name = (
                self.get_name(winner_member)
                if winner_member
                else f"Unknown ({winner_member_id_str})"
            )
            winner_mention = winner_member.mention if winner_member else winner_name

            winner_source = winner.get("source", "unknown")
            source_note = " (Server Booster Bonus!)" if winner_source == "server_booster" else ""
            winner_line = f"Winner: **{winner_mention}**{source_note}"

            # ----- Detect "Server Booster Bonus" members -----
            # Members who had a server_booster entry in ROUND 1
            booster_ids: Set[str] = set()
            if history:
                first_round = history[0]
                for result in first_round:
                    if result.get("source") == "server_booster":
                        mid = str(result.get("member_id"))
                        booster_ids.add(mid)

            # We'll only label "(Server Booster Bonus)" once per member across the embed,
            # and only on the *server_booster* entry, not the top_five one.
            bonus_label_used: Set[str] = set()

            # ----- Build embed -----
            embed = discord.Embed(
                title="🎲 Chancellor Roll-Off Results",
                description=winner_line,
                color=discord.Color.gold()
            )

            if booster_ids:
                embed.add_field(
                    name="Bonus Info",
                    value="Players marked with `(Server Booster Bonus)` had an extra entry from being a Server Booster.",
                    inline=False
                )

            # ----- Add each round as a field -----
            for round_index, round_results in enumerate(history, start=1):
                lines: List[str] = []

                for result in round_results:
                    member_id_str = str(result.get("member_id"))
                    roll_value = result.get("roll", "?")
                    result_source = result.get("source", "unknown")

                    try:
                        member_id_int = int(member_id_str)
                    except (TypeError, ValueError):
                        member_id_int = None

                    member = guild.get_member(member_id_int) if member_id_int else None
                    if member:
                        member_name = self.get_name(member)
                    else:
                        member_name = f"Unknown ({member_id_str})"

                    # Only tag the entry that came from server_booster,
                    # and only once per member.
                    bonus_text = ""
                    if (
                        member_id_str in booster_ids
                        and result_source == "server_booster"
                        and member_id_str not in bonus_label_used
                    ):
                        bonus_text = " (Server Booster Bonus)"
                        bonus_label_used.add(member_id_str)

                    lines.append(f"• **{member_name}**{bonus_text}: rolled **{roll_value}**")

                if not lines:
                    continue

                value = "\n".join(lines)
                if len(value) > 1024:
                    value = value[:1020] + "..."

                embed.add_field(
                    name=f"Round {round_index}",
                    value=value,
                    inline=False
                )

            embed.set_footer(text="Hogbot Roll-Off • Fair, scientific, definitely not rigged")

            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in send_roll_results_embed: {e}", exc_info=True)

    async def appoint_chancellor(self, guild, member_dict: Dict[str, Any]):

        async def remove_role_for_all(guild, role):
            for member in guild.members:
                if role in member.roles:
                    await member.remove_roles(role)

        member = guild.get_member(int(member_dict["member_id"]))
        if member:
            logger.info(f'chancellor id: {CHANCELLOR_ROLE_ID}')
            chancellor = guild.get_role(CHANCELLOR_ROLE_ID)
            if chancellor is None:
                logger.info('Chancellor role not found!')
            else:
                await remove_role_for_all(guild, chancellor)
                await member.add_roles(chancellor)
                self.state.current_chancellor_id = member.id
        else:
            logger.error(f'Member with ID {member_id} not found in guild.')

    async def deprecate_chancellor(self):
        logger.info("Deprecating Chancellor role")

        guild = self.bot.get_guild(HOGBOT_SERVER_ID)
        if guild is None:
            logger.warning("Guild not found!")
            return

        chancellor = guild.get_role(CHANCELLOR_ROLE_ID)
        if chancellor is None:
            logger.warning("Chancellor role not found!")
            return

        # Remove role from all members safely
        logger.info("Chancellor role found, removing from all members")
        for member in list(chancellor.members):
            try:
                await member.remove_roles(chancellor, reason="Chancellery deprecated")
            except discord.Forbidden:
                logger.warning(f"Missing permissions to remove {chancellor.name} from {member}")
            except discord.HTTPException as e:
                logger.error(f"Failed to remove {chancellor.name} from {member}: {e}")

        # Update internal state
        self.state.current_chancellor_id = None

        # Prepare the embed
        embed = discord.Embed(
            title="",
            description=(
                "The Chancellor’s seal fades. The banners are folded. "
                "The crown set to rest. New voices rise, free and unbound, "
                "as the Hog Pen looks with clearer eyes to dawn once more."
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Thus ends the Age of the Chancellor.")
        embed.set_thumbnail(url="https://backtozero.co/cdn/shop/products/DSC_0770_18e5d7d1-3a6d-4592-ae24-7ae4ebe04451_600x.jpg?v=1673327655")  # optional decorative icon

        # Send to announcements channel
        channel = self.bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
            logger.info("Deprecation message sent to announcements channel.")
        else:
            logger.warning("Announcements channel not found!")

__all__ = ['ChancellorService']