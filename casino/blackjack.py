import logging
import random
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Union

import discord
from redbot.core import commands


RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS = ['♠', '♥', '♦', '♣']

log = logging.getLogger("red.BadwolfCogs.casino.Blackjack")


class BlackjackGame:
    DECK_COUNT = 8

    def __init__(
        self,
        ctx: Union[commands.Context, discord.Interaction],
        cog,
        bet: int,
    ):
        self.ctx = ctx
        self.cog = cog
        self.bet = bet
        self.deck: List[str] = []
        self.dealer_hand: List[str] = []
        self.player_hands: List[List[str]] = []
        self.hand_bets: List[int] = []
        self.hand_doubled: List[bool] = []
        self.hand_done: List[bool] = []
        self.hand_results: List[Optional[dict]] = []
        self.current_hand_index = 0
        self.split_performed = False

        self.message: Optional[discord.Message] = None
        self.view: Optional[BlackjackView] = None
        self.phase = "playing"
        self._finalized = False

        self.blackjack_payout_multiplier = Decimal("1.5")
        self.five_card_charlie_payout_multiplier = Decimal("2.0")
        self.insurance_bet = 0
        self.insurance_profit = 0
        self.insurance_settled = False

    @property
    def current_hand(self) -> List[str]:
        return self.player_hands[self.current_hand_index]

    def build_deck(self) -> None:
        self.deck = [f"{s}{r}" for _ in range(self.DECK_COUNT) for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

    def draw(self) -> str:
        if not self.deck:
            self.build_deck()
        return self.deck.pop()

    @staticmethod
    def rank_of(card: str) -> str:
        return card[1:]

    @classmethod
    def value_of(cls, card: str) -> int:
        rank = cls.rank_of(card)
        if rank in {'J', 'Q', 'K'}:
            return 10
        if rank == 'A':
            return 11
        return int(rank)

    def calc_total(self, hand: List[str]) -> int:
        total = sum(self.value_of(c) for c in hand)
        aces = sum(1 for c in hand if self.rank_of(c) == 'A')
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def round_payout(self, bet: int, multiplier: Decimal) -> int:
        return int((Decimal(bet) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def is_natural_blackjack(self, hand: List[str]) -> bool:
        return len(hand) == 2 and self.calc_total(hand) == 21

    def dealer_has_blackjack(self) -> bool:
        return self.is_natural_blackjack(self.dealer_hand)

    def dealer_shows_ace(self) -> bool:
        return bool(self.dealer_hand) and self.rank_of(self.dealer_hand[0]) == 'A'

    def insurance_amount(self) -> int:
        return self.bet // 2

    async def start(self, ctx: Union[commands.Context, discord.Interaction] = None):
        if ctx is not None:
            self.ctx = ctx

        await self.cog.update_balance(self.ctx.author, -self.bet)
        self.build_deck()
        self._finalized = False
        self.phase = "insurance" if self.dealer_shows_ace() else "playing"
        self.split_performed = False
        self.current_hand_index = 0
        self.insurance_bet = 0
        self.insurance_profit = 0
        self.insurance_settled = False

        self.player_hands = [[self.draw(), self.draw()]]
        self.dealer_hand = [self.draw(), self.draw()]
        self.hand_bets = [self.bet]
        self.hand_doubled = [False]
        self.hand_done = [False]
        self.hand_results = [None]

        self.phase = "insurance" if self.dealer_shows_ace() else "playing"
        self.view = BlackjackView(self)
        self.message = await self.ctx.reply(
            embed=self.embed("🎴 **Blackjack 21點** 🎴", self.build_description()),
            view=self.view,
            mention_author=False,
        )

        if self.phase == "playing":
            await self.resolve_initial_blackjacks()

    def embed(self, title: str, desc: str, win: Optional[bool] = None) -> discord.Embed:
        if win is True:
            color = discord.Color.green()
        elif win is False:
            color = discord.Color.red()
        else:
            color = discord.Color.dark_grey()
        return discord.Embed(title=title, description=desc, color=color)

    def can_take_insurance(self) -> bool:
        return self.phase == "insurance" and self.insurance_amount() > 0 and self.insurance_bet == 0

    def can_split_current_hand(self) -> bool:
        if self.phase != "playing" or self.split_performed:
            return False
        hand = self.current_hand
        return len(hand) == 2 and self.value_of(hand[0]) == self.value_of(hand[1])

    def can_double_current_hand(self) -> bool:
        if self.phase != "playing" or self.split_performed:
            return False
        return len(self.current_hand) == 2 and not self.hand_doubled[self.current_hand_index]

    async def has_balance_for_extra_bet(self, amount: int) -> bool:
        return await self.cog.get_balance(self.ctx.author) >= amount

    async def update_message(self, notice: str = ""):
        if self._finalized or not self.message:
            return
        self.view = BlackjackView(self)
        await self.message.edit(
            embed=self.embed("🎴 **Blackjack 21點** 🎴", self.build_description(notice=notice)),
            view=self.view,
        )

    def build_description(self, reveal_dealer: bool = False, notice: str = "") -> str:
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🪙 本輪下注：{sum(self.hand_bets) + self.insurance_bet:,} 狗幣",
            f"規則：{self.DECK_COUNT} 副牌｜Blackjack 3:2 四捨五入｜莊家 Soft 17 停牌｜Split 一次",
        ]
        if self.insurance_bet:
            lines.append(f"🛡️ 保險下注：{self.insurance_bet:,} 狗幣")
        if notice:
            lines.append(f"📢 {notice}")

        lines.extend(["", "🧑 你的手牌："])
        for idx, hand in enumerate(self.player_hands):
            marker = "▶ " if idx == self.current_hand_index and not self.hand_done[idx] and self.phase == "playing" else ""
            result = self.hand_results[idx]
            status = result["label"] if result else ("等待莊家結算" if self.hand_done[idx] else "進行中")
            doubled = "｜已雙倍" if self.hand_doubled[idx] else ""
            lines.append(
                f"{marker}手牌 {idx + 1}：{'  '.join(hand)}（{self.calc_total(hand)}）"
                f"｜下注 {self.hand_bets[idx]:,}{doubled}｜{status}"
            )

        dealer_cards = "  ".join(self.dealer_hand) if reveal_dealer else f"{self.dealer_hand[0]}  ??"
        dealer_total = self.calc_total(self.dealer_hand) if reveal_dealer else "?"
        lines.extend([
            "",
            "🃏 莊家的手牌：",
            dealer_cards,
            f"🧮 莊家點數：**{dealer_total}**",
            "━━━━━━━━━━━━━━━━━━━━",
        ])
        return "\n".join(lines)

    async def resolve_initial_blackjacks(self, notice: str = ""):
        if self._finalized:
            return

        dealer_blackjack = self.dealer_has_blackjack()
        player_blackjack = self.is_natural_blackjack(self.player_hands[0])
        self.settle_insurance(dealer_blackjack)

        if dealer_blackjack:
            if player_blackjack:
                self.hand_results[0] = {"profit": 0, "label": "Blackjack 平手"}
            else:
                self.hand_results[0] = {"profit": -self.hand_bets[0], "label": "莊家 Blackjack"}
            self.hand_done[0] = True
            await self.finalize("莊家 Blackjack。")
            return

        if player_blackjack:
            payout = self.round_payout(self.hand_bets[0], self.blackjack_payout_multiplier)
            self.hand_results[0] = {"profit": payout, "label": "自然 Blackjack"}
            self.hand_done[0] = True
            await self.finalize("玩家擁有自然 Blackjack，獲勝！")
            return

        await self.update_message(notice)

    def settle_insurance(self, dealer_blackjack: bool):
        if self.insurance_settled:
            return
        if self.insurance_bet:
            self.insurance_profit = self.insurance_bet * 2 if dealer_blackjack else -self.insurance_bet
        self.insurance_settled = True

    async def take_insurance(self):
        amount = self.insurance_amount()
        if amount <= 0:
            await self.update_message("目前下注無法購買保險。")
            return
        if not await self.has_balance_for_extra_bet(amount):
            await self.update_message("餘額不足，無法購買保險。")
            return

        await self.cog.update_balance(self.ctx.author, -amount)
        self.insurance_bet = amount
        self.phase = "playing"
        await self.resolve_initial_blackjacks("已購買保險。")

    async def decline_insurance(self):
        self.phase = "playing"
        await self.resolve_initial_blackjacks("未購買保險。")

    async def take_even_money(self):
        self.hand_results[0] = {"profit": self.bet, "label": "Even Money"}
        self.hand_done[0] = True
        self.phase = "playing"
        self.insurance_settled = True
        await self.finalize("玩家選擇 Even Money，獲得 1:1 派彩。")

    async def decline_even_money(self):
        self.phase = "playing"
        await self.resolve_initial_blackjacks("未選擇 Even Money。")

    async def hit_current_hand(self):
        hand = self.current_hand
        hand.append(self.draw())
        total = self.calc_total(hand)

        if total > 21:
            stake = self.hand_bets[self.current_hand_index]
            self.hand_results[self.current_hand_index] = {"profit": -stake, "label": "爆牌"}
            self.hand_done[self.current_hand_index] = True
            await self.finish_turn("你爆牌了。")
            return

        if len(hand) >= 5:
            stake = self.hand_bets[self.current_hand_index]
            payout = self.round_payout(stake, self.five_card_charlie_payout_multiplier)
            self.hand_results[self.current_hand_index] = {"profit": payout, "label": "五龍勝利"}
            self.hand_done[self.current_hand_index] = True
            await self.finish_turn("五龍勝利。")
            return

        await self.update_message()

    async def stand_current_hand(self, notice: str = "停牌。"):
        self.hand_done[self.current_hand_index] = True
        await self.finish_turn(notice)

    async def double_current_hand(self):
        if not self.can_double_current_hand():
            await self.update_message("目前不能雙倍下注。")
            return
        if not await self.has_balance_for_extra_bet(self.bet):
            await self.update_message("餘額不足，無法雙倍下注。")
            return

        await self.cog.update_balance(self.ctx.author, -self.bet)
        idx = self.current_hand_index
        self.hand_bets[idx] += self.bet
        self.hand_doubled[idx] = True
        self.player_hands[idx].append(self.draw())

        total = self.calc_total(self.player_hands[idx])
        if total > 21:
            self.hand_results[idx] = {"profit": -self.hand_bets[idx], "label": "雙倍後爆牌"}
        self.hand_done[idx] = True
        await self.finish_turn("已雙倍下注。")

    async def split_current_hand(self):
        if not self.can_split_current_hand():
            await self.update_message("目前不能分牌。")
            return
        if not await self.has_balance_for_extra_bet(self.bet):
            await self.update_message("餘額不足，無法分牌。")
            return

        await self.cog.update_balance(self.ctx.author, -self.bet)
        first, second = self.current_hand
        self.player_hands = [[first, self.draw()], [second, self.draw()]]
        self.hand_bets = [self.bet, self.bet]
        self.hand_doubled = [False, False]
        self.hand_done = [False, False]
        self.hand_results = [None, None]
        self.current_hand_index = 0
        self.split_performed = True
        await self.update_message("已分牌。")

    async def finish_turn(self, notice: str = ""):
        if self._finalized:
            return

        for idx in range(self.current_hand_index + 1, len(self.player_hands)):
            if not self.hand_done[idx]:
                self.current_hand_index = idx
                await self.update_message(notice)
                return

        if any(result is None for result in self.hand_results):
            self.play_dealer_hand()
            self.settle_stood_hands()

        await self.finalize(notice or "遊戲結束。")

    def play_dealer_hand(self):
        while self.calc_total(self.dealer_hand) < 17:
            self.dealer_hand.append(self.draw())

    def settle_stood_hands(self):
        dealer_total = self.calc_total(self.dealer_hand)
        for idx, result in enumerate(self.hand_results):
            if result is not None:
                continue

            player_total = self.calc_total(self.player_hands[idx])
            stake = self.hand_bets[idx]
            if dealer_total > 21 or player_total > dealer_total:
                self.hand_results[idx] = {"profit": stake, "label": "勝利"}
            elif player_total == dealer_total:
                self.hand_results[idx] = {"profit": 0, "label": "平手"}
            else:
                self.hand_results[idx] = {"profit": -stake, "label": "落敗"}
            self.hand_done[idx] = True

    async def resolve_timeout(self):
        if self._finalized:
            return

        if self.phase == "insurance":
            self.phase = "playing"
            await self.resolve_initial_blackjacks("保險 / Even Money 選擇逾時。")
            return

        for idx, done in enumerate(self.hand_done):
            if not done:
                self.hand_done[idx] = True
        await self.finish_turn("超時停牌。")

    async def finalize(self, result: str):
        if self._finalized:
            log.warning(f"Attempted to finalize already finished blackjack game for {self.ctx.author.id}")
            return
        self._finalized = True

        if self.insurance_bet and not self.insurance_settled:
            self.settle_insurance(self.dealer_has_blackjack())

        total_bet = sum(self.hand_bets) + self.insurance_bet
        hand_profit = sum(result_data["profit"] for result_data in self.hand_results if result_data)
        total_profit = hand_profit + self.insurance_profit

        return_amount = 0
        for stake, result_data in zip(self.hand_bets, self.hand_results):
            profit = result_data["profit"] if result_data else -stake
            if profit >= 0:
                return_amount += stake + profit
        if self.insurance_bet and self.insurance_profit >= 0:
            return_amount += self.insurance_bet + self.insurance_profit

        if return_amount > 0:
            await self.cog.update_balance(self.ctx.author, return_amount)

        await self.cog.stats_db.update_stats(
            self.ctx.author.id,
            game_type="blackjack",
            bet=total_bet,
            profit=total_profit,
        )

        total_balance = await self.cog.get_balance(self.ctx.author)
        insurance_line = ""
        if self.insurance_bet:
            insurance_line = f"🛡️ 保險盈虧：{self.insurance_profit:+,} 狗幣\n"

        desc = (
            f"{self.build_description(reveal_dealer=True)}\n"
            f"📢 結果：{result}\n"
            f"{insurance_line}"
            f"💰 本輪盈虧：{total_profit:+,} 狗幣\n"
            f"💼 目前總餘額：{int(total_balance):,} 狗幣\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        embed = self.embed("🏁 **遊戲結束** 🏁", desc, total_profit > 0 if total_profit != 0 else None)
        if self.message:
            await self.message.edit(embed=embed, view=None)
        else:
            await self.ctx.send(embed=embed)
        self.cleanup()

    def cleanup(self):
        self.cog.end_game(self.ctx.author.id)
        if self.view:
            self.view.stop()


class BlackjackView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game

        if game.phase == "insurance":
            self.remove_item(self.hit)
            self.remove_item(self.stand)
            self.remove_item(self.double)
            self.remove_item(self.split)
            if game.is_natural_blackjack(game.player_hands[0]):
                self.remove_item(self.insurance)
                self.remove_item(self.no_insurance)
            else:
                self.remove_item(self.even_money)
                self.remove_item(self.decline_even_money)
                if not game.can_take_insurance():
                    self.insurance.disabled = True
        else:
            self.remove_item(self.insurance)
            self.remove_item(self.no_insurance)
            self.remove_item(self.even_money)
            self.remove_item(self.decline_even_money)
            self.double.disabled = not game.can_double_current_hand()
            self.split.disabled = not game.can_split_current_hand()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        if self.game._finalized:
            await interaction.response.send_message("遊戲已經結束。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="叫牌", style=discord.ButtonStyle.green, custom_id="hit")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.hit_current_hand()

    @discord.ui.button(label="停牌", style=discord.ButtonStyle.grey, custom_id="stand")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.stand_current_hand()

    @discord.ui.button(label="雙倍下注", style=discord.ButtonStyle.blurple, custom_id="double")
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.double_current_hand()

    @discord.ui.button(label="分牌", style=discord.ButtonStyle.green, custom_id="split")
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.split_current_hand()

    @discord.ui.button(label="買保險", style=discord.ButtonStyle.blurple, custom_id="insurance")
    async def insurance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.take_insurance()

    @discord.ui.button(label="不買保險", style=discord.ButtonStyle.grey, custom_id="no_insurance")
    async def no_insurance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.decline_insurance()

    @discord.ui.button(label="Even Money", style=discord.ButtonStyle.blurple, custom_id="even_money")
    async def even_money(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.take_even_money()

    @discord.ui.button(label="繼續開牌", style=discord.ButtonStyle.grey, custom_id="decline_even_money")
    async def decline_even_money(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.game.decline_even_money()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.game.message and not self.game._finalized:
            try:
                await self.game.message.edit(view=self)
            except discord.HTTPException:
                pass
        await self.game.resolve_timeout()
