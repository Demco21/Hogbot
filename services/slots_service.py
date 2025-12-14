from __future__ import annotations

import asyncio
import random
from typing import List, Tuple, Optional

import discord
from discord.ext import commands

from bot_state import BotState
from logging_config import logger
from constants import GameSource, UpdateType


class SlotsView(discord.ui.View):
    """
    Interactive view for a one-shot slot machine spin.

    Flow:
      1. Player opens /slots -> initial embed + "Crank!" button.
      2. Player presses "Crank!" once -> bet is already taken, reels animate, then final result.
      3. Optional bonus spins can be triggered manually (no extra bet) by pressing "Crank!" again.
      4. After all spins are used, the view disables itself; to play again, the player must use /slots again.
    """

    # Base symbol list
    SYMBOLS: List[Tuple[str, str]] = [
        ("🐷", "Pig"),
        ("🍒", "Cherry"),
        ("🍋", "Lemon"),
        ("🔔", "Bell"),
        ("⭐", "Star"),
        ("🍀", "Clover"),
    ]

    # Weighted symbols
    WEIGHTED_SYMBOLS: List[Tuple[str, int]] = [
        ("🐷", 1),  # rare
        ("⭐", 2),
        ("🔔", 3),
        ("🍀", 3),
        ("🍒", 4),
        ("🍋", 6),  # common
    ]

    def __init__(self, player: discord.User, bet: int, bot_state: BotState, bot):
        super().__init__(timeout=45)
        self.player = player
        self.bet = bet
        self.state = bot_state
        self.bot = bot
        self.message: Optional[discord.Message] = None

        # Spin state
        self.spun: bool = False  # True while a spin animation is in progress
        self.spin_started: bool = False  # True once at least one spin has been triggered
        self.bonus_spin_available: bool = False  # True if a free spin is unlocked
        self.bonus_spin_used: bool = False  # True once a spin is finished *and* no bonus remains

        # Pre-calc for weighted choices
        self._weighted_emojis, self._weights = zip(*self.WEIGHTED_SYMBOLS)
        self._cleanup_task = asyncio.create_task(self._auto_cleanup())

    async def _auto_cleanup(self):
        try:
            await asyncio.sleep(60)  # 2 minutes max lifetime
        except asyncio.CancelledError:
            # Round ended normally; just exit quietly
            return

        if hasattr(self.state, "active_slots"):
            self.state.active_slots.discard(self.player.id)
        self.stop()

    def _spin_symbol(self):
        """Return a symbol based on weights."""
        return random.choices(self._weighted_emojis, weights=self._weights, k=1)[0]

    async def _ensure_player(self, interaction: discord.Interaction):
        """Only allow the original player to press buttons."""
        if interaction.user.id != self.player.id:
            try:
                await interaction.response.send_message(
                    "This isn't your slot machine. Go start your own spin. 🎰",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                pass
            return False
        return True

    def _base_embed(self, description: str, *, color: discord.Color = discord.Color.blurple()):
        embed = discord.Embed(
            title="🎰 Hog Pen Slots",
            description=f"**Player:** {self.player.mention}\n\n{description}",
            color=color,
        )
        # Show bet and current balance if known
        wallets = getattr(self.state, "member_wallets", None) or {}
        balance = wallets.get(self.player.id, 0)
        embed.add_field(name="Bet", value=f"🪙 {self.bet}", inline=True)
        embed.add_field(name="Balance", value=f"🪙 {balance}", inline=True)

        jackpot = getattr(self.state, "slots_progressive_jackpot", 0)
        embed.add_field(name="Jackpot Pool", value=f"🪙 {jackpot}", inline=False)

        return embed

    def _format_reels(self, symbols: List[str]):
        # Pretty single payline
        return f"│ {symbols[0]} │ {symbols[1]} │ {symbols[2]} │"

    def _evaluate_spin(
        self,
        result: List[str],
        jackpot_amount: int,
    ):
        """
        Determine the multiplier, flavor text, bonus spin flag, and jackpot flag.

        Payout rules:
          - 🐷🐷🐷  -> x20 + Progressive Jackpot
          - ⭐⭐⭐   -> x8  + Bonus Spin
          - 🍀🍀🍀 -> x6  + Bonus Spin
          - Any other 3-of-a-kind -> x10
          - Two 🐷 anywhere -> x5
          - Any other 2-of-a-kind -> x2
          - Anything else -> 0

        Bonus spin triggers:
          - ⭐⭐⭐ or 🍀🍀🍀 (regardless of regular payout).
        """
        s1, s2, s3 = result
        symbols_set = {s1, s2, s3}

        # Count occurrences
        pig_count = sum(1 for s in result if s == "🐷")
        star_count = sum(1 for s in result if s == "⭐")
        clover_count = sum(1 for s in result if s == "🍀")

        bonus_spin = False
        jackpot_hit = False

        # Jackpot: triple pig (includes progressive pot)
        if s1 == s2 == s3 == "🐷":
            jackpot_hit = True
            text = (
                "🎉 **JACKPOT!**\n🎉 **JACKPOT!**\n🎉 **JACKPOT!**\n\n"
                "Triple **PIGS** on the line! The **Hog Gods** are pleased. 🐷🐷🐷\n"
                f"You scoop the entire pot of 🪙 **{jackpot_amount}** on top of your payout!"
            )
            return 20, text, bonus_spin, jackpot_hit

        # Bonus triple star
        if s1 == s2 == s3 == "⭐":
            bonus_spin = True
            text = (
                "🌟 **Starlit Win!**\n🌟 **Starlit Win!**\n🌟 **Starlit Win!**\n\n"
                "Triple ⭐⭐⭐ across the board.\n"
                "You earn a **bonus spin** and a solid payout."
            )
            return 8, text, bonus_spin, jackpot_hit

        # Bonus triple clover
        if s1 == s2 == s3 == "🍀":
            bonus_spin = True
            text = (
                "🍀 **Lucky Clover!**\n🍀 **Lucky Clover!**\n🍀 **Lucky Clover!**\n\n"
                "Triple clovers shimmer on the reels.\n"
                "You feel the Hog Gods smile — **bonus spin** unlocked!"
            )
            return 6, text, bonus_spin, jackpot_hit

        # Any other triple
        if len(symbols_set) == 1:
            text = (
                "💰 **Triple hit!**\n💰 **Triple hit!**\n💰 **Triple hit!**\n\n"
                "Three of a kind across the board."
            )
            return 10, text, bonus_spin, jackpot_hit

        # Two pigs anywhere
        if pig_count == 2:
            text = "✨ **Double Pig!** Two 🐷 on the reels — not bad at all."
            return 5, text, bonus_spin, jackpot_hit

        # Any other pair
        if len(symbols_set) == 2:
            text = "🥈 **That's a nice pair!** Two symbols matched. The house pays out."
            return 2, text, bonus_spin, jackpot_hit

        # Total miss
        text = "🚫 Nothing lines up. The house scoops your bet. Better luck next squeal."
        return 0, text, bonus_spin, jackpot_hit

    async def _animate_spin(
        self,
        interaction: discord.Interaction,
        final_result: List[str],
        multiplier: int,
        outcome_text: str,
        total_payout: int,
        jackpot_won: bool,
        bonus_label: Optional[str] = None,
        bonus_available: bool = False,
    ):
        """
        Animate the reels with a staggered, semi-random stop, then show the final outcome.

        Behavior:
          - Reels stop on the *true* final result while the embed is still BLUE.
          - The final (green/red) result is revealed after a random suspense delay.
          - If bonus_available is True, the Crank button is re-enabled and the
            footer tells the player they can press it again for a free spin.
        """
        if not self.message:
            # Fallback to editing via the interaction if message isn't wired
            self.message = await interaction.original_response()

        # Slightly randomized stop timing for each reel
        stop_steps = [
            random.randint(5, 7),   # first reel
            random.randint(7, 9),   # second reel
            random.randint(9, 15),  # third reel
        ]
        total_steps = max(stop_steps) + 1

        # First acknowledge the button press / further edits
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            # Already deferred/answered, fine.
            pass

        # --- Phase 1: spinning + final freeze in BLUE ---
        for step in range(total_steps):
            current_symbols: List[str] = []
            for idx in range(3):
                if step >= stop_steps[idx]:
                    current_symbols.append(final_result[idx])
                else:
                    # Random placeholder symbol while spinning
                    current_symbols.append(self._spin_symbol())

            reel_line = self._format_reels(current_symbols)

            if step >= 0 and step < 4:
                spin_msg = "_The reels are spinning... steady now......._"
                base_delay = 0.2 + (step * 0.03)
                jitter = random.uniform(-0.04, 0.04)
            elif step >= 4 and step < total_steps - 4:
                spin_msg = "_The reels are spinning... slowing down..._"
                base_delay = 0.2 + (step * 0.03)
                jitter = random.uniform(-0.04, 0.04)
            else:
                spin_msg = "_The reels are spinning... almost there....._"
                base_delay = 0.3 + (step * 0.03)
                jitter = random.uniform(-0.08, 0.08)

            desc = f"{spin_msg}\n\n{reel_line}"
            if bonus_label:
                desc = f"**{bonus_label}**\n\n" + desc

            embed = self._base_embed(desc)

            try:
                await self.message.edit(
                    embed=embed,
                    view=self,
                )
            except discord.HTTPException:
                logger.warning(
                    "Failed to edit slots message during animation.", exc_info=True
                )

            await asyncio.sleep(max(0.12, base_delay + jitter))

        # --- Phase 2: suspense delay before revealing final (green/red) result ---
        reveal_delay = random.uniform(0.1, 1.3)
        await asyncio.sleep(reveal_delay)

        # --- Phase 3: final result reveal in GREEN/RED ---
        wallets = getattr(self.state, "member_wallets", None) or {}
        balance = wallets.get(self.player.id, 0)

        color = discord.Color.green() if multiplier > 0 or jackpot_won else discord.Color.red()
        reel_line = self._format_reels(final_result)

        desc = (
            f"**Final Result:**\n{reel_line}\n\n"
            f"{outcome_text}\n\n"
            f"**Payout Multiplier:** 🪙x{multiplier}\n"
        )

        title = "🎰 Hog Pen Slots – Result"
        if bonus_label:
            title = f"🎰 Hog Pen Slots – {bonus_label.title()} Result"

        final_embed = discord.Embed(
            title=title,
            description=f"**Player:** {self.player.mention}\n\n{desc}",
            color=color,
        )
        final_embed.add_field(name="Bet", value=f"🪙 {self.bet}", inline=True)
        final_embed.add_field(name="Payout", value=f"🪙 {total_payout}", inline=True)
        final_embed.add_field(name="Balance", value=f"🪙 {balance + total_payout}", inline=True)

        jackpot_after = getattr(self.state, "slots_progressive_jackpot", 0)
        final_embed.add_field(name="Jackpot Pool", value=f"🪙 {jackpot_after}", inline=False)

        if bonus_available:
            footer_text = "🍀 Bonus unlocked! Press **Crank!** again to use your free spin."
            # Re-enable the button so the player can trigger the bonus spin
            for item in self.children:
                item.disabled = False
        else:
            footer_text = "Use /slots again to spin a new machine."

        final_embed.set_footer(text=footer_text)

        try:
            await self.message.edit(embed=final_embed, view=self)
        except discord.HTTPException:
            logger.warning(
                "Failed to edit slots message for final reveal.", exc_info=True
            )

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        # If the player already started at least one spin,
        # don't overwrite the final result – just stop the view.
        if self.spin_started:
            # clear the player's active slot lock on timeout
            if hasattr(self.state, "active_slots"):
                self.state.active_slots.discard(self.player.id)
            self.stop()
            return

        self.disable_all_items()
        if self.message:
            try:
                embed = (
                    self.message.embeds[0]
                    if self.message.embeds
                    else self._base_embed("⏰ Slot machine timed out.")
                )
                embed.set_footer(text="⏰ Slot machine timed out.")
                await self.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        # Bet is already taken at command start; timing out just means walking away.
        guild = self.message.guild if self.message else None
        if guild is not None:
            try:
                service = getattr(self.bot, "gamble_service", None)
                if service:
                    await service.update_richest_member_role(guild)
                    balance = self.state.member_wallets.get(self.player.id, 0)
                    service.add_wallet_history_entry(
                        self.player.id, 
                        balance,
                        metadata = {
                            "game_source": GameSource.SLOTS,
                            "update_type": UpdateType.BET_LOST,
                            "bet_amount": self.bet,
                            "payout_amount": 0,
                            "reason": "Slot machine timed out."
                        }
                    )
            except Exception:
                logger.error(
                    "Failed to update richest member role on slots timeout",
                    exc_info=True,
                )
        # also clear lock here
        if hasattr(self.state, "active_slots"):
            self.state.active_slots.discard(self.player.id)

        if hasattr(self, "_cleanup_task") and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self.stop()

    # ---------- UI: Crank Button ----------

    @discord.ui.button(label="🎰 Crank!", style=discord.ButtonStyle.success)
    async def crank_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._ensure_player(interaction):
            return

        # If a spin animation is currently in progress, ignore extra clicks.
        if self.spun:
            try:
                await interaction.response.send_message(
                    "The reels are already spinning. Wait for them to stop first!",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                pass
            return

        # If we've already used the main spin and there is no unused bonus spin, this machine is spent.
        if self.spin_started and (not self.bonus_spin_available or self.bonus_spin_used):
            try:
                await interaction.response.send_message(
                    "This machine is spent. Start a fresh /slots for another spin.",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                pass
            return

        # Determine whether this is the main spin or a bonus spin
        is_bonus_spin = (
            self.spin_started
            and self.bonus_spin_available
            and not self.bonus_spin_used
        )

        self.spun = True
        # Disable the button while the reels animate to prevent double-presses.
        self.disable_all_items()

        try:
            # Ensure wallet container
            wallets = getattr(self.state, "member_wallets", None)
            if wallets is None:
                self.state.member_wallets = {}
                wallets = self.state.member_wallets

            current_balance = wallets.get(self.player.id, 0)
            jackpot_amount = getattr(self.state, "slots_progressive_jackpot", 0)

            if not is_bonus_spin:
                # ---- First (paid) Spin ----
                self.spin_started = True

                final_result = [self._spin_symbol() for _ in range(3)]
                multiplier, outcome_text, bonus_spin, jackpot_hit = self._evaluate_spin(
                    final_result, jackpot_amount
                )

                total_payout = self.bet * multiplier

                # Store bonus spin state for a future button press
                self.bonus_spin_available = bonus_spin
                self.bonus_spin_used = False

                # Animate the first spin, keeping the button enabled afterward if a bonus was unlocked
                await self._animate_spin(
                    interaction,
                    final_result,
                    multiplier,
                    outcome_text,
                    total_payout,
                    jackpot_hit,
                    bonus_label=None,
                    bonus_available=self.bonus_spin_available,
                )

                # If jackpot hit, add progressive pool on top
                if jackpot_hit:
                    total_payout += jackpot_amount
                    self.state.slots_progressive_jackpot = SlotsService.JACKPOT_SEED

                # Apply payout to wallet
                if total_payout > 0:
                    new_balance = current_balance + total_payout
                    try:
                        self.bot.gamble_service.update_wallet(self.player.id, new_balance)
                        self.bot.gamble_service.add_wallet_history_entry(
                            self.player.id, 
                            new_balance,
                            metadata = {
                                "game_source": GameSource.SLOTS,
                                "update_type": UpdateType.BET_WON,
                                "bet_amount": self.bet,
                                "payout_amount": total_payout,
                                "reason": final_result
                            }
                        )
                    except Exception:
                        logger.error(
                            "Error updating wallet after slots win", exc_info=True
                        )
                else:
                    # Record the loss state in history
                    try:
                        balance = self.state.member_wallets.get(self.player.id, 0)
                        self.bot.gamble_service.add_wallet_history_entry(
                            self.player.id, 
                            balance,
                            metadata = {
                                "game_source": GameSource.SLOTS,
                                "update_type": UpdateType.BET_LOST,
                                "bet_amount": self.bet,
                                "payout_amount": 0,
                                "reason": final_result
                            }
                        )
                    except Exception:
                        logger.error(
                            "Error recording wallet history after slots loss", exc_info=True
                        )

                # Trigger richest role update after spin resolves
                try:
                    if interaction.guild is not None:
                        await self.bot.gamble_service.update_richest_member_role(
                            interaction.guild
                        )
                except Exception:
                    logger.error(
                        "Failed to update richest member role after slots spin", exc_info=True
                    )

                if self.bonus_spin_available:
                    # Allow the user to press Crank! again for the free spin
                    self.spun = False
                else:
                    # No bonus – machine is finished for this command
                    if hasattr(self.state, "active_slots"):
                        self.state.active_slots.discard(self.player.id)

                    if hasattr(self, "_cleanup_task") and not self._cleanup_task.done():
                        self._cleanup_task.cancel()
                    
                    self.stop()

            else:
                # ---- Bonus Spin (can chain) ----
                # Re-read current balance and jackpot for the bonus spin
                wallets = getattr(self.state, "member_wallets", None) or {}
                current_balance = wallets.get(self.player.id, 0)
                jackpot_amount = getattr(self.state, "slots_progressive_jackpot", 0)

                bonus_result = [self._spin_symbol() for _ in range(3)]
                b_mult, b_text, b_bonus, b_jackpot_hit = self._evaluate_spin(
                    bonus_result, jackpot_amount
                )
                bonus_total_payout = self.bet * b_mult

                # Update bonus spin state based on this bonus result
                # If we hit another triple clover/star, we get another bonus spin.
                self.bonus_spin_available = b_bonus
                self.bonus_spin_used = not b_bonus

                await self._animate_spin(
                    interaction,
                    bonus_result,
                    b_mult,
                    b_text,
                    bonus_total_payout,
                    b_jackpot_hit,
                    bonus_label="Bonus Spin",
                    bonus_available=self.bonus_spin_available,
                )

                if b_jackpot_hit:
                    bonus_total_payout += jackpot_amount
                    self.state.slots_progressive_jackpot = SlotsService.JACKPOT_SEED

                if bonus_total_payout > 0:
                    new_balance = current_balance + bonus_total_payout
                    try:
                        self.bot.gamble_service.update_wallet(self.player.id, new_balance)
                        self.bot.gamble_service.add_wallet_history_entry(
                            self.player.id, 
                            new_balance,
                            metadata = {
                                "game_source": GameSource.SLOTS,
                                "update_type": UpdateType.BET_WON,
                                "bet_amount": self.bet,
                                "payout_amount": bonus_total_payout,
                                "reason": bonus_result
                            }
                        )
                    except Exception:
                        logger.error(
                            "Error updating wallet after slots bonus win", exc_info=True
                        )
                else:
                    try:
                        balance = self.state.member_wallets.get(self.player.id, 0)
                        self.bot.gamble_service.add_wallet_history_entry(
                            self.player.id, 
                            balance,
                            metadata = {
                                "game_source": GameSource.SLOTS,
                                "update_type": UpdateType.BET_LOST,
                                "bet_amount": self.bet,
                                "payout_amount": 0,
                                "reason": bonus_result
                            }
                        )
                    except Exception:
                        logger.error(
                            "Error recording wallet history after slots bonus loss",
                            exc_info=True,
                        )

                try:
                    if interaction.guild is not None:
                        await self.bot.gamble_service.update_richest_member_role(
                            interaction.guild
                        )
                except Exception:
                    logger.error(
                        "Failed to update richest member role after slots bonus spin",
                        exc_info=True,
                    )

                if self.bonus_spin_available:
                    # Allow chaining another bonus spin
                    self.spun = False
                else:
                    # No more bonus spins – fully done
                    if hasattr(self.state, "active_slots"):
                        self.state.active_slots.discard(self.player.id)

                    if hasattr(self, "_cleanup_task") and not self._cleanup_task.done():
                        self._cleanup_task.cancel()
                    
                    self.stop()
        except Exception:
            logger.error("Unhandled error in crank_button", exc_info=True)
            await interaction.followup.send("An unexpected error occurred. Try again later.", ephemeral=True)
        finally:
            # Ensure cleanup if the view is stuck in a bad state
            if not self.bonus_spin_available or self.bonus_spin_used:
                if hasattr(self.state, "active_slots"):
                    self.state.active_slots.discard(self.player.id)


class SlotsService:
    """
    Service entrypoint for the /slots command.

    Uses the shared Hog Coin economy:
      - Deducts a configurable bet amount at the start of each spin.
      - A single 'Crank!' determines the outcome – one spin per command,
        though bonus spins may be triggered manually without extra cost.
    """

    MIN_BET = 100
    MAX_BET = 10_000
    DEFAULT_BET = 100  # default if no bet provided

    # Progressive jackpot configuration
    JACKPOT_SEED = 100_000          # base pool when empty / reset
    JACKPOT_PERCENT = 1             # 100% of each bet goes to the jackpot

    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

        # Initialize progressive jackpot if missing
        if not hasattr(self.state, "slots_progressive_jackpot"):
            self.state.slots_progressive_jackpot = self.JACKPOT_SEED

        # NEW: initialize active slots tracking
        if not hasattr(self.state, "active_slots"):
            self.state.active_slots = set()

    async def slots(self, interaction: discord.Interaction, bet: Optional[int] = None):
        """
        Entry point for the /slots command.

        Behavior:
          - Charges the player a bet amount (between MIN_BET and MAX_BET).
          - Opens a slot machine with a 'Crank!' button.
          - After the main spin (and any manual bonus spins), the view disables itself and
            the player must use /slots again for another game.
        """
        user = interaction.user

        # Ensure active_slots container exists
        if not hasattr(self.state, "active_slots"):
            self.state.active_slots = set()

        # Enforce: one active slots game per user
        if user.id in self.state.active_slots:
            msg = (
                "You already have an active slot machine running.\n"
                "Finish that game before starting a new one. 🎰"
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        # Ensure wallets dict exists and default them if needed
        if not hasattr(self.state, "member_wallets"):
            self.state.member_wallets = {}

        wallets = self.state.member_wallets
        if user.id not in wallets:
            # Same default as other games: start with 1000
            wallets[user.id] = 1000
            try:
                self.bot.gamble_service.update_wallet(user.id, wallets[user.id])
                self.bot.gamble_service.add_wallet_history_entry(
                    user.id, 
                    wallets[user.id],
                    metadata = {
                        "game_source": GameSource.SLOTS,
                        "update_type": UpdateType.INIT_BALANCE,
                    }
                )
            except Exception:
                logger.error(
                    "Error initializing wallet for slots user", exc_info=True
                )

        wallet_balance = wallets[user.id]

        # Determine the bet amount
        if bet is None:
            bet_amount = self.DEFAULT_BET
        else:
            bet_amount = bet

        # Enforce min/max bet
        if bet_amount < self.MIN_BET or bet_amount > self.MAX_BET:
            msg = (
                f"Your bet must be between 🪙 **{self.MIN_BET}** and 🪙 **{self.MAX_BET}**.\n"
                f"You tried to bet 🪙 **{bet_amount}**."
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        if bet_amount <= 0:
            msg = "Something went wrong – the slot machine has an invalid bet amount."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            logger.error("SlotsService bet is non-positive.")
            return

        if wallet_balance < bet_amount:
            msg = (
                f"You're too broke to spin right now, {user.mention}.\n"
                f"Your bet is 🪙 **{bet_amount}**, but you only have 🪙 **{wallet_balance}**.\n"
                "Try /beg to scrounge up some Hog Coins."
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            # Mark this user as having an active slots game
            self.state.active_slots.add(user.id)

            # Deduct bet up front like a real machine
            new_balance = wallet_balance - bet_amount
            self.bot.gamble_service.update_wallet(user.id, new_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                user.id, 
                new_balance,
                metadata = {
                    "game_source": GameSource.SLOTS,
                    "update_type": UpdateType.BET_PLACED,
                    "bet_amount": bet_amount,
                }
            )

            # Feed a slice of every bet into the progressive jackpot
            try:
                contrib = max(int(bet_amount * self.JACKPOT_PERCENT), 1)
                self.state.slots_progressive_jackpot += contrib
            except Exception:
                logger.error("Error contributing to slots progressive jackpot", exc_info=True)

            view = SlotsView(user, bet_amount, self.state, self.bot)
            jackpot = getattr(self.state, "slots_progressive_jackpot", 0)
            description = (
                f"Welcome to **Hog Pen Slots**!\n"
                "Each bet is added towards the **progressive jackpot**.\n"
                "Press **Crank!** to spin the reels.\n\n"
                "**Jackpot:** 🐷🐷🐷\n"
                "**Bonus Spins:** ⭐⭐⭐ or 🍀🍀🍀"
            )
            embed = view._base_embed(description=description)
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
        except Exception:
            # If anything goes wrong starting the game, release their lock
            if hasattr(self.state, "active_slots"):
                self.state.active_slots.discard(user.id)

            logger.error("Error starting slots game", exc_info=True)
            error_msg = (
                "An error occurred while starting the slot machine. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)


__all__ = ["SlotsService"]
