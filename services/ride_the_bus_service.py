from datetime import datetime, timedelta
from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random
from constants import GameSource, UpdateType

class RideTheBusView(discord.ui.View):
    """
    Interactive view for the Ride the Bus game.

    Flow:
      1. Red / Black -> 2x on win, then Cash Out or Continue.
      2. Higher / Lower vs first card -> 3x on win, then Cash Out or Continue.
      3. Inside / Outside vs first two cards (matching either = loss) -> 4x on win, then Cash Out or Continue.
      4. Guess Suit -> 8x on win, otherwise loss.
    """
    def __init__(self, player: discord.User, bet: int, bot_state: BotState, bot):
        super().__init__(timeout=180)
        self.player = player
        self.bet = bet
        self.stage = 1
        self.current_multiplier = 2
        self.cards = []  # list of dicts: {"rank": int, "suit": str}
        self.deck = self._build_deck()
        self.message: discord.Message | None = None
        self.state = bot_state
        self.bot = bot

    # ---------- Helpers ----------

    def _build_deck(self):
        suits = ["♠️", "♥️", "♦️", "♣️"]
        deck = []
        for suit in suits:
            for rank in range(2, 15):  # 2-10, 11=J,12=Q,13=K,14=A
                deck.append({"rank": rank, "suit": suit})
        random.shuffle(deck)
        return deck

    def draw_card(self):
        if not self.deck:
            self.deck = self._build_deck()
        return self.deck.pop()

    @staticmethod
    def _rank_str(rank: int):
        mapping = {11: "J", 12: "Q", 13: "K", 14: "A"}
        return mapping.get(rank, str(rank))

    def format_card(self, card):
        return f"{self._rank_str(card['rank'])}{card['suit']}"

    @staticmethod
    def card_color(card):
        # Hearts / Diamonds = red; Clubs / Spades = black
        if card["suit"] in {"♥️", "♦️"}:
            return "red"
        return "black"

    def cards_summary(self):
        if not self.cards:
            return "❓ ❓ ❓ ❓"
        if len(self.cards) == 1:
            return f"{self.format_card(self.cards[0])} ❓ ❓ ❓"
        if len(self.cards) == 2:
            return f"{self.format_card(self.cards[0])} {self.format_card(self.cards[1])} ❓ ❓"
        if len(self.cards) == 3:
            return f"{self.format_card(self.cards[0])} {self.format_card(self.cards[1])} {self.format_card(self.cards[2])} ❓"
        return " ".join(self.format_card(c) for c in self.cards)

    def potential_payout(self, multiplier: int):
        return self.bet * multiplier

    async def _ensure_player(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            try:
                await interaction.response.send_message(
                    "This isn't your game of Ride the Bus.",
                    ephemeral=True
                )
            except discord.InteractionResponded:
                # Already responded elsewhere
                pass
            return False
        return True

    def _base_embed(self, description: str, *, win: bool = None, game_over: bool = None):
        color = discord.Color.blurple()
        if win is True:
            color = discord.Color.green()
        elif win is False:
            color = discord.Color.red()

        embed = discord.Embed(
            title=f"🃏 Ride the Bus",
            description=f"**Player**: {self.player.mention}\n\n" + description,
            color=color
        )
        embed.add_field(name="Bet", value=f"🪙 {str(self.bet)}", inline=True)
        # first round, no win/loss yet
        if self.stage == 1 and win is not True and game_over is not True:
            embed.add_field(name="Cashout Value", value=f"🪙 0", inline=True)
            embed.add_field(name="Balance", value=f"🪙 {self.state.member_wallets[self.player.id]}", inline=True)
        # first round, lost
        elif self.stage == 1 and win is not True and game_over is True:
            embed.add_field(name="Final Payout", value=f"🪙 0", inline=True)
            embed.add_field(name="Balance", value=f"🪙 {self.state.member_wallets[self.player.id]}", inline=True)
        # ongoing game, show cashout value
        elif not game_over:
            embed.add_field(name="Cashout Value", value=f"🪙 {self.potential_payout(self.current_multiplier)}", inline=True)
            embed.add_field(name="Balance", value=f"🪙 {self.state.member_wallets[self.player.id]}", inline=True)
        # game over, show final payout if any
        elif game_over is True:
            embed.add_field(name="Final Payout", value=f"🪙 {self.potential_payout(self.current_multiplier)}", inline=True)
            embed.add_field(name="Balance", value=f"🪙 {self.state.member_wallets[self.player.id]}", inline=True)
        embed.add_field(name="Cards so far", value=self.cards_summary(), inline=False)
        return embed

    def _reset_buttons_for_round1(self):
        self.clear_items()
        self.add_item(self.red_button)
        self.add_item(self.black_button)

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        self.disable_all_items()
        guild = self.message.guild if self.message else None
        if self.message:
            try:
                embed = self.message.embeds[0] if self.message.embeds else self._base_embed("Game timed out.")
                embed.set_footer(text="⏰ Game timed out.")
                await self.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        if guild is not None:
            try:
                await self._update_richest_member_after_game(guild)
                wallet_balance = self.state.member_wallets[self.player.id]
                self.bot.gamble_service.add_wallet_history_entry(
                    self.player.id, 
                    wallet_balance,
                    metadata = {
                        "game_source": GameSource.RIDE_THE_BUS,
                        "update_type": UpdateType.BET_LOST,
                        "bet_amount": self.bet,
                        "payout_amount": 0,
                        "reason": "Game timed out"
                    }
                )
            except Exception:
                logger.error("Failed to update richest member role on timeout", exc_info=True)

        self.stop()

    # ---------- Round 1: Red / Black ----------

    def build_intro_embed(self):
        desc = (
            "**Round 1 – Red or Black?**\n"
            "Guess the **color** of the first card.\n\n"
            "**Round 1 Multiplier**: 🪙x2\n\n"
        )
        self._reset_buttons_for_round1()
        self.current_multiplier = 2
        return self._base_embed(desc)

    @discord.ui.button(label="🟥 Red", style=discord.ButtonStyle.danger)
    async def red_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_player(interaction):
            return
        await self._handle_color_guess(interaction, "red")

    @discord.ui.button(label="⬛ Black", style=discord.ButtonStyle.secondary)
    async def black_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_player(interaction):
            return
        await self._handle_color_guess(interaction, "black")

    async def _handle_color_guess(self, interaction: discord.Interaction, guess: str):
        self.stage = 1
        card = self.draw_card()
        self.cards.append(card)
        actual_color = self.card_color(card)

        try:
            player_id = self.player.id
            color_stats = self.state.first_round_color_draws.setdefault(
                player_id, {"red": 0, "black": 0}
            )
            if actual_color == "red":
                color_stats["red"] += 1
            else:
                color_stats["black"] += 1
        except Exception:
            logger.error("Error updating first_round_color_draws", exc_info=True)

        desc = (
            f"**Round 1 – Red or Black**\n"
        )

        if guess == actual_color:
            self.current_multiplier = 2
            potential = self.potential_payout(self.current_multiplier)
            desc += (
                "\n✅ You **won**!\n"
                f"Current multiplier: **x{self.current_multiplier}**\n"
            )
            self.clear_items()
            embed = self._base_embed(desc, win=True)
            await self.prompt_round_two(interaction, embed)
        else:
            desc += "\n❌ You **lost**. The house takes your bet."
            self.current_multiplier = 0
            self.disable_all_items()
            embed = self._base_embed(desc, win=False, game_over=True)
            await interaction.response.edit_message(embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": guess,
                    "actual": actual_color,
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "wrong color guess"
                }
            )
            self.stop()

    # ---------- Round 2: Higher / Lower ----------

    async def prompt_round_two(self, interaction: discord.Interaction, embed):
        self.stage = 2
        self.clear_items()

        higher_button = discord.ui.Button(
            label="⬆️ Higher",
            style=discord.ButtonStyle.primary
        )
        lower_button = discord.ui.Button(
            label="⬇️ Lower",
            style=discord.ButtonStyle.primary
        )
        cashout_button = discord.ui.Button(
            label="💰 Cashout",
            style=discord.ButtonStyle.primary
        )

        async def higher_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._handle_hilo_guess(i, "higher")

        async def lower_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._handle_hilo_guess(i, "lower")

        higher_button.callback = higher_cb
        lower_button.callback = lower_cb
        cashout_button.callback = self.cashout_callback

        self.add_item(higher_button)
        self.add_item(lower_button)
        self.add_item(cashout_button)

        first_card = self.cards[0]
        desc = (
            "**Round 2 – Higher or Lower**\n"
            "Guess if the **next card** will be **higher** or **lower**.\n"
            "_Ties lose._\n\n"
            "**Round 2 Multiplier**: 🪙x3"
        )
        embed = self._base_embed(desc)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _handle_hilo_guess(self, interaction: discord.Interaction, guess: str):
        second = self.draw_card()
        self.cards.append(second)
        first = self.cards[0]

        desc = (
            "**Round 2 – Higher or Lower**\n"
        )

        if second["rank"] == first["rank"]:
            desc += "\nIt's a **tie** – house wins.\n❌ You **lost** your bet."
            self.current_multiplier = 0
            self.disable_all_items()
            embed = self._base_embed(desc, win=False, game_over=True)
            await interaction.response.edit_message(embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": guess,
                    "actual": self.format_card(second),
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "overunder tie"
                }
            )
            self.stop()
            return

        is_higher = second["rank"] > first["rank"]
        win = (guess == "higher" and is_higher) or (guess == "lower" and not is_higher)

        if win:
            self.current_multiplier = 3
            potential = self.potential_payout(self.current_multiplier)
            desc += (
                "\n✅ You **won**!\n"
                f"Current multiplier: **x{self.current_multiplier}**\n"
            )
            self.clear_items()
            embed = self._base_embed(desc, win=True)
            await self.prompt_round_three(interaction, embed)
        else:
            desc += "\n❌ You **lost** this round. The house takes your bet."
            self.current_multiplier = 0
            self.disable_all_items()
            embed = self._base_embed(desc, win=False, game_over=True)
            await interaction.response.edit_message(embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": guess,
                    "actual": "higher" if is_higher else "lower",
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "wrong higher guess" if guess == "higher" else "wrong lower guess"
                }
            )
            self.stop()

    # ---------- Round 3: Inside / Outside ----------

    async def prompt_round_three(self, interaction: discord.Interaction, embed):
        self.stage = 3
        self.clear_items()

        inside_button = discord.ui.Button(
            label="⬛ Inside",
            style=discord.ButtonStyle.primary
        )
        outside_button = discord.ui.Button(
            label="⬜ Outside",
            style=discord.ButtonStyle.primary
        )
        cashout_button = discord.ui.Button(
            label="💰 Cashout",
            style=discord.ButtonStyle.primary
        )

        async def inside_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._handle_inside_outside(i, "inside")

        async def outside_cb(i: discord.Interaction):
            if not await self._ensure_player(i):
                return
            await self._handle_inside_outside(i, "outside")

        inside_button.callback = inside_cb
        outside_button.callback = outside_cb
        cashout_button.callback = self.cashout_callback

        self.add_item(inside_button)
        self.add_item(outside_button)
        self.add_item(cashout_button)

        first, second = self.cards[0], self.cards[1]
        low = min(first["rank"], second["rank"])
        high = max(first["rank"], second["rank"])

        desc = (
            "**Round 3 – Inside or Outside**\n"
            "\nGuess if the **next card** will be **inside** or **outside** the first two cards.\n"
            "If it **matches** either card exactly, you **lose**.\n\n"
            "**Round 3 Multiplier**: 🪙x4"
        )
        embed = self._base_embed(desc)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _handle_inside_outside(self, interaction: discord.Interaction, guess: str):
        third = self.draw_card()
        self.cards.append(third)
        first, second = self.cards[0], self.cards[1]
        low = min(first["rank"], second["rank"])
        high = max(first["rank"], second["rank"])

        desc = (
            "**Round 3 – Inside or Outside**\n"
        )

        if third["rank"] == first["rank"] or third["rank"] == second["rank"]:
            desc += (
                "\nThe third card **matches** one of the first two.\n"
                "❌ You **lose** this round and your bet."
            )
            self.current_multiplier = 0
            self.disable_all_items()
            embed = self._base_embed(desc, win=False, game_over=True)
            await interaction.response.edit_message(embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": guess,
                    "actual": self.format_card(third),
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "inside/outside match"
                }
            )
            self.stop()
            return

        inside = low < third["rank"] < high
        win = (guess == "inside" and inside) or (guess == "outside" and not inside)

        if win:
            self.current_multiplier = 4
            potential = self.potential_payout(self.current_multiplier)
            desc += (
                "\n✅ You **won**!\n"
                f"Current multiplier: **x{self.current_multiplier}**\n"
                f"If you cash out now, you take 🪙 **{potential}**.\n\n"
            )
            self.clear_items()
            embed = self._base_embed(desc, win=True)
            await self.prompt_round_four(interaction, embed)
        else:
            desc += "\n❌ You **lost** this round. The house takes your bet."
            self.current_multiplier = 0
            self.disable_all_items()
            embed = self._base_embed(desc, win=False, game_over=True)
            await interaction.response.edit_message(embed=embed, view=None)
            await self._update_richest_member_after_game(interaction.guild)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": guess,
                    "actual": "inside" if inside else "outside",
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "wrong inside guess" if guess == "inside" else "wrong outside guess"
                }
            )
            self.stop()

    # ---------- Round 4: Guess the Suit ----------

    async def prompt_round_four(self, interaction: discord.Interaction, embed):
        self.stage = 4
        self.clear_items()

        suits = [
            ("♠️", "Spades"),
            ("♥️", "Hearts"),
            ("♦️", "Diamonds"),
            ("♣️", "Clubs"),
        ]

        for symbol, name in suits:
            button = discord.ui.Button(
                label=f"{symbol} {name}",
                style=discord.ButtonStyle.primary
            )

            async def suit_cb(i: discord.Interaction, s=symbol):
                if not await self._ensure_player(i):
                    return
                await self._handle_suit_guess(i, s)

            button.callback = suit_cb
            self.add_item(button)

        cashout_button = discord.ui.Button(
            label="💰 Cashout",
            style=discord.ButtonStyle.primary
        )
        cashout_button.callback = self.cashout_callback
        self.add_item(cashout_button)

        desc = (
            "**Round 4 – Guess the Suit**\n"
            "\nFinal card! Guess the **suit** of the last card.\n\n"
            "**Round 4 Multiplier**: 🪙x8\n"
        )
        embed = self._base_embed(desc)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _handle_suit_guess(self, interaction: discord.Interaction, suit_symbol: str):
        fourth = self.draw_card()
        self.cards.append(fourth)

        desc = (
            "**Round 4 – Guess the Suit**\n"
        )

        if fourth["suit"] == suit_symbol:
            self.current_multiplier = 8
            wallet_balance = self.state.member_wallets[self.player.id]
            winnings = self.potential_payout(self.current_multiplier)
            new_balance = wallet_balance + winnings
            self.bot.gamble_service.update_wallet(self.player.id, new_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                new_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_WON,
                    "choice": suit_symbol,
                    "actual": fourth["suit"],
                    "round": "4",
                    "bet_amount": self.bet,
                    "payout_amount": winnings,
                    "reason": "correct suit"
                }
            )
            desc += (
                "\n🎉 **Jackpot!** You guessed correctly.\n\n"
                f"**Final Multiplier**: 🪙x{self.current_multiplier}\n"
            )
            embed = self._base_embed(desc, win=True, game_over=True)
        else:
            self.current_multiplier = 0
            desc += "\n❌ Wrong suit. You **lose** your bet."
            embed = self._base_embed(desc, win=False, game_over=True)
            wallet_balance = self.state.member_wallets[self.player.id]
            self.bot.gamble_service.add_wallet_history_entry(
                self.player.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_LOST,
                    "choice": suit_symbol,
                    "actual": fourth["suit"],
                    "round": "4",
                    "bet_amount": self.bet,
                    "payout_amount": 0,
                    "reason": "wrong suit"
                }
            )

        self.disable_all_items()
        await interaction.response.edit_message(embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def cashout_callback(self, interaction: discord.Interaction):
        if not await self._ensure_player(interaction):
            return
        wallet_balance = self.state.member_wallets[self.player.id]
        winnings = self.potential_payout(self.current_multiplier)
        new_balance = wallet_balance + winnings
        self.bot.gamble_service.update_wallet(self.player.id, new_balance)
        self.bot.gamble_service.add_wallet_history_entry(
            self.player.id, 
            new_balance,
            metadata = {
                "game_source": GameSource.RIDE_THE_BUS,
                "update_type": UpdateType.BET_WON,
                "choice": "cashout",
                "round": self.stage,
                "bet_amount": self.bet,
                "payout_amount": winnings,
            }
        )
        desc = (
            f"You chose to **cash out**.\n\n"
            f"**Final Multiplier**: 🪙x{self.current_multiplier}\n"
        )
        embed = self._base_embed(desc, win=True, game_over=True)
        self.disable_all_items()
        await interaction.response.edit_message(embed=embed, view=None)
        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _update_richest_member_after_game(self, guild: discord.Guild = None):
        """
        Call back into the RideTheBusService to update the richest member role
        after a game concludes (win, loss, cashout, or timeout).
        """
        if guild is None:
            return

        service = getattr(self.bot, "gamble_service", None)
        if service is None:
            # In case the bot wasn't wired with this attribute
            logger.warning("gamble_service not found on bot when updating richest member.")
            return

        try:
            await service.update_richest_member_role(guild)
        except Exception:
            logger.error("Failed to update richest member role", exc_info=True)

class RideTheBusService:

    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    async def ride_the_bus(self, interaction: discord.Interaction, bet: int):
        """
        Entry point for the /ridethebus slash command.

        bet: integer wager amount (you can wire this into an economy system later).
        """
        if bet <= 0:
            msg = "Bet must be a positive number."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        if interaction.user.id in self.state.member_wallets:
            wallet_balance = self.state.member_wallets[interaction.user.id]
        else:
            wallet_balance = 1000
            self.bot.gamble_service.update_wallet(interaction.user.id, wallet_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                interaction.user.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.INIT_BALANCE,
                    "choice": "game_start",
                    "round": "1",
                    "bet_amount": self.bet,
                }
            )
        if bet > wallet_balance:
            msg = f"You don't have enough **Hog Coins** to make that bet. Your current balance is 🪙 {wallet_balance}."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            wallet_balance -= bet
            self.bot.gamble_service.update_wallet(interaction.user.id, wallet_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                interaction.user.id, 
                wallet_balance,
                metadata = {
                    "game_source": GameSource.RIDE_THE_BUS,
                    "update_type": UpdateType.BET_PLACED,
                    "bet_amount": bet,
                    "choice": "game_start",
                    "round": "1",
                }
            )
            view = RideTheBusView(interaction.user, bet, self.state, self.bot)
            embed = view.build_intro_embed()
            await interaction.response.send_message(embed=embed, view=view)
            # Save message reference for timeout handling
            view.message = await interaction.original_response()
        except Exception:
            logger.error("Error starting Ride the Bus game", exc_info=True)
            error_msg = "An error occurred while starting Ride the Bus. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

__all__ = ['RideTheBusService']