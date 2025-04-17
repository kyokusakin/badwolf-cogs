import discord
from redbot.core import commands
import random
from typing import List, Optional, Union
import time
import asyncio

class SlotGame:
    EMOJIS = [":skull:", ":cherries:", ":lemon:", ":grapes:", ":watermelon:", ":seven:"]

    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog  # 主模組，提供更新餘額等方法
        self.bet = bet
        self.message = None
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
        self.last_spin_time = {}  # Store last spin time for each user ID
        self.spin_cooldown = 5  # Set the cooldown in seconds
        self.total_profit = -self.bet

    async def start(self, ctx: Union[commands.Context, discord.Interaction] = None):
        if ctx is not None:
            self.ctx = ctx

        # 扣款與初始牌，顯示下注
        await self.cog.update_balance(self.ctx.author, -self.bet)
        embed = discord.Embed(
            title="拉霸遊戲",
            description=f"下注金額：{self.bet}\n按下按鈕開始拉霸或結束遊戲！",
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
        if self.message:
            view = SlotView(self) # Re-create the view with both buttons
            await self.message.edit(embed=embed, view=view)
        else:
            view = SlotView(self)
            self.message = await self.ctx.send(embed=embed, view=view)

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
        self.message: discord.Message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        return True

    async def spin(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        current_time = time.time()

        if user_id in self.game.last_spin_time and current_time - self.game.last_spin_time[user_id] < self.game.spin_cooldown:
            remaining_time = self.game.spin_cooldown - (current_time - self.game.last_spin_time[user_id])
            await interaction.response.send_message(f"請稍後再試！冷卻時間還剩 {remaining_time:.1f} 秒。", ephemeral=True)
            return

        current_balance = await self.game.cog.get_balance(interaction.user)
        if current_balance < self.game.bet:
            await interaction.response.send_message(f"你的籌碼不足！本次下注需要 {self.game.bet} 籌碼，但你只有 {current_balance} 籌碼。", ephemeral=True)
            return

        self.game.last_spin_time[user_id] = current_time

        await interaction.response.defer(ephemeral=True)  # 顯示「正在思考」並防止觀眾看到
        await interaction.message.edit(view=self)  # 更新消息，這是第一次回應

        # 隨機選出三個符號
        emojis = list(self.game.emoji_weights.keys())
        weights = list(self.game.emoji_weights.values())
        result = random.choices(emojis, weights=weights, k=3)
        result_str = " ".join(result)
        winnings = 0
        result_desc_parts = [f"下注金額：{self.game.bet}", result_str]

        # Check for three of the same
        if result.count(":skull:") >= 2:
            result_desc_parts.append("出現內務部！你損失了下注金額。")
            winnings = -self.game.bet
        elif result.count(result[0]) == 3:
            emoji = result[0]
            if emoji in self.game.payouts["three_same"]:
                multiplier = self.game.payouts["three_same"][emoji]
                winnings = self.game.bet * (1 + multiplier)
                result_desc_parts.append(f"恭喜中大獎！你獲得 {winnings} 倍 ({winnings}) 的獎金。")
            else:
                result_desc_parts.append("發生錯誤：未知的賠率設定 (三個相同)。")
        else:
            # Check for two of the same
            for emoji in self.game.EMOJIS:
                if result.count(emoji) == 2:
                    if emoji in self.game.payouts["two_same"]:
                        multiplier = self.game.payouts["two_same"][emoji]
                        winnings = self.game.bet * (1 + multiplier)
                        result_desc_parts.append(f"部分中獎！你獲得 {multiplier} 倍 ({winnings}) 的獎金。")
                        break  # Stop after finding the first pair
            else:
                result_desc_parts.append("未中獎。")
                winnings = -self.game.bet  # No winnings, deduct the bet

        self.game.total_profit += winnings
        await self.game.cog.update_balance(self.game.ctx.author, winnings)
        current_balance = await self.game.cog.get_balance(interaction.user)

        result_desc_parts.append(f"總盈虧：{self.game.total_profit}")
        result_desc_parts.append(f"總籌碼：{current_balance}")

        await self.game.update_message("\n".join(result_desc_parts))
        await interaction.message.edit(view=self)


    async def end_game(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("你已結束拉霸遊戲。")
        self.cleanup()
        self.stop()

    def cleanup(self):
        self.game.cog.end_game(self.game.ctx.author.id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.game.message:
            await self.game.message.edit(view=None)
        refund = self.game.bet
        await self.game.cog.update_balance(self.game.ctx.author, refund)
        await self.game.ctx.send(
            f"{self.game.ctx.author.mention} 遊戲超時，退回下注 {refund} 狗幣。\n"
            f"目前總狗幣: {round(await self.game.cog.get_balance(self.game.ctx.author)):,}"
        )
        self.game.cleanup()