import discord
from redbot.core import commands
import random
from typing import Union
import time

class SlotGame:
    EMOJIS = [":skull:", ":cherries:", ":lemon:", ":grapes:", ":watermelon:", ":seven:"]

    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog  # 主模組，提供更新餘額等方法
        self.bet = bet
        self.message: discord.Message = None
        self.view = SlotView(self)  # 單一 View 實例，避免多次建立造成重複超時
        self.payouts = {
            "three_same": {
                ":cherries:": 0.5,
                ":lemon:": 1,
                ":grapes:": 5,
                ":watermelon:": 10,
                ":seven:": 30,
            },
            "two_same": {
                ":cherries:": 0.2,
                ":lemon:": 0.5,
                ":grapes:": 1,
                ":watermelon:": 2,
                ":seven:": 5,
            },
        }
        self.emoji_weights = {
            ":skull:": 28,
            ":cherries:": 30,
            ":lemon:": 25,
            ":grapes:": 20,
            ":watermelon:": 15,
            ":seven:": 5,
        }
        self.last_spin_time: dict[int, float] = {}
        self.spin_cooldown = 5  # 冷卻秒數
        self.total_profit = -self.bet
        self.ended = False  # 標記遊戲是否已結束

    async def start(self, ctx: Union[commands.Context, discord.Interaction] = None):
        if ctx:
            self.ctx = ctx

        # 扣款並顯示初始訊息
        await self.cog.update_balance(self.ctx.author, -self.bet)
        embed = discord.Embed(
            title="拉霸遊戲",
            description=f"下注金額：{self.bet}\n按下按鈕開始拉霸或結束遊戲！",
            color=discord.Color.gold()
        )
        self.message = await self.ctx.send(embed=embed, view=self.view)

    async def update_message(self, result_desc: str):
        embed = discord.Embed(
            title="拉霸遊戲",
            description=result_desc,
            color=discord.Color.gold()
        )
        if self.message:
            await self.message.edit(embed=embed)
        else:
            self.message = await self.ctx.send(embed=embed, view=self.view)

class SlotView(discord.ui.View):
    def __init__(self, game: SlotGame):
        super().__init__(timeout=30)
        self.game = game
        self.spin_button = discord.ui.Button(label="Spin", style=discord.ButtonStyle.blurple)
        self.spin_button.callback = self.spin
        self.end_button = discord.ui.Button(label="結束", style=discord.ButtonStyle.red)
        self.end_button.callback = self.end_game
        self.add_item(self.spin_button)
        self.add_item(self.end_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        return True

    async def spin(self, interaction: discord.Interaction):
        if self.game.ended:
            await interaction.response.send_message("遊戲已結束，無法再拉霸。", ephemeral=True)
            return

        user_id = interaction.user.id
        now = time.time()
        # 冷卻檢查
        last = self.game.last_spin_time.get(user_id, 0)
        if now - last < self.game.spin_cooldown:
            await interaction.response.send_message(
                f"請稍後再試！冷卻時間剩 {self.game.spin_cooldown - (now - last):.1f} 秒。",
                ephemeral=True
            )
            return

        balance = await self.game.cog.get_balance(interaction.user)
        if balance < self.game.bet:
            await interaction.response.send_message(
                f"籌碼不足！本次需 {self.game.bet}，但你只有 {balance}。",
                ephemeral=True
            )
            return

        # 扣款並記錄時間
        self.game.last_spin_time[user_id] = now
        await interaction.response.defer(ephemeral=True)

        # 隨機轉盤結果
        emojis = list(self.game.emoji_weights.keys())
        weights = list(self.game.emoji_weights.values())
        result = random.choices(emojis, weights=weights, k=3)
        rstr = " ".join(result)
        winnings = 0
        parts = [f"下注金額：{self.game.bet}", rstr]

        # 處理結果
        if result.count(":skull:") >= 2:
            parts.append("出現內務部！損失下注。")
            winnings = -self.game.bet
        elif result.count(result[0]) == 3:
            mul = self.game.payouts["three_same"].get(result[0], 0)
            winnings = int(self.game.bet * (1 + mul))
            parts.append(f"恭喜中大獎：獲得 {winnings}。")
        else:
            for e in SlotGame.EMOJIS:
                if result.count(e) == 2:
                    mul2 = self.game.payouts["two_same"].get(e, 0)
                    winnings = int(self.game.bet * (1 + mul2))
                    parts.append(f"部分中獎：獲得 {winnings}。")
                    break
            else:
                parts.append("未中獎。")
                winnings = -self.game.bet

        # 更新盈虧與餘額
        self.game.total_profit += winnings
        await self.game.cog.update_balance(self.game.ctx.author, winnings)
        new_bal = await self.game.cog.get_balance(self.game.ctx.author)
        parts.extend([f"總盈虧：{self.game.total_profit:,}", f"總籌碼：{new_bal:,}"])

        await self.game.update_message("\n".join(parts))

    async def end_game(self, interaction: discord.Interaction):
        self.game.ended = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=None)
        await interaction.followup.send("你已結束遊戲。", ephemeral=True)
        self.game.cog.end_game(self.game.ctx.author.id)
        self.stop()

    async def on_timeout(self):
        if self.game.ended:
            return
        for item in self.children:
            item.disabled = True
        if self.game.message:
            await self.game.message.edit(view=None)
        refund = self.game.bet
        await self.game.cog.update_balance(self.game.ctx.author, refund)
        bal = await self.game.cog.get_balance(self.game.ctx.author)
        await self.game.ctx.send(
            f"{self.game.ctx.author.mention} 遊戲超時，退回 {refund}。\n目前籌碼: {bal}"
        )
        self.game.cog.end_game(self.game.ctx.author.id)
