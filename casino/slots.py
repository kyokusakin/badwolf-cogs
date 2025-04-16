import discord
from redbot.core import commands
import random

class SlotGame:
    EMOJIS = [":cherries:", ":lemon:", ":grapes:", ":watermelon:", ":seven:"]

    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog  # 主模組，提供更新餘額等方法
        self.bet = bet
        self.message = None

    async def start(self):
        # 直接扣除下注金額
        await self.cog.update_balance(self.ctx.author, -self.bet)
        embed = discord.Embed(
            title="拉霸遊戲",
            description="按下下面按鈕開始拉霸！",
            color=discord.Color.gold()
        )
        view = SlotView(self)
        self.message = await self.ctx.send(embed=embed, view=view)

    async def update_message(self, result_desc: str):
        embed = discord.Embed(
            title="拉霸遊戲",
            description=result_desc,
            color=discord.Color.gold()
        )
        await self.message.edit(embed=embed, view=None)

class SlotView(discord.ui.View):
    def __init__(self, game: SlotGame):
        super().__init__(timeout=30)
        self.game = game
        self.spin_button = discord.ui.Button(label="Spin", style=discord.ButtonStyle.blurple)
        self.spin_button.callback = self.spin
        self.add_item(self.spin_button)

    async def spin(self, interaction: discord.Interaction):
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return

        # 禁用按鈕防止重複點擊
        self.spin_button.disabled = True
        await interaction.response.edit_message(view=self)

        # 隨機選出三個符號
        result = [random.choice(self.game.EMOJIS) for _ in range(3)]
        result_str = " ".join(result)
        winnings = 0

        if result.count(result[0]) == 3:
            result_desc = f"{result_str}\n恭喜中大獎！你獲得 {self.game.bet * 3} 的獎金。"
            winnings = self.game.bet * 3
        elif any(result.count(emoji) == 2 for emoji in self.game.EMOJIS):
            result_desc = f"{result_str}\n部分中獎！退回下注金額 {self.game.bet}。"
            winnings = self.game.bet
        else:
            result_desc = f"{result_str}\n未中獎。"

        await self.game.cog.update_balance(self.game.ctx.author, winnings)
        await self.game.update_message(result_desc)
        self.stop()

    async def on_timeout(self) -> None:
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)