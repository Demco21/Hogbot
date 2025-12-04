from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random
from config import RICHEST_MEMBER_ROLE_ID

class GambleService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member: discord.abc.User) -> str:
        # Escape underscores so Discord doesn't do italics
        escaped_name = member.name.replace("_", "\\_")
        return escaped_name

    async def roll(self, interaction: discord.Interaction, from_value: int = 1, to_value: int = 100):
        """Handle a /roll-style command and send a polished result embed."""
        roller_display = interaction.user.mention

        try:
            if from_value > to_value:
                error_msg = "Invalid roll range!"
                if interaction.response.is_done():
                    await interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(error_msg, ephemeral=True)
                return

            roll_result = random.randint(from_value, to_value)

            # Determine correct article ("a" or "an")
            first_digit = str(roll_result)[0]
            article = "an" if first_digit in {"8"} else "a"

            embed = discord.Embed(
                title=f"🎲 Roll From {from_value} to {to_value}",
                description=f"{roller_display} rolled {article} **{roll_result}**!",
                color=discord.Color.blurple(),
            )

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)

            logger.info(f"User {interaction.user} rolled {roll_result}")

        except Exception as e:
            logger.error("Error in roll method", exc_info=True)

            error_msg = "An error occurred while processing your roll. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    async def loan(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        """Handle loans of Hog Coins between players."""
        try:
            lender = interaction.user

            # Basic validation
            if amount <= 0:
                msg = "Loan amount must be a positive number."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            if lender.id == target.id:
                msg = "You can't loan Hog Coins to yourself."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Ensure wallets dict exists
            if not hasattr(self.state, "member_wallets"):
                self.state.member_wallets = {}

            wallets = self.state.member_wallets

            # Default starting balance (same behavior as RideTheBusService)
            if lender.id not in wallets:
                wallets[lender.id] = 1000
            if target.id not in wallets:
                wallets[target.id] = 1000

            lender_balance = wallets[lender.id]
            target_balance = wallets[target.id]

            if amount > lender_balance:
                msg = (
                    f"You don't have enough **Hog Coins** to loan that amount.\n"
                    f"Your current balance is 🪙 **{lender_balance}**."
                )
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Perform the loan
            wallets[lender.id] -= amount
            wallets[target.id] += amount

            lender_name = self.get_name(lender)
            target_name = self.get_name(target)

            msg = (
                f"✅ **Loan completed!**\n\n"
                f"You loaned 🪙 **{amount}** Hog Coins to **{target.mention}**.\n\n"
                f"**Your New Balance: 🪙 {wallets[lender.id]}**\n"
            )

            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

            target_msg = (
                f"✅ You received a loan of 🪙 **{amount}** Hog Coins from **{lender.display_name}**!\n\n"
                f"**Your New Balance: 🪙 **{wallets[target.id]}**\n"
            )
            
            await target.send(target_msg)

            logger.info(
                f"{lender} ({lender.id}) loaned {amount} Hog Coins "
                f"to {target} ({target.id}). "
                f"New balances -> lender: {wallets[lender.id]}, target: {wallets[target.id]}"
            )

        except Exception:
            logger.error("Error in loan method", exc_info=True)
            error_msg = "An error occurred while processing the loan. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    async def update_richest_member_role(self, guild: discord.Guild):
        """
        Ensure exactly one member in this guild has the richest member role:
        the one with the highest Hog Coin balance in member_wallets.
        """
        if guild is None:
            return

        loot_role = guild.get_role(RICHEST_MEMBER_ROLE_ID)
        if loot_role is None:
            logger.warning("Richest member role not found in guild %s", guild.id)
            return

        role_name = loot_role.name if loot_role else "Unknown Role"

        if not self.state.member_wallets:
            return

        # Pick the member with the highest wallet balance
        top_member_id, _ = max(
            self.state.member_wallets.items(),
            key=lambda kv: kv[1]
        )

        new_holder = guild.get_member(top_member_id)
        if new_holder is None:
            # Top wallet isn't in this guild (e.g. DMs / another guild)
            return

        # Remove richest member role from everyone else
        for member in guild.members:
            if loot_role in member.roles and member.id != top_member_id:
                try:
                    await member.remove_roles(
                        loot_role,
                        reason=f"New {role_name} crowned (highest Hog Coin balance)."
                    )
                except discord.HTTPException:
                    logger.warning(
                        f"Failed to remove {role_name} role from %s", member.id,
                        exc_info=True
                    )

        # Give richest member to the new top holder if they don't already have it
        if loot_role not in new_holder.roles:
            try:
                await new_holder.add_roles(
                    loot_role,
                    reason=f"Highest Hog Coin balance - {role_name}."
                )
            except discord.HTTPException:
                logger.warning(
                    f"Failed to add {role_name} role to %s", new_holder.id,
                    exc_info=True
                )

    async def leaderboard(self, interaction: discord.Interaction):
        """
        Show the top 10 members by Hog Coin balance in this guild.
        Also triggers a richest member role update as a safety check.
        """
        try:
            guild = interaction.guild
            if guild is None:
                msg = "This command can only be used inside a server."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Ensure wallets dict exists
            if not hasattr(self.state, "member_wallets") or not self.state.member_wallets:
                msg = "No Hog Coin data yet. Go gamble something first. 🐷"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            wallets = self.state.member_wallets

            # Sort members by balance, highest first
            sorted_wallets = sorted(
                wallets.items(),
                key=lambda kv: kv[1],
                reverse=True
            )

            lines = []
            rank = 1

            loot_role = guild.get_role(RICHEST_MEMBER_ROLE_ID)
            if loot_role is None:
                logger.warning("Richest member role not found in guild %s", guild.id)
            else:
                role_name = loot_role.name if loot_role else ""

            for user_id, balance in sorted_wallets:
                member = guild.get_member(user_id)
                if member is None:
                    # Skip users that aren't in this guild
                    continue

                # Special indicator for the #1 seed
                if rank == 1:
                    line = (
                        f"**#{rank}** 👑 {member.mention} — 🪙 **{balance}** "
                        f"*({role_name})*"
                    )
                else:
                    line = f"**#{rank}** {member.mention} — 🪙 **{balance}**"

                lines.append(line)
                rank += 1
                if rank > 10:
                    break

            if not lines:
                msg = "No eligible members with Hog Coin balances in this server yet."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            embed = discord.Embed(
                title="🏆 Hog Coin Leaderboard",
                description="Top 10 richest **high rollers** in the **HOG PEN** casino.",
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Standings",
                value="\n".join(lines),
                inline=False
            )
            embed.set_footer(text="Only members with activity in the Hog Coin economy are shown.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)

            # Safety check: make sure richest member is properly set
            try:
                await self.update_richest_member_role(guild)
            except Exception:
                logger.error("Failed to update richest member from leaderboard.", exc_info=True)

        except Exception:
            logger.error("Error in leaderboard method", exc_info=True)
            error_msg = "An error occurred while building the leaderboard. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

__all__ = ['GambleService']
