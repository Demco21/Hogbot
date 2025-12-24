from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import asyncio
import random

import discord

from bot_state import BotState
from logging_config import logger
from constants import GameSource, UpdateType, FIRST_BET_BALANCE

MIN_BET = 100


@dataclass
class BJHand:
    cards: List[Dict[str, Any]]
    bet: int
    doubled: bool = False
    from_split: bool = False
    natural_blackjack: bool = False
    finished: bool = False
    result: Optional[str] = None  # "win"|"loss"|"push"|"blackjack"


def _card_value(card: Dict[str, Any]):
    r = int(card["rank"])
    if r >= 11 and r <= 13:
        return 10
    if r == 14:
        return 11
    return r


def _is_ten_value(card: Dict[str, Any]):
    r = int(card["rank"])
    return r == 10 or (11 <= r <= 13)


def _hand_value(cards: List[Dict[str, Any]]):
    total = 0
    aces = 0
    for c in cards:
        v = _card_value(c)
        if int(c["rank"]) == 14:
            aces += 1
        total += v

    # Demote aces from 11 to 1 as needed
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _is_soft(cards: List[Dict[str, Any]]):
    total = 0
    aces = 0
    for c in cards:
        r = int(c["rank"])
        if r == 14:
            aces += 1
            total += 11
        elif 11 <= r <= 13:
            total += 10
        else:
            total += r

    # if we can keep at least one ace as 11 without busting, it's soft
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return aces > 0  # remaining ace(s) counted as 11


class BlackjackView(discord.ui.View):
    def __init__(
        self,
        player: discord.User,
        bet: int,
        state: BotState,
        bot,
    ):
        super().__init__(timeout=180)
        self.player = player
        self.base_bet = bet
        self.state = state
        self.bot = bot

        self.deck: List[Dict[str, Any]] = self._new_deck()
        self.hands: List[BJHand] = []
        self.active_hand_idx: int = 0

        self.dealer_cards: List[Dict[str, Any]] = []
        self.message: Optional[discord.Message] = None

        self._init_deal()

    # ---------- deck / dealing ----------
    def _new_deck(self):
        suits = ["♠️", "♥️", "♦️", "♣️"]
        deck = [{"rank": r, "suit": s} for s in suits for r in range(2, 15)]
        import random

        random.shuffle(deck)
        return deck

    def _draw(self):
        if not self.deck:
            self.deck = self._new_deck()
        return self.deck.pop()

    def _fmt_card(self, c: Dict[str, Any]):
        r = int(c["rank"])
        rank = {11: "J", 12: "Q", 13: "K", 14: "A"}.get(r, str(r))
        return f"{rank}{c['suit']}"

    def _fmt_cards(self, cards: List[Dict[str, Any]]):
        return " ".join(self._fmt_card(c) for c in cards)

    def _init_deal(self):
        p1 = self._draw()
        p2 = self._draw()
        d1 = self._draw()  # upcard
        d2 = self._draw()  # hole

        player_cards = [p1, p2]
        dealer_cards = [d1, d2]

        is_natural = (len(player_cards) == 2) and (_hand_value(player_cards) == 21)
        self.hands = [
            BJHand(
                cards=player_cards,
                bet=self.base_bet,
                doubled=False,
                from_split=False,
                natural_blackjack=is_natural,
                finished=False,
            )
        ]
        self.dealer_cards = dealer_cards

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True
    
    # ---------- interaction guards / helpers ----------
    async def _ensure_player(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                "🚫 This blackjack table is already in use. Start your own with **/blackjack**.",
                ephemeral=True,
            )
            return False
        return True

    async def _safe_edit(self, interaction: discord.Interaction, *, embed: discord.Embed, view: Optional[discord.ui.View]):
        try:
            if interaction.response.is_done():
                await interaction.followup.edit_message(message_id=self.message.id, embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
        except Exception:
            logger.error("Failed to edit blackjack message", exc_info=True)

    async def _update_richest_member_after_game(self, guild: discord.Guild = None):
        if guild is None:
            return
        service = getattr(self.bot, "gamble_service", None)
        if service is None:
            return
        try:
            await service.update_richest_member_role(guild)
        except Exception:
            logger.error("Failed to update richest member role", exc_info=True)

    def _dealer_upcard(self):
        return self.dealer_cards[0]

    def _dealer_has_blackjack(self):
        return len(self.dealer_cards) == 2 and _hand_value(self.dealer_cards) == 21

    def _player_has_blackjack(self):
        h = self.hands[0]
        return (not h.from_split) and h.natural_blackjack and len(h.cards) == 2 and _hand_value(h.cards) == 21

    def _peek_required(self):
        up = self._dealer_upcard()
        return int(up["rank"]) == 14 or _is_ten_value(up)

    def _active_hand(self):
        return self.hands[self.active_hand_idx]

    def _can_split(self):
        h = self._active_hand()
        if h.from_split:
            return False
        if len(self.hands) != 1:
            return False
        if len(h.cards) != 2:
            return False
        v1 = _card_value(h.cards[0])
        v2 = _card_value(h.cards[1])
        return v1 == v2

    def _can_double(self):
        h = self._active_hand()
        if h.finished or h.doubled:
            return False
        return len(h.cards) == 2

    async def _animate_stand_to_dealer_reveal(self, interaction: discord.Interaction, *, note: Optional[str]):
        # Suspense: show stand message while dealer hole is still hidden, then reveal.
        self.disable_all_items()

        embed = self.build_embed(
            reveal_hole=False,
            note=note,
            game_over=False,
            hide_active_marker=True,
        )
        await self._safe_edit(interaction, embed=embed, view=self)

        await asyncio.sleep(1.0)
    
    async def _animate_double_down(self, interaction: discord.Interaction, *, note: Optional[str]):
        self.disable_all_items()

        # Step 1: show "double down" note + pending player card
        embed = self.build_embed(
            reveal_hole=False,
            note=note,
            game_over=False,
            player_pending=True,
        )
        await self._safe_edit(interaction, embed=embed, view=self)

        await asyncio.sleep(1.0)

        # Step 2: actually draw the player's final card and reveal it
        h = self._active_hand()
        h.cards.append(self._draw())
        hv = _hand_value(h.cards)

        embed = self.build_embed(
            reveal_hole=False,
            note=note,
            game_over=False,
            player_pending=False,
        )
        await self._safe_edit(interaction, embed=embed, view=self)

        await asyncio.sleep(1.0)

        # Step 3: if player busted, stop here (no dealer animation)
        if hv > 21:
            h.finished = True
            h.result = "loss"
            await self._resolve_all(interaction, note="💥 **Double down**... and you busted.")
            return

        # Otherwise, forced stand and proceed to dealer animation/resolution
        h.finished = True
        await self._resolve_all(interaction, note=note)

    async def _animate_dealer_play(self, interaction: discord.Interaction, *, note: Optional[str]):
        # Reveal hole card first, then draw one card at a time with a delay.
        self.disable_all_items()

        pending = _hand_value(self.dealer_cards) < 17
        embed = self.build_embed(reveal_hole=True, note=note, game_over=False, dealer_pending=pending, hide_active_marker=True)
        await self._safe_edit(interaction, embed=embed, view=self)

        def get_delay_value():
            if len(self.dealer_cards) == 2:
                return random.uniform(1.5, 2.0)
            if len(self.dealer_cards) == 3:
                return random.uniform(2.0, 2.5)
            if len(self.dealer_cards) > 3:
                return random.uniform(2.5, 3.0)
            return 1.0

        while _hand_value(self.dealer_cards) < 17:
            delay = get_delay_value()
            await asyncio.sleep(delay)
            self.dealer_cards.append(self._draw())

            pending = _hand_value(self.dealer_cards) < 17
            embed = self.build_embed(reveal_hole=True, note=note, game_over=False, dealer_pending=pending, hide_active_marker=True)
            await self._safe_edit(interaction, embed=embed, view=self)

        # Final state with no ❓
        embed = self.build_embed(reveal_hole=True, note=note, game_over=False, dealer_pending=False, hide_active_marker=True)
        await self._safe_edit(interaction, embed=embed, view=self)

    def build_embed(
        self,
        *,
        reveal_hole: bool = False,
        note: Optional[str] = None,
        game_over: bool = False,
        payout_override: Optional[int] = None,
        dealer_pending: bool = False,
        hide_active_marker: bool = False,
        player_pending: bool = False,
    ):
        if reveal_hole:
            dealer_show = self._fmt_cards(self.dealer_cards)
            if dealer_pending:
                dealer_show = f"{dealer_show}  ❓"
        else:
            dealer_show = f"{self._fmt_card(self.dealer_cards[0])}  ❓"

        lines = [f"**Dealer:** {dealer_show}"]

        def get_status(h: BJHand):
            if h.finished and h.result:
                if h.result == "win":
                    return " — ✅"
                if h.result == "push":
                    return " — 🤝"
                if h.result == "loss":
                    return " — ❌"
                if h.result == "blackjack":
                    return " — ✅"
            return ""

        def get_embed_color(hands: List[BJHand], game_over_flag: bool):
            if not game_over_flag:
                return discord.Color.dark_gold()
            saw_push = False
            saw_loss = False
            for hand in hands:
                if not getattr(hand, "finished", False):
                    continue
                result = getattr(hand, "result", None)
                if not result:
                    continue
                if result in ("win", "blackjack"):
                    return discord.Color.green()
                if result == "loss":
                    saw_loss = True
                    continue
                if result == "push":
                    saw_push = True
                    continue
            if saw_push:
                return discord.Color.light_grey()
            if saw_loss:
                return discord.Color.red()
            return discord.Color.light_grey()

        for idx, h in enumerate(self.hands, start=1):
            hv = _hand_value(h.cards)
            marker = ""
            if len(self.hands) > 1 and not hide_active_marker:
                marker = "👉 " if (idx - 1) == self.active_hand_idx and not game_over else ""
            tag = " (Blackjack!)" if (h.natural_blackjack and not h.from_split and len(h.cards) == 2 and hv == 21) else ""
            status = get_status(h)
            hand_cards = self._fmt_cards(h.cards)
            if player_pending and (idx - 1) == self.active_hand_idx and not game_over:
                hand_cards = f"{hand_cards}  ❓"

            lines.append(f"\n{marker}**Hand {idx}:** {hand_cards} {tag}{status}")


        desc = "\n".join(lines)
        if note:
            desc += f"\n\n{note}"

        embed = discord.Embed(
            title="🃏 Blackjack",
            description=desc,
            color=get_embed_color(self.hands, game_over),
        )

        total_bet = sum(int(h.bet or 0) for h in self.hands)

        wallets = getattr(self.state, "member_wallets", {}) or {}
        balance = int(wallets.get(self.player.id, 0) or 0)

        embed.add_field(name="Bet", value=f"🪙 {total_bet:,}", inline=True)

        if game_over:
            if payout_override is not None:
                payout = int(payout_override)
            else:
                payout = 0
                for h in self.hands:
                    r = getattr(h, "result", None)
                    b = int(getattr(h, "bet", 0) or 0)
                    if r == "win":
                        payout += b * 2
                    elif r == "push":
                        payout += b
                    elif r == "blackjack":
                        payout += (b * 5) // 2

            embed.add_field(name="Final Payout", value=f"🪙 {payout:,}", inline=True)

        embed.add_field(name="Balance", value=f"🪙 {balance:,}", inline=True)

        embed.set_footer(text="Hit / Stand / Double / Split. No surrender. Dealer stands on 17.")
        return embed

    def _refresh_buttons(self):
        self.clear_items()

        hit_btn = discord.ui.Button(label="➕ Hit", style=discord.ButtonStyle.primary)
        stand_btn = discord.ui.Button(label="✋ Stand", style=discord.ButtonStyle.secondary)

        double_btn = discord.ui.Button(label="💥 Double", style=discord.ButtonStyle.success, disabled=not self._can_double())
        split_btn = discord.ui.Button(label="🪓 Split", style=discord.ButtonStyle.success, disabled=not self._can_split())

        async def hit_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._hit(i)

        async def stand_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._stand(i)

        async def double_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._double(i)

        async def split_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._split(i)

        hit_btn.callback = hit_cb
        stand_btn.callback = stand_cb
        double_btn.callback = double_cb
        split_btn.callback = split_cb

        self.add_item(hit_btn)
        self.add_item(stand_btn)
        self.add_item(double_btn)
        self.add_item(split_btn)

    # ---------- core actions ----------
    async def start(self, interaction: discord.Interaction):
        self._refresh_buttons()

        # Dealer peek only if upcard is Ace or 10-value
        if self._peek_required() and self._dealer_has_blackjack():
            # Dealer blackjack ends immediately
            reveal = True
            if self._player_has_blackjack():
                # push
                await self._resolve_immediate_push_blackjack(interaction, reveal_hole=reveal)
            else:
                await self._resolve_immediate_dealer_blackjack(interaction, reveal_hole=reveal)
            return

        # Player natural blackjack ends immediately (if dealer didn't have blackjack)
        if self._player_has_blackjack():
            await self._resolve_player_blackjack(interaction)
            return

        embed = self.build_embed(reveal_hole=False)
        await self._safe_edit(interaction, embed=embed, view=self)

    async def _hit(self, interaction: discord.Interaction):
        h = self._active_hand()
        if h.finished:
            return

        h.cards.append(self._draw())
        hv = _hand_value(h.cards)

        if hv > 21:
            h.finished = True
            h.result = "loss"
            note = "💀 **Busted.** Moving to the next hand..." if self._has_unfinished_other_hand() else "💀 **Busted.** Resolving dealer..."
            await self._advance_or_resolve(interaction, note=note)
            return

        self._refresh_buttons()
        embed = self.build_embed(reveal_hole=False)
        await self._safe_edit(interaction, embed=embed, view=self)

    async def _stand(self, interaction: discord.Interaction):
        h = self._active_hand()
        if h.finished:
            return
        h.finished = True
        await self._advance_or_resolve(interaction, note="✋ **Stand.**")

    async def _double(self, interaction: discord.Interaction):
        h = self._active_hand()
        if not self._can_double():
            return

        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)
        if bal < h.bet:
            await interaction.response.send_message(
                f"🚫 You need 🪙 **{h.bet:,}** more to double. Current balance: 🪙 **{bal:,}**",
                ephemeral=True,
            )
            return

        # Deduct extra bet
        new_bal = bal - h.bet
        self.bot.gamble_service.update_wallet(self.player.id, new_bal)

        h.bet *= 2
        h.doubled = True

        # Animate suspense: show ❓, then draw/reveal, then dealer plays
        await self._animate_double_down(interaction, note="💥 **Double down** taken.")


    async def _split(self, interaction: discord.Interaction):
        if not self._can_split():
            return

        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)
        if bal < self.base_bet:
            await interaction.response.send_message(
                f"🚫 You need 🪙 **{self.base_bet:,}** to split. Current balance: 🪙 **{bal:,}**",
                ephemeral=True,
            )
            return

        # Deduct extra bet for the second hand
        new_bal = bal - self.base_bet
        self.bot.gamble_service.update_wallet(self.player.id, new_bal)

        # Log the split bet as another BET_PLACED (counts as another hand played)
        self.bot.gamble_service.add_wallet_history_entry(
            self.player.id,
            new_bal,
            metadata={
                "game_source": GameSource.BLACKJACK,
                "update_type": UpdateType.BET_PLACED,
                "bet_amount": self.base_bet,
                "choice": "split",
            },
        )

        orig = self.hands[0]
        c1, c2 = orig.cards[0], orig.cards[1]

        h1 = BJHand(cards=[c1, self._draw()], bet=self.base_bet, from_split=True)
        h2 = BJHand(cards=[c2, self._draw()], bet=self.base_bet, from_split=True)

        self.hands = [h1, h2]
        self.active_hand_idx = 0

        self._refresh_buttons()
        embed = self.build_embed(reveal_hole=False, note="🪓 **Split!** Playing Hand 1 first.")
        await self._safe_edit(interaction, embed=embed, view=self)

    def _has_unfinished_other_hand(self):
        return any(not h.finished for h in self.hands)

    async def _advance_or_resolve(self, interaction: discord.Interaction, *, note: Optional[str] = None):
        # Move to next unfinished hand, else resolve dealer + outcomes
        for idx, h in enumerate(self.hands):
            if not h.finished:
                self.active_hand_idx = idx
                self._refresh_buttons()
                embed = self.build_embed(reveal_hole=False, note=note)
                await self._safe_edit(interaction, embed=embed, view=self)
                return

        await self._resolve_all(interaction, note=note)

    # ---------- resolution ----------
    async def _resolve_immediate_dealer_blackjack(self, interaction: discord.Interaction, *, reveal_hole: bool):
        # player loses entire initial bet (already deducted); just log loss
        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)

        self.bot.gamble_service.add_wallet_history_entry(
            self.player.id,
            bal,
            metadata={
                "game_source": GameSource.BLACKJACK,
                "update_type": UpdateType.BET_LOST,
                "bet_amount": self.base_bet,
                "payout_amount": 0,
                "reason": "dealer_blackjack",
            },
        )

        for h in self.hands:
            h.finished = True
            h.result = "loss"

        self.disable_all_items()
        embed = self.build_embed(reveal_hole=reveal_hole, note="🂡 Dealer has **BLACKJACK**. You lose.", game_over=True)
        await self._safe_edit(interaction, embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _resolve_immediate_push_blackjack(self, interaction: discord.Interaction, *, reveal_hole: bool):
        # push: return bet
        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)
        new_bal = bal + self.base_bet

        self.bot.gamble_service.update_wallet(self.player.id, new_bal)
        self.bot.gamble_service.add_wallet_history_entry(
            self.player.id,
            new_bal,
            metadata={
                "game_source": GameSource.BLACKJACK,
                "update_type": UpdateType.BET_PUSH,
                "bet_amount": self.base_bet,
                "payout_amount": self.base_bet,
                "reason": "both_blackjack",
            },
        )

        for h in self.hands:
            h.finished = True
            h.result = "push"

        self.disable_all_items()
        embed = self.build_embed(reveal_hole=reveal_hole, note="🤝 Both have **BLACKJACK**. Push.", game_over=True)
        await self._safe_edit(interaction, embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _resolve_player_blackjack(self, interaction: discord.Interaction):
        # payout 3:2 => total return = 2.5x bet
        payout = (self.base_bet * 5) // 2
        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)
        new_bal = bal + payout

        self.bot.gamble_service.update_wallet(self.player.id, new_bal)
        self.bot.gamble_service.add_wallet_history_entry(
            self.player.id,
            new_bal,
            metadata={
                "game_source": GameSource.BLACKJACK,
                "update_type": UpdateType.BET_WON,
                "bet_amount": self.base_bet,
                "payout_amount": payout,
                "blackjack": True,
                "reason": "natural_blackjack",
            },
        )

        self.hands[0].finished = True
        self.hands[0].result = "blackjack"

        self.disable_all_items()
        embed = self.build_embed(reveal_hole=False, note=f"🂡🃏 **BLACKJACK!** You win 🪙 **{payout:,}**.", game_over=True)
        await self._safe_edit(interaction, embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _resolve_all(self, interaction: discord.Interaction, *, note: Optional[str] = None):
        # If every hand is already busted, skip dealer play/animation entirely.
        if all(_hand_value(h.cards) > 21 for h in self.hands):
            wallets = getattr(self.state, "member_wallets", {}) or {}
            bal = int(wallets.get(self.player.id, 0) or 0)
            new_bal = bal

            notes = []
            if note:
                notes.append(note)

            for h in self.hands:
                h.result = "loss"
                h.finished = True
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_LOST,
                        "bet_amount": h.bet,
                        "payout_amount": 0,
                        "double_down": bool(h.doubled),
                        "reason": "bust",
                    },
                )

            self.disable_all_items()
            embed = self.build_embed(
                reveal_hole=False,
                note="\n".join(notes) if notes else None,
                game_over=True,
            )
            await self._safe_edit(interaction, embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            self.stop()
            return

        # Suspense before the dealer reveals the hole card
        await self._animate_stand_to_dealer_reveal(interaction, note=note)

        # Dealer plays out with animation (stand on 17, including soft 17)
        await self._animate_dealer_play(interaction, note=note)

        dealer_total = _hand_value(self.dealer_cards)
        dealer_bust = dealer_total > 21

        wallets = getattr(self.state, "member_wallets", {}) or {}
        bal = int(wallets.get(self.player.id, 0) or 0)
        new_bal = bal

        notes = []
        if note:
            notes.append(note)

        for h in self.hands:
            if _hand_value(h.cards) > 21:
                h.result = "loss"
                h.finished = True
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_LOST,
                        "bet_amount": h.bet,
                        "payout_amount": 0,
                        "double_down": bool(h.doubled),
                        "reason": "bust",
                    },
                )
                continue

            player_total = _hand_value(h.cards)

            if dealer_bust:
                payout = h.bet * 2
                new_bal += payout
                self.bot.gamble_service.update_wallet(self.player.id, new_bal)
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_WON,
                        "bet_amount": h.bet,
                        "payout_amount": payout,
                        "double_down": bool(h.doubled),
                        "reason": "dealer_bust",
                    },
                )
                h.result = "win"
                h.finished = True
                continue

            if player_total > dealer_total:
                payout = h.bet * 2
                new_bal += payout
                self.bot.gamble_service.update_wallet(self.player.id, new_bal)
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_WON,
                        "bet_amount": h.bet,
                        "payout_amount": payout,
                        "double_down": bool(h.doubled),
                        "reason": "higher_than_dealer",
                    },
                )
                h.result = "win"
            elif player_total < dealer_total:
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_LOST,
                        "bet_amount": h.bet,
                        "payout_amount": 0,
                        "double_down": bool(h.doubled),
                        "reason": "lower_than_dealer",
                    },
                )
                h.result = "loss"
            else:
                payout = h.bet
                new_bal += payout
                self.bot.gamble_service.update_wallet(self.player.id, new_bal)
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id,
                    new_bal,
                    metadata={
                        "game_source": GameSource.BLACKJACK,
                        "update_type": UpdateType.BET_PUSH,
                        "bet_amount": h.bet,
                        "payout_amount": payout,
                        "double_down": bool(h.doubled),
                        "reason": "push",
                    },
                )
                h.result = "push"

            h.finished = True

        self.disable_all_items()
        embed = self.build_embed(reveal_hole=True, note="\n".join(notes) if notes else None, game_over=True)
        await self._safe_edit(interaction, embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()


class BlackjackService:
    def __init__(self, bot_state, bot):
        self.state = bot_state
        self.bot = bot

    def _prune_processed_interactions(self, *, ttl_seconds: int = 60):
        processed = getattr(self.state, "processed_interactions", None)
        if not isinstance(processed, dict) or not processed:
            return

        now_ts = datetime.now(timezone.utc).timestamp()
        to_delete = [iid for iid, ts in processed.items() if now_ts - float(ts) > ttl_seconds]
        for iid in to_delete:
            processed.pop(iid, None)

    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if bet < MIN_BET:
            msg = f"Minimum bet is 🪙 **{MIN_BET:,}**."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        if not hasattr(self.state, "processed_interactions") or not isinstance(self.state.processed_interactions, dict):
            self.state.processed_interactions = {}

        self._prune_processed_interactions(ttl_seconds=60)

        # prevent double-processing the same interaction id
        if interaction.id in self.state.processed_interactions:
            return

        if bet <= 0:
            msg = "Bet must be a positive number."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        # ensure wallets exists
        if not hasattr(self.state, "member_wallets") or self.state.member_wallets is None:
            self.state.member_wallets = {}

        wallets = self.state.member_wallets

        # init balance if missing
        if interaction.user.id in wallets:
            wallet_balance = int(wallets[interaction.user.id] or 0)
        else:
            wallet_balance = FIRST_BET_BALANCE
            self.bot.gamble_service.update_wallet(interaction.user.id, wallet_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                interaction.user.id,
                wallet_balance,
                metadata={
                    "game_source": GameSource.BLACKJACK,
                    "update_type": UpdateType.INIT_BALANCE,
                    "choice": "game_start",
                    "bet_amount": bet,
                },
            )

        if bet > wallet_balance:
            msg = (
                "You don't have enough **Hog Coins** to make that bet. "
                f"Your current balance is 🪙 **{wallet_balance:,}**."
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            # deduct bet up front
            wallet_balance -= bet
            self.bot.gamble_service.update_wallet(interaction.user.id, wallet_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                interaction.user.id,
                wallet_balance,
                metadata={
                    "game_source": GameSource.BLACKJACK,
                    "update_type": UpdateType.BET_PLACED,
                    "bet_amount": bet,
                    "choice": "game_start",
                },
            )

            view = BlackjackView(interaction.user, bet, self.state, self.bot)
            embed = view.build_embed(reveal_hole=False, note=None, game_over=False)

            if interaction.response.is_done():
                msg_obj = await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
                msg_obj = await interaction.original_response()

            view.message = msg_obj

            self.state.processed_interactions[interaction.id] = datetime.now(timezone.utc).timestamp()
            self._prune_processed_interactions(ttl_seconds=60)

            # IMPORTANT: handle immediate dealer blackjack check after we have a message to edit
            await view.start(interaction)

        except Exception:
            self.state.processed_interactions.pop(interaction.id, None)
            logger.error("Error starting Blackjack game", exc_info=True)

            error_msg = "An error occurred while starting Blackjack. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

__all__ = ['BlackjackService']