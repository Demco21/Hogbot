from bot_state import BotState
from logging_config import logger
import discord
from discord.ext import commands
import random
from constants import GameSource, UpdateType

class CeeLoView(discord.ui.View):
    """
    Interactive view for the Cee-Lo lobby and game.

    Flow:
      - Lobby:
          • Host creates lobby with a buy-in (/ceelo).
          • Host is auto-joined and pays the buy-in.
          • Buttons: Join, Start, Leave, End.
          • Only joined players can Start/Leave/End.
          • Start requires 2+ players.

      - Game:
          • Join/Start/Leave/End buttons are removed.
          • Embed shows players in join order.
          • Only current player can press Roll.
          • Each player rolls until they get a scoring combo.
          • Special rules:
              - [4,5,6] (any order): immediate win, pot goes to that player.
              - [1,2,3] (any order): immediate loss; player is ineligible.
              - Triples (e.g. [6,6,6]) ranked from 6s down to 1s.
              - Pair + single (e.g. [X,X,6]): point = the odd die, ranked 6 -> 1.
              - Non-scoring roll (e.g. 2,3,5 that isn't 1-2-3 or 4-5-6): roll again.

          • After all players have a scoring result or bust:
              - If everyone rolled [1,2,3], all buy-ins refunded.
              - Otherwise, best score wins the pot.
    """

    def __init__(self, host: discord.Member, buy_in: int, bot_state: BotState, bot):
        super().__init__(timeout=300)
        self.host = host
        self.buy_in = buy_in
        self.state = bot_state
        self.bot = bot

        self.participants: list[discord.Member] = [host]
        self.participant_ids: list[int] = [host.id]
        self.game_started: bool = False
        self.current_index: int = 0

        # Scores: member_id -> dict with keys:
        #   category, value, dice, label, auto_win, auto_lose
        self.scores: dict[int, dict] = {}
        self.eliminated: set[int] = set()  # players who rolled 1-2-3

        self.message = None
        self.channel = None

        # Pot starts with host's buy-in (already deducted by service)
        self.pot: int = buy_in

    # ---------- Utility helpers ----------

    def _wallets(self):
        if not hasattr(self.state, "member_wallets"):
            self.state.member_wallets = {}
        return self.state.member_wallets

    def _ensure_wallet(self, member_id: int):
        wallets = self._wallets()
        if member_id not in wallets:
            new_balance = 1000
            self.bot.gamble_service.update_wallet(member_id, new_balance)
            self.bot.gamble_service.add_wallet_history_entry(
                member_id, 
                new_balance,
                metadata = {
                    "game_source": GameSource.CEE_LO,
                    "update_type": UpdateType.INIT_BALANCE,
                }
            )
        return wallets[member_id]

    def _build_lobby_embed(self):
        wallets = self._wallets()
        desc_lines = [
            f"**Host**: {self.host.mention}",
            f"**Buy-in**: 🪙 **{self.buy_in}** per player",
            f"**Current Pot**: 🪙 **{self.pot}**",
            "",
            f"**Players ({len(self.participants)}):**",
        ]
        for idx, member in enumerate(self.participants, start=1):
            desc_lines.append(f"{idx}. {member.mention}")

        embed = discord.Embed(
            title="🎲 Cee-Lo Lobby",
            description="\n".join(desc_lines),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Join the lobby, then Start when ready (minimum 2 players).")
        return embed

    def _build_game_embed(self):
        wallets = self._wallets()
        lines = [
            f"**Buy-in**: 🪙 **{self.buy_in}** per player",
            f"**Pot**: 🪙 **{self.pot}**",
            "",
            "**Players & Results:**"
        ]

        for idx, member in enumerate(self.participants, start=1):
            base = f"{idx}. {member.mention}"

            if member.id in self.eliminated:
                # Eliminated via auto-lose (1-2-3)
                status = " — 🎲 **[1, 2, 3] (busted ❌)**"
            elif member.id in self.scores:
                score = self.scores[member.id]
                status = f" — {self._format_dice(list(score['dice']))} — {score['label']}"
            elif self.game_started and idx - 1 == self.current_index:
                status = " — 🎲 **Rolling now...**"
            else:
                status = " — ⏳ Waiting to roll"

            lines.append(f"{base}{status}")

        embed = discord.Embed(
            title="🎲 Cee-Lo — Game In Progress",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Roll until you get a scoring combo. Best score wins the pot!")
        return embed

    def _build_final_results_summary(self) -> str:
        """
        Build a summary of what each participant ended up with by the end of the round.
        This is used in final embeds so you can always see everyone's rolls.
        """
        lines = ["", "**Final Results:**"]
        for idx, member in enumerate(self.participants, start=1):
            base = f"{idx}. {member.mention}"

            if member.id in self.scores:
                s = self.scores[member.id]
                dice_str = self._format_dice(list(s["dice"]))
                extra = ""
                if s.get("auto_win"):
                    extra = " — **automatic win**"
                elif s.get("auto_lose"):
                    extra = " — **busted ❌**"
                lines.append(f"{base} — {dice_str} — {s['label']}{extra}")
            elif member.id in self.eliminated:
                # Fallback, in case eliminated but somehow not in scores
                lines.append(f"{base} — 🎲 [1, 2, 3] — 1-2-3 (automatic loss) — **busted ❌**")
            else:
                lines.append(f"{base} — ❔ Did not roll.")
        return "\n".join(lines)

    async def _refresh_message(self, interaction: discord.Interaction):
        """Update the lobby/game message based on current state."""
        if not self.message:
            return

        try:
            if not self.game_started:
                embed = self._build_lobby_embed()
            else:
                embed = self._build_game_embed()
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            logger.warning("Failed to edit Cee-Lo message.", exc_info=True)

    # ---------- Score evaluation ----------

    @staticmethod
    def _format_dice(dice):
        # e.g. 🎲 [4, 5, 6]
        return f"🎲 [{', '.join(str(d) for d in dice)}]"

    def _evaluate_roll(self, dice: list[int]):
        """
        Returns a score dict or None if it's a non-scoring roll that should be re-rolled.

        Score dict:
          {
            "category": int,   # higher is better
            "value": int,      # tie-breaker within category
            "dice": tuple,
            "label": str,
            "auto_win": bool,
            "auto_lose": bool,
          }
        """
        dice_sorted = sorted(dice)
        d1, d2, d3 = dice_sorted

        # Auto-lose: 1-2-3
        if dice_sorted == [1, 2, 3]:
            return {
                "category": -1,
                "value": 0,
                "dice": tuple(dice_sorted),
                "label": "1-2-3 (automatic loss)",
                "auto_win": False,
                "auto_lose": True,
            }

        # Auto-win: 4-5-6
        if dice_sorted == [4, 5, 6]:
            return {
                "category": 4,
                "value": 0,
                "dice": tuple(dice_sorted),
                "label": "4-5-6 (automatic win!)",
                "auto_win": True,
                "auto_lose": False,
            }

        # Triples
        if d1 == d2 == d3:
            # 6s > 5s > ... > 1s
            return {
                "category": 3,
                "value": d1,
                "dice": tuple(dice_sorted),
                "label": f"Triple {d1}s",
                "auto_win": False,
                "auto_lose": False,
            }

        # Pair + single: [X, X, point]
        if d1 == d2 or d2 == d3 or d1 == d3:
            if d1 == d2:
                point = d3
            elif d2 == d3:
                point = d1
            else:
                point = d2

            return {
                "category": 2,
                "value": point,  # 6 down to 1
                "dice": tuple(dice_sorted),
                "label": f"Point {point}",
                "auto_win": False,
                "auto_lose": False,
            }

        # Non-scoring roll (e.g., 2-3-5 that is not 1-2-3 or 4-5-6): roll again.
        return None

    @staticmethod
    def _compare_scores(score_a: dict, score_b: dict):
        """
        Compare two score dicts.
        Returns:
          >0 if A is better
           0 if equal
          <0 if B is better
        """
        if score_a["category"] != score_b["category"]:
            return score_a["category"] - score_b["category"]
        return score_a["value"] - score_b["value"]

    async def _update_richest_member_after_game(self, guild: discord.Guild = None):
        """
        Call back into GambleService to update the richest member role
        after a Cee-Lo game concludes.
        """
        if guild is None:
            return

        service = getattr(self.bot, "gamble_service", None)
        if service is None:
            logger.warning("gamble_service not found on bot when updating richest member.")
            return

        try:
            await service.update_richest_member_role(guild)
        except Exception:
            logger.error("Failed to update richest member role from Cee-Lo.", exc_info=True)

    # ---------- View lifecycle ----------

    async def on_timeout(self):
        # If lobby timed out before the game started, refund buy-ins.
        if not self.game_started:
            wallets = self._wallets()
            for member in self.participants:
                wallets[member.id] = wallets.get(member.id, 1000) + self.buy_in

        if self.message:
            try:
                embed = self.message.embeds[0] if self.message.embeds else self._build_lobby_embed()
                embed.set_footer(text="⏰ Cee-Lo lobby timed out.")
                await self.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        await self._update_richest_member_after_game(self.message.guild if self.message else None)
        self.stop()

    # ---------- Lobby Buttons ----------

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message(
                "The game has already started. You can't join now.",
                ephemeral=True
            )
            return

        user = interaction.user
        wallets = self._wallets()

        if user.id in self.participant_ids:
            await interaction.response.send_message(
                "You're already in this Cee-Lo lobby.",
                ephemeral=True
            )
            return

        balance = self._ensure_wallet(user.id)
        if balance < self.buy_in:
            await interaction.response.send_message(
                f"You don't have enough **Hog Coins** for this buy-in.\n"
                f"Required: 🪙 **{self.buy_in}**, Your balance: 🪙 **{balance}**",
                ephemeral=True
            )
            return

        # Deduct buy-in and add to pot
        wallets[user.id] -= self.buy_in
        self.pot += self.buy_in
        self.participants.append(user)
        self.participant_ids.append(user.id)

        if interaction.response.is_done():
            await interaction.followup.send(f"✅ You joined the Cee-Lo lobby for 🪙 **{self.buy_in}**.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"✅ You joined the Cee-Lo lobby for 🪙 **{self.buy_in}**.",
                ephemeral=True
            )

        await self._refresh_message(interaction)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if self.game_started:
            await interaction.response.send_message(
                "The game has already started.",
                ephemeral=True
            )
            return

        if user.id not in self.participant_ids:
            await interaction.response.send_message(
                "Only players who joined the lobby can start the game.",
                ephemeral=True
            )
            return

        if len(self.participants) < 2:
            await interaction.response.send_message(
                "You need at least **2 players** to start Cee-Lo.",
                ephemeral=True
            )
            return

        # Transition to game mode
        self.game_started = True
        self.current_index = 0

        # Replace lobby buttons with a single Roll button
        self.clear_items()

        roll_button = discord.ui.Button(
            label="🎲 Roll",
            style=discord.ButtonStyle.success
        )

        async def roll_cb(i: discord.Interaction):
            await self._handle_roll(i)

        roll_button.callback = roll_cb
        self.add_item(roll_button)

        await interaction.response.edit_message(embed=self._build_game_embed(), view=self)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if self.game_started:
            await interaction.response.send_message(
                "The game has already started; you can't leave now.",
                ephemeral=True
            )
            return

        if user.id not in self.participant_ids:
            await interaction.response.send_message(
                "You're not in this lobby.",
                ephemeral=True
            )
            return

        wallets = self._wallets()
        # Refund the buy-in for this lobby
        wallets[user.id] = wallets.get(user.id, 1000) + self.buy_in
        self.pot -= self.buy_in

        idx = self.participant_ids.index(user.id)
        del self.participant_ids[idx]
        del self.participants[idx]

        # If host leaves, end lobby and refund everyone else too
        if user.id == self.host.id:
            for member in self.participants:
                wallets[member.id] = wallets.get(member.id, 1000) + self.buy_in
            self.pot = 0
            self.clear_items()

            if interaction.response.is_done():
                await interaction.followup.send("Host left. Lobby has been closed and buy-ins refunded.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "Host left. Lobby has been closed and buy-ins refunded.",
                    ephemeral=True
                )

            if self.message:
                embed = self._build_lobby_embed()
                embed.set_footer(text="Lobby closed by host.")
                await self.message.edit(embed=embed, view=None)

            await self._update_richest_member_after_game(interaction.guild)
            self.stop()
            return

        # Non-host leaving
        if interaction.response.is_done():
            await interaction.followup.send("You left the Cee-Lo lobby. Your buy-in was refunded.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "You left the Cee-Lo lobby. Your buy-in was refunded.",
                ephemeral=True
            )

        await self._refresh_message(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.danger)
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        if user.id not in self.participant_ids:
            await interaction.response.send_message(
                "Only players in the lobby can end it.",
                ephemeral=True
            )
            return

        if self.game_started:
            await interaction.response.send_message(
                "You can't end the lobby once the game has started.",
                ephemeral=True
            )
            return

        # Require host to end the lobby
        if user.id != self.host.id:
            await interaction.response.send_message(
                "Only the host can end this lobby.",
                ephemeral=True
            )
            return

        # Refund everyone
        wallets = self._wallets()
        for member in self.participants:
            wallets[member.id] = wallets.get(member.id, 1000) + self.buy_in
        self.pot = 0

        self.clear_items()

        if interaction.response.is_done():
            await interaction.followup.send("Lobby ended by the host. All buy-ins refunded.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Lobby ended by the host. All buy-ins refunded.",
                ephemeral=True
            )

        if self.message:
            embed = self._build_lobby_embed()
            embed.set_footer(text="Lobby ended by host.")
            await self.message.edit(embed=embed, view=None)

        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    # ---------- Game logic (Roll handling) ----------

    async def _handle_roll(self, interaction: discord.Interaction):
        if not self.game_started:
            await interaction.response.send_message(
                "The game hasn't started yet.",
                ephemeral=True
            )
            return

        user = interaction.user

        if user.id not in self.participant_ids:
            await interaction.response.send_message(
                "Only players in this game can roll.",
                ephemeral=True
            )
            return

        # Enforce turn order
        current_player_id = self.participant_ids[self.current_index]
        if user.id != current_player_id:
            await interaction.response.send_message(
                "It's not your turn to roll.",
                ephemeral=True
            )
            return

        # If already busted or has a score, they shouldn't be rolling
        if user.id in self.eliminated or user.id in self.scores:
            await interaction.response.send_message(
                "You already completed your turn.",
                ephemeral=True
            )
            return

        dice = [random.randint(1, 6) for _ in range(3)]
        score = self._evaluate_roll(dice)

        # Non-scoring roll: roll again
        if score is None:
            msg = f"You rolled {self._format_dice(dice)} — no scoring combo. Roll again!"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

            await self._refresh_message(interaction)
            return

        # Auto-lose (1-2-3)
        if score["auto_lose"]:
            self.scores[user.id] = score
            self.eliminated.add(user.id)

            msg = f"You rolled {self._format_dice(dice)} — {score['label']}. You're out of contention for the pot."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

            # Advance to next player
            self.current_index += 1

            # If everyone busted with 1-2-3, refund all buy-ins
            if len(self.eliminated) == len(self.participants):
                await self._refund_all_and_finish(interaction, reason="Everyone rolled 1-2-3. Pot refunded.")
                return

            # If there are more players, continue; otherwise decide winner
            if self.current_index >= len(self.participants):
                await self._decide_winner_and_payout(interaction)
                return

            await self._refresh_message(interaction)
            return

        # Auto-win (4-5-6)
        if score["auto_win"]:
            self.scores[user.id] = score
            await self._auto_win_payout_and_finish(interaction, user, dice, score)
            return

        # Normal scoring (triples or point)
        self.scores[user.id] = score

        msg = f"You rolled {self._format_dice(dice)} — {score['label']}."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

        # Advance turn
        self.current_index += 1

        if self.current_index >= len(self.participants):
            await self._decide_winner_and_payout(interaction)
        else:
            await self._refresh_message(interaction)

    async def _auto_win_payout_and_finish(
        self,
        interaction: discord.Interaction,
        winner: discord.Member,
        dice: list[int],
        score: dict
    ):
        wallets = self._wallets()
        winner_balance = wallets.get(winner.id, 1000)
        wallets[winner.id] = winner_balance + self.pot

        # Record wallet history for all participants (if your GambleService supports this).
        try:
            self.bot.gamble_service.add_wallet_history_entry(
                winner.id, 
                wallets[winner.id],
                metadata = {
                    "game_source": GameSource.CEE_LO,
                    "update_type": UpdateType.BET_WON,
                    "pot_amount": self.pot,
                    "buy_in_amount": self.buy_in,
                }
            )
            for member in self.participants:
                if member.id != winner.id:
                    self.bot.gamble_service.add_wallet_history_entry(
                        member.id, 
                        wallets.get(member.id, 1000),
                        metadata = {
                            "game_source": GameSource.CEE_LO,
                            "update_type": UpdateType.BET_LOST,
                            "pot_amount": self.pot,
                            "buy_in_amount": self.buy_in,
                        }
                    )
        except Exception:
            logger.warning("Failed to record wallet history in _auto_win_payout_and_finish.", exc_info=True)

        desc = (
            f"{winner.mention} rolled {self._format_dice(dice)} — {score['label']}!\n\n"
            f"🎉 **Automatic win!** They take the pot of 🪙 **{self.pot}**."
        )

        # Append everyone's results to the final message
        desc += self._build_final_results_summary()

        embed = discord.Embed(
            title="🎲 Cee-Lo — Winner!",
            description=desc,
            color=discord.Color.green()
        )
        embed.set_footer(text="4-5-6 ends the round immediately.")

        self.clear_items()

        if interaction.response.is_done():
            await interaction.followup.send(
                f"{winner.mention} won the Cee-Lo game!",
                ephemeral=False
            )
        else:
            await interaction.response.send_message(
                f"{winner.mention} won the Cee-Lo game!",
                ephemeral=False
            )

        if self.message:
            await self.message.edit(embed=embed, view=None)

        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _refund_all_and_finish(self, interaction: discord.Interaction, reason: str):
        wallets = self._wallets()
        for member in self.participants:
            wallets[member.id] = wallets.get(member.id, 1000) + self.buy_in

        desc = reason
        desc += self._build_final_results_summary()

        embed = discord.Embed(
            title="🎲 Cee-Lo — No Winner",
            description=desc,
            color=discord.Color.orange()
        )
        embed.set_footer(text="All buy-ins have been refunded.")

        self.clear_items()

        if self.message:
            await self.message.edit(embed=embed, view=None)

        await self._update_richest_member_after_game(interaction.guild)
        self.stop()

    async def _decide_winner_and_payout(self, interaction: discord.Interaction):
        # If nobody has a score (unlikely due to rerolls) and some are not eliminated,
        # just refund everyone as a safety net.
        if not self.scores:
            await self._refund_all_and_finish(interaction, reason="No valid scoring rolls. Pot refunded.")
            return

        # Candidates are players with a score and not eliminated.
        candidates = [pid for pid in self.participant_ids if pid in self.scores and pid not in self.eliminated]
        if not candidates:
            await self._refund_all_and_finish(interaction, reason="No valid scoring rolls. Pot refunded.")
            return

        # Determine best score; tie-breaker is join order (earlier join wins tie).
        best_id = candidates[0]
        for pid in candidates[1:]:
            cmp = self._compare_scores(self.scores[pid], self.scores[best_id])
            if cmp > 0:
                best_id = pid
            elif cmp == 0:
                # tie on score: earlier join order (already preserved by best_id being earlier)
                continue

        winner = interaction.guild.get_member(best_id) if interaction.guild else None
        wallets = self._wallets()
        winner_balance = wallets.get(best_id, 1000)
        wallets[best_id] = winner_balance + self.pot

        # Record wallet history for everyone
        try:
            self.bot.gamble_service.add_wallet_history_entry(
                best_id, 
                wallets[best_id],
                metadata = {
                    "game_source": GameSource.CEE_LO,
                    "update_type": UpdateType.BET_WON,
                    "pot_amount": self.pot,
                    "buy_in_amount": self.buy_in,
                }
            )
            for member in self.participants:
                if member.id != best_id:
                    self.bot.gamble_service.add_wallet_history_entry(
                        member.id, 
                        wallets.get(member.id, 1000),
                        metadata = {
                            "game_source": GameSource.CEE_LO,
                            "update_type": UpdateType.BET_LOST,
                            "pot_amount": self.pot,
                            "buy_in_amount": self.buy_in,
                        }
                    )
        except Exception:
            logger.warning("Failed to record wallet history in _decide_winner_and_payout.", exc_info=True)

        score = self.scores[best_id]
        desc = (
            f"The round is over!\n\n"
            f"🏆 Winner: {winner.mention if winner else f'<@{best_id}>'}\n"
            f"Winning roll: {self._format_dice(list(score['dice']))} — {score['label']}\n\n"
            f"They win the pot of 🪙 **{self.pot}**."
        )

        # Append everyone's results to the final message
        desc += self._build_final_results_summary()

        embed = discord.Embed(
            title="🎲 Cee-Lo — Winner!",
            description=desc,
            color=discord.Color.green()
        )

        self.clear_items()

        if self.message:
            await self.message.edit(embed=embed, view=None)

        await self._update_richest_member_after_game(interaction.guild)
        self.stop()


class CeeLoService:
    def __init__(self, bot_state: BotState, bot):
        self.state = bot_state
        self.bot = bot

    def _wallets(self):
        if not hasattr(self.state, "member_wallets"):
            self.state.member_wallets = {}
        return self.state.member_wallets

    async def ceelo(self, interaction: discord.Interaction, buy_in: int):
        """
        Entry point for the /ceelo slash command.
        Creates a lobby and charges the host the initial buy-in.
        """
        if buy_in <= 0:
            msg = "Buy-in must be a positive number."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        wallets = self._wallets()
        host_id = interaction.user.id

        if host_id not in wallets:
            wallets[host_id] = 1000

        if wallets[host_id] < buy_in:
            msg = (
                f"You don't have enough **Hog Coins** to create this lobby.\n"
                f"Required: 🪙 **{buy_in}**, Your balance: 🪙 **{wallets[host_id]}**"
            )
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            # Deduct host buy-in up front
            wallets[host_id] -= buy_in

            view = CeeLoView(interaction.user, buy_in, self.state, self.bot)
            embed = view._build_lobby_embed()

            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
            view.channel = interaction.channel

            logger.info(f"User {interaction.user} started a Cee-Lo lobby with buy-in {buy_in}")
        except Exception:
            logger.error("Error starting Cee-Lo lobby", exc_info=True)
            error_msg = "An error occurred while starting the Cee-Lo lobby. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)


__all__ = ["CeeLoService"]
