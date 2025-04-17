import discord
from redbot.core import commands
import random
import logging
from typing import List, Optional, Union

# 全域牌組模板
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'J', 'Q', 'K', 'A']
SUITS = ['♠', '♥', '♦', '♣']

log = logging.getLogger("red.BadwolfCogs.casino.Blackjack")

class BlackjackGame:
    def __init__(
        self,
        ctx: Union[commands.Context, discord.Interaction],
        cog,
        bet: int,
        double_totals: Optional[List[int]] = None
    ):
        # 初始時必填 ctx（Context 或者 Interaction）
        self.ctx = ctx
        self.cog = cog
        self.bet = bet
        self.double_totals = double_totals or [11]
        self.player_hand: List[str] = []
        self.dealer_hand: List[str] = []
        self.deck: List[str] = []
        self.message: Optional[discord.Message] = None
        self.doubled = False
        #賠率
        self.blackjack_payout_multiplier = 1.5
        self.double_win_multiplier = 1.0 # 原始為 2.0，修改成 1 + 倍率後，淨贏是 1 倍
        self.five_card_charlie_payout_multiplier = 2.0 # 原始為 2.0，修改成 1 + 倍率後，淨贏是 1 倍

    def build_deck(self) -> None:
        self.deck = [f"{s}{r}" for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

    def draw(self) -> str:
        if not self.deck:
            self.build_deck()
        return self.deck.pop()

    @staticmethod
    def value_of(card: str) -> int:
        r = card[-1]
        if r in 'JQK':
            return 10
        if r == 'A':
            return 11
        return int(r)

    def calc_total(self, hand: List[str]) -> int:
        total = sum(self.value_of(c) for c in hand)
        aces = sum(1 for c in hand if c[-1] == 'A')
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def embed(self, title: str, desc: str, win: Optional[bool] = None) -> discord.Embed:
        if win is True:
            color = discord.Color.green()
        elif win is False:
            color = discord.Color.red()
        else:
            color = discord.Color.dark_grey()
        return discord.Embed(title=title, description=desc, color=color)

    async def start(self, ctx: Union[commands.Context, discord.Interaction] = None):
        """開始遊戲。可選傳入新的 Context/Interaction 來覆寫 self.ctx。"""
        if ctx is not None:
            self.ctx = ctx  # 支援 on_message 的 interaction 或 command ctx

        # 扣款與初始牌，顯示下注
        await self.cog.update_balance(self.ctx.author, -self.bet)
        self.build_deck()
        self.doubled = False
        self.player_hand = [self.draw(), self.draw()]
        self.dealer_hand = [self.draw(), self.draw()]

        desc = (
            f"本輪下注: {self.bet} 狗幣\n\n"
            f"你的牌:\n `{'  '.join(self.player_hand)}` \n你的點數: {self.calc_total(self.player_hand)}\n\n"
            f"莊家:\n `{self.dealer_hand[0]}  ??`"
        )
        view = BlackjackView(self)
        embed = self.embed("21 點遊戲", desc)
        self.message = await self.ctx.send(embed=embed, view=view)

        # 如果有自然 Blackjack，就結算並清理
        if await self.check_blackjack():
            await self.message.edit(embed=embed, view=None)
            self.cleanup()
            return

    async def check_blackjack(self) -> bool:
        p_tot = self.calc_total(self.player_hand)
        d_tot = self.calc_total(self.dealer_hand)

        if p_tot == 21 or d_tot == 21:
            if p_tot == d_tot:
                msg, round_delta, win = "平手，退回下注。", 0, None
                await self.cog.update_balance(self.ctx.author, self.bet)
            elif p_tot == 21:
                payout = int(self.bet * self.blackjack_payout_multiplier)
                msg, round_delta, win = f"玩家 Blackjack！", payout, True
                await self.cog.update_balance(self.ctx.author, self.bet + payout)
            else:
                msg, round_delta, win = "莊家 Blackjack，你輸了。", -self.bet, False
                await self.cog.update_balance(self.ctx.author, -self.bet)

            total_balance = await self.cog.get_balance(self.ctx.author)
            desc = (
                f"本輪下注: {self.bet} 狗幣\n\n"
                f"你的牌:\n `{'  '.join(self.player_hand)}` ({p_tot})\n\n"
                f"莊家牌:\n `{'  '.join(self.dealer_hand)}` ({d_tot})\n\n"
                f"{msg}\n"
                f"本輪盈虧: {round_delta:+} 狗幣\n"
                f"總狗幣: {round(total_balance):,}"
            )
            await self.ctx.send(embed=self.embed("遊戲結算", desc, win))
            return True
        return False

    async def finalize(self, result: str, win: Optional[bool] = None, payout: int = 0):
        """當玩家停牌或爆牌後的最終結算。"""
        if win is True:
            await self.cog.update_balance(self.ctx.author, self.bet + payout)
            round_delta = payout
        elif win is None:
            await self.cog.update_balance(self.ctx.author, self.bet)
            round_delta = 0
        else:
            round_delta = -self.bet

        total_balance = await self.cog.get_balance(self.ctx.author)
        desc = (
            f"本輪下注: {self.bet} 狗幣\n\n"
            f"你的牌:\n `{'  '.join(self.player_hand)}` \n你的點數: {self.calc_total(self.player_hand)}\n\n"
            f"莊家牌:\n `{'  '.join(self.dealer_hand)}` \n莊家的點數: {self.calc_total(self.dealer_hand)}\n\n"
            f"{result}\n"
            f"本輪盈虧: {round_delta:+} 狗幣\n"
            f"總狗幣: {round(total_balance):,}"
        )
        embed = self.embed("遊戲結束", desc, win)
        if self.message:
            await self.message.edit(embed=embed, view=None)
        else:
            await self.ctx.send(embed=embed)

        self.cleanup()

    def cleanup(self):
        """遊戲結束時呼叫：移除 active_games 鎖定"""
        self.cog.end_game(self.ctx.author.id)


class BlackjackView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game
        # 初始化時處理雙倍下注按鈕是否可用
        for item in self.children:
            if getattr(item, 'custom_id', None) == 'double':
                total = self.game.calc_total(self.game.player_hand)
                item.disabled = not (len(self.game.player_hand) == 2 and total in self.game.double_totals)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="叫牌", style=discord.ButtonStyle.green, custom_id="hit")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.player_hand.append(self.game.draw())
        total = self.game.calc_total(self.game.player_hand)
        if total > 21:
            await self.game.finalize("你爆牌了！", win=False)
            self.stop()
        elif len(self.game.player_hand) >= 5 and total <= 21:
            payout = int(self.game.bet * self.game.five_card_charlie_payout_multiplier)
            await self.game.finalize(f"五龍勝利！", win=True, payout=payout)
            self.stop()
        else:
            desc = (
                f"本輪下注: {self.game.bet} 狗幣\n\n"
                f"你的牌:\n `{'  '.join(self.game.player_hand)}` \n你的點數: {self.game.calc_total(self.game.player_hand)}\n\n"
                f"莊家:\n `{self.game.dealer_hand[0]}  ??`"
            )
            await interaction.response.edit_message(embed=self.game.embed("21 點遊戲", desc), view=self)

    @discord.ui.button(label="停牌", style=discord.ButtonStyle.grey, custom_id="stand")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.dealer_play(interaction)
        self.stop()

    @discord.ui.button(label="雙倍下注", style=discord.ButtonStyle.blurple, custom_id="double")
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.doubled:
            await interaction.response.send_message("已執行雙倍下注！", ephemeral=True)
            return
        bal = await self.game.cog.get_balance(self.game.ctx.author)
        if bal < self.game.bet:
            await interaction.response.send_message("餘額不足，無法雙倍下注！", ephemeral=True)
            return
        self.game.doubled = True
        await self.game.cog.update_balance(self.game.ctx.author, -self.game.bet)
        self.game.player_hand.append(self.game.draw())
        total = self.game.calc_total(self.game.player_hand)
        if total > 21:
            await self.game.finalize("雙倍後爆牌！", win=False)
        else:
            await self.dealer_play(interaction, extra="(已雙倍下注)")
        self.stop()

    async def dealer_play(self, interaction: discord.Interaction, extra: str = ""):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        while self.game.calc_total(self.game.dealer_hand) < 17:
            self.game.dealer_hand.append(self.game.draw())

        p_tot = self.game.calc_total(self.game.player_hand)
        d_tot = self.game.calc_total(self.game.dealer_hand)

        if d_tot > 21 or p_tot > d_tot:
            payout = self.game.bet * (self.game.double_win_multiplier if self.game.doubled else 1)
            await self.game.finalize(f"你贏了！{extra}", win=True, payout=payout)
        elif p_tot == d_tot:
            await self.game.finalize("平手，退回下注。", win=None)
        else:
            await self.game.finalize("你輸了。", win=False)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.game.message:
            await self.game.message.edit(view=None)
        # 退還下注
        refund_multiplier = 2 if self.game.doubled else 1
        refund = self.game.bet * refund_multiplier
        await self.game.cog.update_balance(self.game.ctx.author, refund)
        await self.game.ctx.send(
            f"{self.game.ctx.author.mention} 遊戲超時，退回下注 {refund} 狗幣。\n"
            f"目前總狗幣: {round(await self.game.cog.get_balance(self.game.ctx.author)):,}"
        )
        self.game.cleanup()