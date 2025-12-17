from __future__ import annotations

import asyncio
import random
import time
from typing import List, Tuple, Optional

import discord
from discord.ext import commands

from bot_state import BotState
from logging_config import logger
from constants import GameSource, UpdateType


class SlotsView(discord.ui.View):
    """
    Interactive view for a one-shot slot machine spin.
    """

    SYMBOLS: List[Tuple[str, str]] = [
        ("🐷", "Hog"),
        ("🍒", "Cherry"),
        ("🍋", "Lemon"),
        ("🔔", "Bell"),
        ("⭐", "Star"),
        ("🍀", "Clover"),
    ]

    WEIGHTED_SYMBOLS: List[Tuple[str, int]] = [
        ("🐷", 1),  # rare
        ("⭐", 2),
        ("🔔", 3),
        ("🍀", 3),
        ("🍒", 4),
        ("🍋", 6),  # common
    ]

    VIEW_TIMEOUT_SECONDS = 45
    MAX_LIFETIME_SECONDS = 60
    EDIT_RETRIES = 4
    EDIT_BASE_BACKOFF = 0.35
    SPIN_WATCHDOG_THRESHOLD_SECONDS = 15  # if "spinning" longer than this, self-heal

    def __init__(self, player: discord.User, bet: int, bot_state: BotState, bot):
        super().__init__(timeout=self.VIEW_TIMEOUT_SECONDS)
        self.player = player
        self.bet = bet
        self.state = bot_state
        self.bot = bot
        self.message: Optional[discord.Message] = None

        # Spin state
        self.spun: bool = False              # True while spin animation / work is in progress
        self.spin_started: bool = False      # True once at least one spin has been triggered
        self.machine_spent: bool = False
        self.bonus_spin_available: bool = False
        self.bonus_spin_used: bool = False

        self._created_at = time.monotonic()
        self._spin_started_at: Optional[float] = None

        # True concurrency guard (prevents rare race conditions)
        self._spin_lock = asyncio.Lock()

        # Weighted choices
        self._weighted_emojis, self._weights = zip(*self.WEIGHTED_SYMBOLS)

        # Background tasks
        self._cleanup_task = asyncio.create_task(self._auto_cleanup())
        self._watchdog_task = asyncio.create_task(self._spin_watchdog())

    # -------------------- Safety helpers --------------------

    async def _safe_defer(self, interaction: discord.Interaction):
        """
        Safely ack the interaction so Discord doesn't consider it "failed".
        """
        try:
            if interaction.response.is_done():
                return
            await interaction.response.defer()
        except discord.InteractionResponded:
            return
        except Exception:
            logger.warning("Slots: failed to defer interaction", exc_info=True)

    async def _safe_ephemeral(self, interaction: discord.Interaction, msg: str):
        """
        Safely send an ephemeral message regardless of whether the interaction
        has already been responded to.
        """
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.InteractionResponded:
            try:
                await interaction.followup.send(msg, ephemeral=True)
            except Exception:
                logger.warning("Slots: failed sending followup ephemeral", exc_info=True)
        except Exception:
            logger.warning("Slots: failed sending ephemeral", exc_info=True)

    async def _ensure_message(self, interaction: discord.Interaction):
        """
        Ensure self.message is wired. If it can't be recovered, returns None.
        """
        if self.message is not None:
            return self.message

        try:
            self.message = await interaction.original_response()
            return self.message
        except Exception:
            logger.warning("Slots: could not fetch original_response to wire message", exc_info=True)
            return None

    async def _safe_edit(self, *, embed: discord.Embed, view: Optional[discord.ui.View]):
        """
        Safely edit the slot message with retries/backoff for transient Discord/API issues.
        Returns True on success, False if all retries fail.
        """
        if self.message is None:
            return False

        backoff = self.EDIT_BASE_BACKOFF
        for attempt in range(1, self.EDIT_RETRIES + 1):
            try:
                await self.message.edit(embed=embed, view=view)
                return True
            except discord.HTTPException as e:
                # discord.py often raises HTTPException for transient failures, including rate limits.
                logger.warning(
                    "Slots: message.edit failed (attempt %s/%s) status=%s",
                    attempt,
                    self.EDIT_RETRIES,
                    getattr(e, "status", "unknown"),
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff *= 1.8
            except Exception:
                logger.warning(
                    "Slots: message.edit failed (attempt %s/%s) unexpected",
                    attempt,
                    self.EDIT_RETRIES,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff *= 1.8

        return False

    def _enable_all_items(self):
        for item in self.children:
            item.disabled = False

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    # -------------------- Background tasks --------------------

    async def _auto_cleanup(self):
        """
        Stops the view after MAX_LIFETIME_SECONDS, but will not kill the view mid-spin.
        """
        try:
            while True:
                await asyncio.sleep(5)

                last_event = self._spin_started_at or self._created_at
                alive = time.monotonic() - last_event
                if alive < self.MAX_LIFETIME_SECONDS:
                    continue

                # Don't cleanup while actively spinning (avoids bricking mid-animation)
                if self.spun:
                    continue

                # Clear per-user lock, then stop view
                if hasattr(self.state, "active_slots"):
                    self.state.active_slots.discard(self.player.id)

                self.stop()
                return
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("Slots: auto cleanup task error", exc_info=True)

    async def _spin_watchdog(self):
        """
        If Discord/API issues or cancellations leave us stuck in "spun=True",
        automatically reset the view so the player isn't deadlocked.
        """
        try:
            while True:
                await asyncio.sleep(2)

                if not self.spun or self._spin_started_at is None:
                    continue

                if time.monotonic() - self._spin_started_at > self.SPIN_WATCHDOG_THRESHOLD_SECONDS:
                    logger.warning(
                        "Slots: watchdog triggered for user_id=%s; resetting stuck spinning state",
                        self.player.id,
                    )
                    self.spun = False
                    self._spin_started_at = None
                    self._enable_all_items()

                    # Best effort: update footer so user knows it recovered
                    if self.message is not None:
                        try:
                            embed = (
                                self.message.embeds[0]
                                if self.message.embeds
                                else self._base_embed("Recovered from a Discord hiccup. Press **Crank!** again.")
                            )
                            embed.set_footer(text="⚠️ Recovered from a Discord hiccup. Press **Crank!** again.")
                            await self._safe_edit(embed=embed, view=self)
                        except Exception:
                            logger.warning("Slots: watchdog failed to edit recovery message", exc_info=True)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("Slots: watchdog task error", exc_info=True)

    # -------------------- Slot logic --------------------

    def _spin_symbol(self):
        return random.choices(self._weighted_emojis, weights=self._weights, k=1)[0]

    async def _ensure_player(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await self._safe_ephemeral(
                interaction,
                "This isn't your slot machine. Go start your own spin. 🎰",
            )
            return False
        return True

    def _base_embed(self, description: str, *, color: discord.Color = discord.Color.blurple()):
        embed = discord.Embed(
            title="🎰 Hog Pen Slots",
            description=f"**Player:** {self.player.mention}\n\n{description}",
            color=color,
        )
        wallets = getattr(self.state, "member_wallets", None) or {}
        balance = wallets.get(self.player.id, 0)
        embed.add_field(name="Bet", value=f"🪙 {self.bet:,}", inline=True)
        embed.add_field(name="Balance", value=f"🪙 {balance:,}", inline=True)

        jackpot = getattr(self.state, "slots_progressive_jackpot", 0)
        embed.add_field(name="Jackpot Pool", value=f"🪙 {jackpot:,}", inline=False)
        return embed

    def _format_reels(self, symbols: List[str]):
        return f"│ {symbols[0]} │ {symbols[1]} │ {symbols[2]} │"

    def _evaluate_spin(self, result: List[str], jackpot_amount: int):
        s1, s2, s3 = result
        symbols_set = {s1, s2, s3}

        pig_count = sum(1 for s in result if s == "🐷")
        bonus_spin = False
        jackpot_hit = False

        if s1 == s2 == s3 == "🐷":
            jackpot_hit = True
            text = (
                "🎉 **JACKPOT!**\n🎉 **JACKPOT!**\n🎉 **JACKPOT!**\n\n"
                "Triple **HOGS** on the line! The **Hog Gods** are pleased. 🐷🐷🐷\n"
                f"You scoop the entire pot of 🪙 **{jackpot_amount:,}** on top of your payout!"
            )
            return 20, text, bonus_spin, jackpot_hit

        if s1 == s2 == s3 == "⭐":
            bonus_spin = True
            text = (
                "🌟 **Starlit Win!**\n🌟 **Starlit Win!**\n🌟 **Starlit Win!**\n\n"
                "Triple ⭐⭐⭐ across the board.\n"
                "You earn a **bonus spin** and a solid payout."
            )
            return 8, text, bonus_spin, jackpot_hit

        if s1 == s2 == s3 == "🍀":
            bonus_spin = True
            text = (
                "🍀 **Lucky Clover!**\n🍀 **Lucky Clover!**\n🍀 **Lucky Clover!**\n\n"
                "Triple clovers shimmer on the reels.\n"
                "You feel the Hog Gods smile — **bonus spin** unlocked!"
            )
            return 6, text, bonus_spin, jackpot_hit

        if len(symbols_set) == 1:
            text = (
                "💰 **Triple hit!**\n💰 **Triple hit!**\n💰 **Triple hit!**\n\n"
                "Three of a kind across the board."
            )
            return 10, text, bonus_spin, jackpot_hit

        if pig_count == 2:
            text = "✨ **Double Hog!** Two 🐷 on the reels — not bad at all."
            return 5, text, bonus_spin, jackpot_hit

        if len(symbols_set) == 2:
            text = "🥈 **That's a nice pair!** Two symbols matched. The house pays out."
            return 2, text, bonus_spin, jackpot_hit

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
        Animation with safe edit retries.
        If edits fail, we still complete logic and attempt a final edit.
        """
        await self._safe_defer(interaction)
        msg = await self._ensure_message(interaction)
        if msg is None:
            # No message to edit; we can’t animate, but we must not deadlock.
            return

        stop_steps = [
            random.randint(5, 7),
            random.randint(7, 9),
            random.randint(9, 15),
        ]
        total_steps = max(stop_steps) + 1

        for step in range(total_steps):
            current_symbols: List[str] = []
            for idx in range(3):
                if step >= stop_steps[idx]:
                    current_symbols.append(final_result[idx])
                else:
                    current_symbols.append(self._spin_symbol())

            reel_line = self._format_reels(current_symbols)

            if step < 4:
                spin_msg = "_The reels are spinning... steady now......._"
                base_delay = 0.2 + (step * 0.03)
                jitter = random.uniform(-0.04, 0.04)
            elif step < total_steps - 4:
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

            # Best effort edits; if these fail, we keep going.
            await self._safe_edit(embed=embed, view=self)
            await asyncio.sleep(max(0.12, base_delay + jitter))

        await asyncio.sleep(random.uniform(0.1, 1.3))

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
        jackpot_amount = getattr(self.state, "slots_progressive_jackpot", 0)
        new_balance = balance + total_payout + jackpot_amount if jackpot_won else balance + total_payout
        jackpot_payout_msg = " + 💰 Jackpot Pool" if jackpot_won else ""
        final_embed.add_field(name="Bet", value=f"🪙 {self.bet:,}", inline=True)
        final_embed.add_field(name="Payout", value=f"🪙 {total_payout:,}{jackpot_payout_msg}", inline=True)
        final_embed.add_field(name="Balance", value=f"🪙 {new_balance:,}", inline=True)
        final_embed.add_field(name="Jackpot Pool", value=f"🪙 {jackpot_amount:,}", inline=False)

        if bonus_available:
            footer_text = "🍀 Bonus unlocked! Press **Crank!** again to use your free spin."
            self._enable_all_items()
        else:
            footer_text = "Use /slots again to spin a new machine."

        final_embed.set_footer(text=footer_text)
        await self._safe_edit(embed=final_embed, view=self)

    async def on_timeout(self):
        # Don't stomp on a running spin; just stop after releasing lock.
        if self.spun:
            # Let watchdog/cleanup handle it; best effort release user lock
            if hasattr(self.state, "active_slots"):
                self.state.active_slots.discard(self.player.id)
            self.stop()
            return

        # If they started at least one spin, don't overwrite the final result.
        if self.spin_started:
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
                await self._safe_edit(embed=embed, view=None)
            except Exception:
                pass

        # Record timeout / cleanup lock
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
                        metadata={
                            "game_source": GameSource.SLOTS,
                            "update_type": UpdateType.BET_LOST,
                            "bet_amount": self.bet,
                            "payout_amount": 0,
                            "reason": "Slot machine timed out.",
                        },
                    )
            except Exception:
                logger.error("Failed to update richest member role on slots timeout", exc_info=True)

        if hasattr(self.state, "active_slots"):
            self.state.active_slots.discard(self.player.id)

        # Stop background tasks
        if hasattr(self, "_cleanup_task") and self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        if hasattr(self, "_watchdog_task") and self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        self.stop()

    # -------------------- UI: Crank Button --------------------

    @discord.ui.button(label="🎰 Crank!", style=discord.ButtonStyle.success)
    async def crank_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_player(interaction):
            return

        # True concurrency guard
        async with self._spin_lock:
            # If already spinning, ignore extra clicks
            if self.spun:
                await self._safe_ephemeral(interaction, "The reels are already spinning. Wait for them to stop first!")
                return

            # If machine spent (main spin done and no unused bonus)
            if self.machine_spent:
                await self._safe_ephemeral(interaction, "This machine is spent. Start a fresh /slots for another spin.")
                return

            is_bonus_spin = self.bonus_spin_available and not self.bonus_spin_used

            # Mark spinning immediately and disable buttons
            self.spun = True
            self._spin_started_at = time.monotonic()
            self.disable_all_items()

            # Best effort to reflect "starting" state quickly
            await self._safe_defer(interaction)

            try:
                # Ensure wallets container
                wallets = getattr(self.state, "member_wallets", None)
                if wallets is None:
                    self.state.member_wallets = {}
                    wallets = self.state.member_wallets

                current_balance = wallets.get(self.player.id, 0)
                jackpot_amount = getattr(self.state, "slots_progressive_jackpot", 0)

                if not is_bonus_spin:
                    # ---- First (paid) spin ----
                    self.spin_started = True

                    final_result = [self._spin_symbol() for _ in range(3)]
                    multiplier, outcome_text, bonus_spin, jackpot_hit = self._evaluate_spin(final_result, jackpot_amount)
                    total_payout = self.bet * multiplier

                    self.bonus_spin_available = bonus_spin
                    self.bonus_spin_used = False

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

                    # Jackpot: add pot on top then reset
                    if jackpot_hit:
                        total_payout += jackpot_amount
                        self.state.slots_progressive_jackpot = SlotsService.JACKPOT_SEED

                    # Apply payout
                    if total_payout > 0:
                        new_balance = current_balance + total_payout
                        try:
                            self.bot.gamble_service.update_wallet(self.player.id, new_balance)
                            self.bot.gamble_service.add_wallet_history_entry(
                                self.player.id,
                                new_balance,
                                metadata={
                                    "game_source": GameSource.SLOTS,
                                    "update_type": UpdateType.BET_WON,
                                    "bet_amount": self.bet,
                                    "payout_amount": total_payout,
                                    "reason": final_result,
                                },
                            )
                        except Exception:
                            logger.error("Error updating wallet after slots win", exc_info=True)
                    else:
                        try:
                            balance = self.state.member_wallets.get(self.player.id, 0)
                            self.bot.gamble_service.add_wallet_history_entry(
                                self.player.id,
                                balance,
                                metadata={
                                    "game_source": GameSource.SLOTS,
                                    "update_type": UpdateType.BET_LOST,
                                    "bet_amount": self.bet,
                                    "payout_amount": 0,
                                    "reason": final_result,
                                },
                            )
                        except Exception:
                            logger.error("Error recording wallet history after slots loss", exc_info=True)

                    try:
                        if interaction.guild is not None:
                            await self.bot.gamble_service.update_richest_member_role(interaction.guild)
                    except Exception:
                        logger.error("Failed to update richest member role after slots spin", exc_info=True)

                    if not self.bonus_spin_available:
                        if hasattr(self.state, "active_slots"):
                            self.state.active_slots.discard(self.player.id)
                        if hasattr(self, "_cleanup_task") and self._cleanup_task and not self._cleanup_task.done():
                            self._cleanup_task.cancel()
                        if hasattr(self, "_watchdog_task") and self._watchdog_task and not self._watchdog_task.done():
                            self._watchdog_task.cancel()
                        self.machine_spent = True
                        self.stop()

                else:
                    # ---- Bonus spin ----
                    wallets = getattr(self.state, "member_wallets", None) or {}
                    current_balance = wallets.get(self.player.id, 0)
                    jackpot_amount = getattr(self.state, "slots_progressive_jackpot", 0)

                    bonus_result = [self._spin_symbol() for _ in range(3)]
                    b_mult, b_text, b_bonus, b_jackpot_hit = self._evaluate_spin(bonus_result, jackpot_amount)
                    bonus_total_payout = self.bet * b_mult

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
                                metadata={
                                    "game_source": GameSource.SLOTS,
                                    "update_type": UpdateType.BET_WON,
                                    "bet_amount": self.bet,
                                    "payout_amount": bonus_total_payout,
                                    "reason": bonus_result,
                                },
                            )
                        except Exception:
                            logger.error("Error updating wallet after slots bonus win", exc_info=True)
                    else:
                        try:
                            balance = self.state.member_wallets.get(self.player.id, 0)
                            self.bot.gamble_service.add_wallet_history_entry(
                                self.player.id,
                                balance,
                                metadata={
                                    "game_source": GameSource.SLOTS,
                                    "update_type": UpdateType.BET_LOST,
                                    "bet_amount": self.bet,
                                    "payout_amount": 0,
                                    "reason": bonus_result,
                                },
                            )
                        except Exception:
                            logger.error("Error recording wallet history after slots bonus loss", exc_info=True)

                    try:
                        if interaction.guild is not None:
                            await self.bot.gamble_service.update_richest_member_role(interaction.guild)
                    except Exception:
                        logger.error("Failed to update richest member role after slots bonus spin", exc_info=True)

                    if not self.bonus_spin_available:
                        if hasattr(self.state, "active_slots"):
                            self.state.active_slots.discard(self.player.id)
                        if hasattr(self, "_cleanup_task") and self._cleanup_task and not self._cleanup_task.done():
                            self._cleanup_task.cancel()
                        if hasattr(self, "_watchdog_task") and self._watchdog_task and not self._watchdog_task.done():
                            self._watchdog_task.cancel()
                        self.machine_spent = True
                        self.stop()

            except Exception:
                logger.error("Unhandled error in crank_button", exc_info=True)
                await self._safe_ephemeral(interaction, "An unexpected error occurred. Press **Crank!** again.")
            finally:
                # Always un-stick the view if we didn't finish cleanly.
                # If bonus is available, we allow another press.
                if self.bonus_spin_available:
                    self.spun = False
                    self._enable_all_items()
                else:
                    # If no bonus remains, machine is effectively done.
                    # But in case of failure mid-spin, we still want to unstick it so user isn't trapped.
                    self.spun = False
                    self._spin_started_at = None
                    # Don't necessarily enable if we've stopped; safe either way:
                    if not self.is_finished():
                        self._enable_all_items()

                # Ensure cleanup if view should no longer be active
                if not self.bonus_spin_available or self.bonus_spin_used:
                    if hasattr(self.state, "active_slots"):
                        self.state.active_slots.discard(self.player.id)


class SlotsService:
    """
    Service entrypoint for the /slots command.
    """

    MIN_BET = 100
    MAX_BET = 10_000
    DEFAULT_BET = 100

    JACKPOT_SEED = 100_000
    JACKPOT_PERCENT = 1  # 100% of bet to jackpot (as written)

    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

        if not hasattr(self.state, "slots_progressive_jackpot"):
            self.state.slots_progressive_jackpot = self.JACKPOT_SEED

        if not hasattr(self.state, "active_slots"):
            self.state.active_slots = set()

    async def slots(self, interaction: discord.Interaction, bet: Optional[int] = None):
        user = interaction.user

        if not hasattr(self.state, "active_slots"):
            self.state.active_slots = set()

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

        if not hasattr(self.state, "member_wallets"):
            self.state.member_wallets = {}

        wallets = self.state.member_wallets
        if user.id not in wallets:
            wallets[user.id] = 1000
            try:
                self.bot.gamble_service.update_wallet(user.id, wallets[user.id])
                self.bot.gamble_service.add_wallet_history_entry(
                    user.id,
                    wallets[user.id],
                    metadata={
                        "game_source": GameSource.SLOTS,
                        "update_type": UpdateType.INIT_BALANCE,
                    },
                )
            except Exception:
                logger.error("Error initializing wallet for slots user", exc_info=True)

        wallet_balance = wallets[user.id]
        bet_amount = self.DEFAULT_BET if bet is None else bet

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
                f"Your bet is 🪙 **{bet_amount:,}**, but you only have 🪙 **{wallet_balance:,}**.\n"
                "Try /beg to scrounge up some Hog Coins."
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            self.state.active_slots.add(user.id)

            new_balance = wallet_balance - bet_amount
            self.bot.gamble_service.update_wallet(user.id, new_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                user.id,
                new_balance,
                metadata={
                    "game_source": GameSource.SLOTS,
                    "update_type": UpdateType.BET_PLACED,
                    "bet_amount": bet_amount,
                },
            )

            try:
                contrib = max(int(bet_amount * self.JACKPOT_PERCENT), 1)
                self.state.slots_progressive_jackpot += contrib
            except Exception:
                logger.error("Error contributing to slots progressive jackpot", exc_info=True)

            view = SlotsView(user, bet_amount, self.state, self.bot)
            description = (
                f"Welcome to **Hog Pen Slots**!\n"
                "Each bet is added towards the **progressive jackpot**.\n"
                "Press **Crank!** to spin the reels.\n\n"
                "**Jackpot:** 🐷🐷🐷\n"
                "**Bonus Spins:** ⭐⭐⭐ or 🍀🍀🍀"
            )
            embed = view._base_embed(description=description)
            await interaction.response.send_message(embed=embed, view=view)
            try:
                view.message = await interaction.original_response()
            except Exception:
                # Not fatal; view has safe fallback for missing message
                logger.warning("Slots: could not wire view.message from original_response", exc_info=True)

        except Exception:
            if hasattr(self.state, "active_slots"):
                self.state.active_slots.discard(user.id)

            logger.error("Error starting slots game", exc_info=True)
            error_msg = "An error occurred while starting the slot machine. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)


__all__ = ["SlotsService"]
