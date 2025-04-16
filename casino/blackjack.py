import discord
from redbot.core import commands
import random

class BlackjackGame:
    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog  # 主模組（用來呼叫 get_balance/update_balance 等方法）
        self.bet = bet
        self.player_hand = []
        self.dealer_hand = []
        self.message = None

        # 預設建立牌組（也可在 start() 中重新建立）
        self.deck = []  # 這裡先不建構 deck

    def new_deck(self):
        """建立並洗牌一副新的52張撲克牌 (最後一個字元是 rank)"""
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        suits = ['♠', '♥', '♦', '♣']
        self.deck = [f"{suit}{rank}" for suit in suits for rank in ranks]
        random.shuffle(self.deck)

    def draw_card(self):
        """從牌組中抽一張牌，如果牌組用完則重新建立牌組"""
        if not self.deck:
            self.new_deck()
        return self.deck.pop()

    def card_value(self, card):
        """
        取得卡牌數值：只看最後一個字元 (rank)。
        - J, Q, K 的點數皆為 10；A 預設為 11（略過軟/硬 A 處理）。
        """
        rank = card[-1]
        if rank in ['J', 'Q', 'K']:
            return 10
        elif rank == 'A':
            return 11
        else:
            try:
                return int(rank)
            except ValueError:
                # 這不應該發生，但為了安全起見，打印錯誤並返回 0
                print(f"ValueError: 嘗試轉換無效的牌面值: '{rank}' (完整卡牌: '{card}')")
                return 0

    def hand_value(self, hand):
        total = sum(self.card_value(c) for c in hand)
        # 當總點數超過 21 時，將 A 的值從 11 調整為 1
        aces = sum(1 for c in hand if c[-1] == 'A')
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    async def start(self):
        # 每輪遊戲都建立一副新的牌組
        self.new_deck()
        # 先扣除下注金額
        await self.cog.update_balance(self.ctx.author, -self.bet)
        # 初始發牌：玩家發 2 張，莊家發 2 張（其中一張隱藏）
        self.player_hand = [self.draw_card(), self.draw_card()]
        self.dealer_hand = [self.draw_card(), self.draw_card()]
        embed = discord.Embed(
            title="21點遊戲 (最後字元為 Rank)",
            description=(
                f"你的牌: {', '.join(self.player_hand)} (總點數：{self.hand_value(self.player_hand)})\n"
                f"莊家的牌: {self.dealer_hand[0]}，未知牌。"
            ),
            color=discord.Color.blue()
        )
        view = BlackjackView(self)
        self.message = await self.ctx.send(embed=embed, view=view)

    async def update_message(self, view: discord.ui.View, extra_desc=""):
        embed = discord.Embed(
            title="21點遊戲",
            description=(
                f"你的牌: {', '.join(self.player_hand)} (總點數：{self.hand_value(self.player_hand)})\n"
                f"莊家的牌: {self.dealer_hand[0]}，未知牌。\n{extra_desc}"
            ),
            color=discord.Color.blue()
        )
        await self.message.edit(embed=embed, view=view)

class BlackjackView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game
        self.message: discord.Message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="叫牌", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.player_hand.append(self.game.draw_card())
        total = self.game.hand_value(self.game.player_hand)
        if total > 21:
            await self.game.update_message(self, extra_desc="你爆牌了！遊戲結束。")
            self.disable_all_items()
            await interaction.response.edit_message(view=self)
            self.stop()
        else:
            await self.game.update_message(self)
            await interaction.response.defer()

    @discord.ui.button(label="停牌", style=discord.ButtonStyle.grey)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        # 莊家抽牌直到總點數達 17
        dealer_total = self.game.hand_value(self.game.dealer_hand)
        while dealer_total < 17:
            self.game.dealer_hand.append(self.game.draw_card())
            dealer_total = self.game.hand_value(self.game.dealer_hand)
        player_total = self.game.hand_value(self.game.player_hand)
        result_desc = (
            f"莊家的牌: {', '.join(self.game.dealer_hand)} (總點數：{dealer_total})\n"
            f"你的點數：{player_total}\n"
        )
        if dealer_total > 21 or player_total > dealer_total:
            result_desc += "你贏了！"
            winnings = self.game.bet * 2
            await self.game.cog.update_balance(self.game.ctx.author, winnings)
        elif player_total == dealer_total:
            result_desc += "平手！退回下注。"
            await self.game.cog.update_balance(self.game.ctx.author, self.game.bet)
        else:
            result_desc += "你輸了。"
        await self.game.update_message(self, extra_desc=result_desc)
        self.stop()

    async def on_timeout(self) -> None:
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True