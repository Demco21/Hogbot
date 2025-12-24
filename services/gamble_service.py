from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random
import io
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
from config import RICHEST_MEMBER_ROLE_ID
from typing import Optional, Dict, Any
from constants import GameSource, UpdateType

class GambleService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def get_name(self, member: discord.abc.User):
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
                wallets[lender.id] = FIRST_BET_BALANCE
            if target.id not in wallets:
                wallets[target.id] = FIRST_BET_BALANCE

            lender_balance = wallets[lender.id]
            target_balance = wallets[target.id]

            if amount > lender_balance:
                msg = (
                    f"You don't have enough **Hog Coins** to loan that amount.\n"
                    f"Your current balance is 🪙 **{lender_balance:,}**."
                )
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Rate limiting: max 3 successful loans per hour per lender
            now = datetime.now(timezone.utc)

            if not hasattr(self.state, "loan_usage"):
                self.state.loan_usage = {}

            usage = self.state.loan_usage.setdefault(lender.id, [])
            logger.info(f"Loan usage for {lender.id}: {usage}")

            # Keep only timestamps within the last hour
            one_hour_ago = now - timedelta(hours=1)
            usage = [ts for ts in usage if ts > one_hour_ago]
            self.state.loan_usage[lender.id] = usage

            if len(usage) >= 3:
                oldest_relevant = min(usage)
                next_allowed = oldest_relevant + timedelta(hours=1)
                remaining = next_allowed - now
                minutes_remaining = max(1, int(remaining.total_seconds() // 60))

                msg = (
                    "⏱️ You've already made **3 loans** in the last hour.\n"
                    f"Try again in about **{minutes_remaining} minute{'s' if minutes_remaining != 1 else ''}**."
                )
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Perform the loan
            wallets[lender.id] -= amount
            wallets[target.id] += amount

            usage.append(now)
            self.state.loan_usage[lender.id] = usage

            lender_name = self.get_name(lender)
            target_name = self.get_name(target)

            msg = (
                f"✅ **Loan completed!**\n\n"
                f"You loaned 🪙 **{amount:,}** Hog Coins to **{target.mention}**.\n\n"
                f"**Your New Balance: 🪙 {wallets[lender.id]:,}**\n"
            )

            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

            target_msg = (
                f"✅ You received a loan of 🪙 **{amount:,}** Hog Coins from **{lender.display_name}**!\n\n"
                f"**Your New Balance: 🪙 **{wallets[target.id]:,}**\n"
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

        Also tracks "time as richest" in state.wrapped["richest"].
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

        try:
            self._ensure_wrapped_initialized()
            richest = self.state.wrapped["richest"]
            now_ts = datetime.now(timezone.utc).timestamp()

            current_id = richest.get("current_member_id", None)
            current_started = richest.get("current_started_at_ts", None)

            # Initialize if never set
            if current_id is None or current_started is None:
                richest["current_member_id"] = int(top_member_id)
                richest["current_started_at_ts"] = now_ts
            else:
                current_id = int(current_id)
                if current_id != int(top_member_id):
                    # close out previous
                    elapsed = max(0, int(now_ts - float(current_started)))
                    durations = richest.setdefault("durations_seconds", {})
                    durations[current_id] = int(durations.get(current_id, 0) or 0) + elapsed

                    # start new holder window
                    richest["current_member_id"] = int(top_member_id)
                    richest["current_started_at_ts"] = now_ts
        except Exception:
            logger.error("Failed to update richest duration tracker (non-fatal).", exc_info=True)

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
                    continue

                if rank == 1:
                    line = (
                        f"**#{rank}** 👑 {member.mention} — 🪙 **{balance:,}** "
                        f"*({role_name})*"
                    )
                else:
                    line = f"**#{rank}** {member.mention} — 🪙 **{balance:,}**"

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
                color=discord.Color.gold(),
            )
            embed.description = (
                "Top 10 richest **high rollers** in the **HOG PEN** casino.\n\n"
                + "\n".join(lines)
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

    async def beg(self, interaction: discord.Interaction):
        """Allows a broke player to beg for a random amount (1–50) of Hog Coins once they hit 0."""
        try:
            user = interaction.user
            if not hasattr(self.state, "member_wallets"):
                self.state.member_wallets = {}

            wallets = self.state.member_wallets

            # Default starting balance if not found
            if user.id not in wallets:
                new_balance = FIRST_BET_BALANCE
                self.update_wallet(user.id, new_balance)
                self.bot.gamble_service.add_wallet_history_entry(
                    user.id, 
                    new_balance,
                    metadata = {
                        "game_source": GameSource.BEG,
                        "update_type": UpdateType.BEG,
                    }
                )

            current_balance = wallets[user.id]

            # Only allow if user is completely broke
            if current_balance > 0:
                msg = (
                    f"🫳 {user.mention}, you're not desperate enough *yet*.\n"
                    f"You still have 🪙 **{current_balance:,}** Hog Coins."
                )
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
                return

            # Give a random amount between 1 and 50
            beg_amount = random.randint(50, 200)
            self.update_wallet(user.id, beg_amount)
            self.bot.gamble_service.add_wallet_history_entry(
                user.id, 
                beg_amount,
                metadata = {
                    "game_source": GameSource.BEG,
                    "update_type": UpdateType.BEG,
                }
            )
            new_balance = wallets[user.id]

            messages = [
                f"🤲 {user.mention} begged outside the casino... a kind stranger took pity and dropped **{beg_amount:,} Hog Coins** into your cup.",
                f"💍 {user.mention} pawned their wedding ring for **{beg_amount:,} Hog Coins**. Time to gamble it all away again!",
                f"😔 {user.mention} mumbled, *'spare some change for the slots?'* — and somehow got **{beg_amount:,} Hog Coins**.",
                f"🎰 {user.mention} swept the casino floor for coins and found **{beg_amount:,} Hog Coins** under the slot machine.",
                f"🐖 {user.mention} squealed for mercy and the Hog Gods blessed you with **{beg_amount:,} Hog Coins**. Try not to lose them in 2 minutes.",
                f"🧎 {user.mention} groveled before the casino door — **{beg_amount:,} Hog Coins** jingled into your cup. Pathetic, but effective.",
                f"🤡 {user.mention} performed a little dance for the high rollers and earned **{beg_amount:,} Hog Coins** in pity tips.",
                f"🎣 {user.mention} fished **{beg_amount:,} Hog Coins** out of the fountain. Smells like chlorine and shame.",
                f"♻️ {user.mention} recycled empty bottles behind the casino for **{beg_amount:,} Hog Coins**. Recycling *and* relapsing.",
                f"🐀 {user.mention} wrestled a rat in the alley for a dropped coin pouch. You earned **{beg_amount:,} Hog Coins**, and tetanus.",
                f"🎟️ {user.mention} sold fake concert tickets in the casino lobby for **{beg_amount:,} Hog Coins**. You’re not proud of it.",
            ]

            msg = random.choice(messages) + f"\n\n**New Balance:** 🪙 **{new_balance:,}**"

            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg)

            logger.info(
                f"{user} ({user.id}) used /beg and received {beg_amount} Hog Coins (balance: {new_balance})."
            )

        except Exception:
            logger.error("Error in beg method", exc_info=True)
            error_msg = "An error occurred while begging for Hog Coins. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    def update_wallet(
        self,
        member_id: int,
        amount: int
    ):
        """
        Update a member's wallet to a certain amount, optionally updating history.
        """
        if not hasattr(self.state, "member_wallets"):
            self.state.member_wallets = {}

        wallets = self.state.member_wallets
        old_amount = wallets.get(member_id, 0)
        difference = amount - old_amount

        wallets[member_id] = amount

    def add_wallet_history_entry(
        self,
        member_id: int,
        balance: int,
        metadata: Optional[Dict[str, Any]],
    ):
        """Add an entry to a member's balance history AND update Hog Pen Wrapped aggregates."""

        try:
            self._update_wrapped_from_event(member_id=member_id, balance=balance, metadata=metadata)
        except Exception:
            logger.error("Wrapped stats update failed (non-fatal).", exc_info=True)

        username = None
        try:
            if hasattr(self.bot, "get_user"):
                user = self.bot.get_user(member_id)
                username = user.name if user else "Unknown"
            elif hasattr(self.state, "guild") and self.state.guild:
                member = self.state.guild.get_member(member_id)
                username = member.display_name if member else "Unknown"
        except Exception:
            username = "Unknown"

        metadata = metadata or {}

        logger.info(
            "wallet history entry added: "
            f"member_name={username}, member_id={member_id}, "
            f"balance: {balance}, "
            f"game_source={getattr(metadata.get('game_source'), 'value', metadata.get('game_source', 'N/A'))}, "
            f"update_type={getattr(metadata.get('update_type'), 'value', metadata.get('update_type', 'N/A'))}, "
            f"extra={ {k:v for k,v in metadata.items() if k not in ['game_source','update_type']} if metadata else 'None' }"
        )

        if metadata.get("update_type") != UpdateType.BET_PLACED and metadata.get("update_type") != UpdateType.ROUND_WON:
            if not hasattr(self.state, "balance_history"):
                self.state.balance_history = {}

            history = self.state.balance_history.setdefault(member_id, [])
            history.append(balance)
            if len(history) > 100:
                history.pop(0)  # keep only last 100

    async def show_balance_graph(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        """Generate and display a line graph of a player's balance history."""

        def _pct(part: int, whole: int):
            if whole <= 0:
                return "0.0%"
            return f"{(part / whole) * 100:.1f}%"

        def _wl_line(wins: int, losses: int):
            total = wins + losses
            return f"W: **{wins:,}** ({_pct(wins, total)}) | L: **{losses:,}** ({_pct(losses, total)})"

        def _rtb_round1_color_stats_line(user_id: int):
            color_stats_all = getattr(self.state, "first_round_color_draws", {}) or {}
            stats = color_stats_all.get(user_id, {}) or {}

            red = int(stats.get("red", 0) or 0)
            black = int(stats.get("black", 0) or 0)
            total = red + black

            if total <= 0:
                return "Round 1 Color: _no data yet_"

            return (
                "Round 1 Color: "
                f"Red **{red:,}** ({_pct(red, total)}) • "
                f"Black **{black:,}** ({_pct(black, total)})"
            )

        def _build_wrapped_fields(user_id: int):
            """
            Returns:
            - summary_value: str | None
            - game_fields: list[tuple[str, str]]  (name, value)
            """
            wrapped = getattr(self.state, "wrapped", {}) or {}
            members = wrapped.get("members", {}) or {}
            wm = members.get(user_id)
            if not wm:
                return None, []

            hwb = int(wm.get("high_water_balance", 0) or 0)

            hb = wm.get("highest_bet", {}) or {}
            hb_amt = int(hb.get("amount", 0) or 0)
            hb_game = hb.get("game") or "N/A"

            hp = wm.get("highest_payout", {}) or {}
            hp_amt = int(hp.get("amount", 0) or 0)
            hp_game = hp.get("game") or "N/A"

            hl = wm.get("highest_loss", {}) or {}
            hl_amt = int(hl.get("amount", 0) or 0)
            hl_game = hl.get("game") or "N/A"

            beg = int(wm.get("beg_count", 0) or 0)

            if user_id in self.state.member_wallets:
                wallet_balance = self.state.member_wallets[user_id]
            else:
                wallet_balance = FIRST_BET_BALANCE
                self.update_wallet(user_id, wallet_balance)
                self.bot.gamble_service.add_wallet_history_entry(
                    user_id,
                    wallet_balance,
                    metadata={
                        "game_source": GameSource.MY_WALLET,
                        "update_type": UpdateType.INIT_BALANCE,
                    },
                )

            summary_value = "\n".join(
                [
                    f"🪙 **Current Balance** {wallet_balance:,}",
                    f"🪙 **Highest Balance:** {hwb:,}",
                    f"🎯 **Highest Bet:** {hb_amt:,} ({hb_game})",
                    f"💰 **Highest Payout:** {hp_amt:,} ({hp_game})",
                    f"💀 **Biggest Loss:** {hl_amt:,} ({hl_game})",
                    f"🙏 **Beg Count:** {beg:,}",
                ]
            )

            games = wm.get("games", {}) or {}
            slots_key = getattr(GameSource.SLOTS, "value", "slots")
            cee_lo_key = getattr(GameSource.CEE_LO, "value", "cee_lo")
            rtb_key = getattr(GameSource.RIDE_THE_BUS, "value", "ride_the_bus")
            bj_key = getattr(GameSource.BLACKJACK, "value", "blackjack")

            allowed_game_keys = {slots_key, cee_lo_key, rtb_key}

            game_fields: list[tuple[str, str]] = []

            for game_key in (slots_key, rtb_key, cee_lo_key, bj_key):
                if game_key not in games:
                    continue

                gs = games.get(game_key) or {}

                wins = int(gs.get("wins", 0) or 0)
                losses = int(gs.get("losses", 0) or 0)
                played = int(gs.get("played", 0) or 0)
                best = int(gs.get("best_win_streak", 0) or 0)
                worst = int(gs.get("worst_losing_streak", 0) or 0)

                display_name = {
                    rtb_key: "🚌 Ride the Bus",
                    slots_key: "🎰 Slots",
                    cee_lo_key: "🎲 Cee-Lo",
                    bj_key: "🃏 Blackjack",
                }.get(game_key, game_key.replace("_", " ").title())

                value_lines = [
                    f"Played: **{played:,}**",
                    _wl_line(wins, losses),
                    f"Best Win Streak: **{best:,}**",
                    f"Worst Loss Streak: **{worst:,}**",
                ]

                if game_key == slots_key:
                    bonus_spins = int(gs.get("bonus_spin", 0) or 0)
                    jackpot_hits = int(gs.get("jackpot_hit", 0) or 0)
                    value_lines.append(f"Bonus Spins: **{bonus_spins:,}**")
                    value_lines.append(f"Jackpot Hits: **{jackpot_hits:,}**")

                if game_key == rtb_key:
                    value_lines.append(_rtb_round1_color_stats_line(user_id))

                    rounds = gs.get("rounds", {}) or {}
                    for r in ("1", "2", "3", "4"):
                        rs = rounds.get(r, {}) or {}
                        rw = int(rs.get("wins", 0) or 0)
                        rl = int(rs.get("losses", 0) or 0)
                        if rw + rl > 0:
                            value_lines.append(f"↳ Round {r}: {_wl_line(rw, rl)}")

                if game_key == bj_key:
                    ddw = int(gs.get("double_down_wins", 0) or 0)
                    ddl = int(gs.get("double_down_losses", 0) or 0)
                    bjw = int(gs.get("blackjack_wins", 0) or 0)
                    value_lines.append(f"Double Downs: {_wl_line(ddw, ddl)}")
                    value_lines.append(f"Blackjacks Won: **{bjw:,}**")

                game_fields.append((display_name, "\n".join(value_lines).strip()))

            return summary_value, game_fields

        try:
            user_id = member.id

            history = (self.state.balance_history.get(user_id) or []) if hasattr(self.state, "balance_history") else []
            if not history:
                await interaction.response.send_message(
                    f"{member.mention} has no balance history yet.",
                    ephemeral=True,
                )
                return

            plt.figure(figsize=(6, 3))
            plt.plot(history, marker="o", linewidth=2)

            plt.title(f"{member.display_name}'s Hog Coin Progression")
            plt.xlabel("Round")
            plt.ylabel("Balance")
            plt.grid(True, alpha=0.3)
            plt.tight_layout()

            buffer = io.BytesIO()
            plt.savefig(buffer, format="png")
            buffer.seek(0)
            plt.close()

            file = discord.File(buffer, filename="stats.png")

            embed = discord.Embed(
                title=f"📈 {member.display_name}'s Hog Coin Stats",
                color=discord.Color.green(),
            )
            embed.set_image(url="attachment://stats.png")

            summary_value, game_fields = _build_wrapped_fields(user_id)

            if summary_value:
                embed.add_field(name="📊 Stat Summary", value=summary_value, inline=False)

            if game_fields:
                for name, value in game_fields:
                    if len(value) > 1024:
                        value = value[:1020] + "…"
                    embed.add_field(name=name, value=value, inline=False)

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.response.send_message(embed=embed, file=file)

        except Exception:
            logger.error("Error generating balance graph", exc_info=True)

            msg = "An error occurred while generating the stats graph."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    async def my_wallet(self, interaction: discord.Interaction):
        """
        Entry point for the /mywallet slash command.
        Shows the user's current Hog Coin balance.
        """
        if interaction.user.id in self.state.member_wallets:
            wallet_balance = self.state.member_wallets[interaction.user.id]
        else:
            wallet_balance = FIRST_BET_BALANCE
            self.update_wallet(interaction.user.id, wallet_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                interaction.user.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.MY_WALLET,
                    "update_type": UpdateType.INIT_BALANCE,
                }
            )

        msg = f"Your current Hog Coin balance is: 🪙 **{wallet_balance:,}**"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

        # -------------------- Hog Pen Wrapped (stats aggregation) --------------------

    def _ensure_wrapped_initialized(self):
        """
        Ensure state.wrapped exists with the structure we need.
        We store only aggregates (no event log).
        """
        if not hasattr(self.state, "wrapped") or self.state.wrapped is None:
            self.state.wrapped = {}

        wrapped = self.state.wrapped

        if "members" not in wrapped or wrapped["members"] is None:
            wrapped["members"] = {}

        if "richest" not in wrapped or wrapped["richest"] is None:
            wrapped["richest"] = {
                "current_member_id": None,
                "current_started_at_ts": None,  # epoch seconds
                "durations_seconds": {},        # member_id -> int seconds
            }

    def _wrapped_member(self, member_id: int):
        self._ensure_wrapped_initialized()
        members: Dict[int, Dict[str, Any]] = self.state.wrapped["members"]

        if member_id not in members:
            members[member_id] = {
                "high_water_balance": 0,
                "highest_bet": {"amount": 0, "game": None},
                "highest_payout": {"amount": 0, "game": None},
                "highest_loss": {"amount": 0, "game": None},
                "beg_count": 0,
                "games": {},  # game_key -> stats
            }

        return members[member_id]

    def _wrapped_game_stats(self, member: Dict[str, Any], game_key: str):
        games: Dict[str, Dict[str, Any]] = member.setdefault("games", {})

        if game_key not in games:
            games[game_key] = {
                "played": 0,
                "wins": 0,
                "losses": 0,
                "cur_win_streak": 0,
                "best_win_streak": 0,
                "worst_losing_streak": 0,

                "bonus_spin": 0,
                "jackpot_hit": 0,

                # RTB: per-round win/loss (Round 1-4)
                "rounds": {
                    "1": {"wins": 0, "losses": 0},
                    "2": {"wins": 0, "losses": 0},
                    "3": {"wins": 0, "losses": 0},
                    "4": {"wins": 0, "losses": 0},
                },

                # RTB-only
                "wins_8x": 0,
                "highest_8x_bet": 0,
                "highest_8x_payout": 0,

                # Blackjack-only
                "double_down_wins": 0,
                "double_down_losses": 0,
                "blackjack_wins": 0,

            }

        return games[game_key]

    def _update_wrapped_from_event(
        self,
        member_id: int,
        balance: int,
        metadata: Optional[Dict[str, Any]],
    ):
        """
        Called for every wallet history event.
        Uses metadata keys you already send: game_source, update_type, bet_amount, payout_amount, round.
        """
        self._ensure_wrapped_initialized()

        metadata = metadata or {}

        game_source = metadata.get("game_source")
        update_type = metadata.get("update_type")

        if game_source is None or update_type is None:
            return

        # Normalize to raw values (handles Enum instances cleanly)
        gs_val = getattr(game_source, "value", game_source)
        ut_val = getattr(update_type, "value", update_type)

        game_key = str(gs_val) if gs_val is not None else "unknown"
        update_key = str(ut_val) if ut_val is not None else "unknown"

        bet_amount = int(metadata.get("bet_amount", 0) or 0)
        payout_amount = int(metadata.get("payout_amount", 0) or 0)
        round_val = metadata.get("round", None)
        round_key = str(round_val) if round_val is not None else None

        member = self._wrapped_member(member_id)

        # Highest balance (high-water mark)
        try:
            member["high_water_balance"] = max(int(member.get("high_water_balance", 0) or 0), int(balance))
        except Exception:
            pass

        # Begs should ALWAYS count, regardless of game_source
        if update_type == UpdateType.BEG or update_key.lower() == "beg":
            member["beg_count"] = int(member.get("beg_count", 0) or 0) + 1
            return

        # Only track per-game stats for actual games
        allowed_games = {
            getattr(GameSource.RIDE_THE_BUS, "value", "ride_the_bus"),
            getattr(GameSource.SLOTS, "value", "slots"),
            getattr(GameSource.CEE_LO, "value", "cee_lo"),
            getattr(GameSource.BLACKJACK, "value", "blackjack"),
        }

        if game_key not in allowed_games:
            return

        game_stats = self._wrapped_game_stats(member, game_key)

        # ---------------- RTB per-round win/loss ----------------
        if game_key == getattr(GameSource.RIDE_THE_BUS, "value", "ride_the_bus") and round_key in {"1", "2", "3", "4"}:
            try:
                rounds = game_stats.setdefault(
                    "rounds",
                    {
                        "1": {"wins": 0, "losses": 0},
                        "2": {"wins": 0, "losses": 0},
                        "3": {"wins": 0, "losses": 0},
                        "4": {"wins": 0, "losses": 0},
                    },
                )
                if round_key not in rounds:
                    rounds[round_key] = {"wins": 0, "losses": 0}

                if update_type == UpdateType.ROUND_WON or update_key.lower() == "round_won":
                    rounds[round_key]["wins"] = int(rounds[round_key].get("wins", 0) or 0) + 1

                elif update_type == UpdateType.BET_LOST or update_key.lower() == "bet_lost":
                    rounds[round_key]["losses"] = int(rounds[round_key].get("losses", 0) or 0) + 1

                elif (update_type == UpdateType.BET_WON or update_key.lower() == "bet_won") and round_key == "4":
                    if str(metadata.get("choice", "")).lower() != "cashout":
                        rounds["4"]["wins"] = int(rounds["4"].get("wins", 0) or 0) + 1
            except Exception:
                pass
        # ---------------------------------------------------------

        if update_type == UpdateType.BET_PLACED or update_key.lower() == "bet_placed":
            game_stats["played"] = int(game_stats.get("played", 0) or 0) + 1

            hb = member.get("highest_bet", {"amount": 0, "game": None})
            if bet_amount > int(hb.get("amount", 0) or 0):
                member["highest_bet"] = {"amount": bet_amount, "game": game_key}
            return

        if update_type == UpdateType.BET_WON or update_key.lower() == "bet_won":
            game_stats["wins"] = int(game_stats.get("wins", 0) or 0) + 1

            game_stats["cur_win_streak"] = int(game_stats.get("cur_win_streak", 0) or 0) + 1
            game_stats["best_win_streak"] = max(
                int(game_stats.get("best_win_streak", 0) or 0),
                int(game_stats.get("cur_win_streak", 0) or 0),
            )
            game_stats["cur_losing_streak"] = 0

            hp = member.get("highest_payout", {"amount": 0, "game": None})
            if payout_amount > int(hp.get("amount", 0) or 0):
                member["highest_payout"] = {"amount": payout_amount, "game": game_key}

            slots_key = getattr(GameSource.SLOTS, "value", "slots")
            if game_key == slots_key:
                if bool(metadata.get("bonus_spin")):
                    game_stats["bonus_spin"] = int(game_stats.get("bonus_spin", 0) or 0) + 1
                if bool(metadata.get("jackpot_hit")):
                    game_stats["jackpot_hit"] = int(game_stats.get("jackpot_hit", 0) or 0) + 1

            if game_key == getattr(GameSource.RIDE_THE_BUS, "value", "ride_the_bus") and round_key == "4":
                game_stats["wins_8x"] = int(game_stats.get("wins_8x", 0) or 0) + 1
                game_stats["highest_8x_bet"] = max(int(game_stats.get("highest_8x_bet", 0) or 0), bet_amount)
                game_stats["highest_8x_payout"] = max(int(game_stats.get("highest_8x_payout", 0) or 0), payout_amount)

            bj_key = getattr(GameSource.BLACKJACK, "value", "blackjack")
            if game_key == bj_key:
                if bool(metadata.get("double_down")):
                    game_stats["double_down_wins"] = int(game_stats.get("double_down_wins", 0) or 0) + 1
                if bool(metadata.get("blackjack")):
                    game_stats["blackjack_wins"] = int(game_stats.get("blackjack_wins", 0) or 0) + 1

            return

        if update_type == UpdateType.BET_LOST or update_key.lower() == "bet_lost":
            game_stats["losses"] = int(game_stats.get("losses", 0) or 0) + 1

            game_stats["cur_losing_streak"] = int(game_stats.get("cur_losing_streak", 0) or 0) + 1
            game_stats["worst_losing_streak"] = max(
                int(game_stats.get("worst_losing_streak", 0) or 0),
                int(game_stats.get("cur_losing_streak", 0) or 0),
            )

            game_stats["cur_win_streak"] = 0

            hl = member.get("highest_loss", {"amount": 0, "game": None})
            if bet_amount > int(hl.get("amount", 0) or 0):
                member["highest_loss"] = {"amount": bet_amount, "game": game_key}

            bj_key = getattr(GameSource.BLACKJACK, "value", "blackjack")
            if game_key == bj_key:
                if bool(metadata.get("double_down")):
                    game_stats["double_down_losses"] = int(game_stats.get("double_down_losses", 0) or 0) + 1
            
            return

__all__ = ['GambleService']
