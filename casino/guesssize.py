import discord
from redbot.core import commands
import random

class GuessGame:
    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog  # 主模組，用於更新餘額與存取全域賠率設定
        self.bet = bet
        self.current_card = random.randint(1, 13)  # 初始牌隨機產生 1~13
        self.message = None

    async def start(self):
        # 扣除下注金額
        await self.cog.update_balance(self.ctx.author, -self.bet)
        embed = discord.Embed(
            title="猜大小遊戲",
            description=(
                f"初始牌為：{self.current_card}\n"
                "請從下列選項中做出預測：\n"
                "【較大】、【較小】、【單數】、【雙數】"
            ),
            color=discord.Color.purple()
        )
        view = GuessView(self)
        self.message = await self.ctx.send(embed=embed, view=view)

    async def update_message(self, result_desc: str):
        embed = discord.Embed(
            title="猜大小遊戲",
            description=f"初始牌為：{self.current_card}\n{result_desc}",
            color=discord.Color.purple()
        )
        await self.message.edit(embed=embed, view=None)

class GuessView(discord.ui.View):
    def __init__(self, game: GuessGame):
        super().__init__(timeout=30)
        self.game = game

    async def process_guess(self, guess_type: str, new_card: int, interaction: discord.Interaction):
        result = ""
        if guess_type == "larger":
            if new_card > self.game.current_card:
                multiplier = await self.game.cog.config.global_().guess_large_multiplier()
                result = f"下一張牌為 {new_card}，你猜對了！"
                win_amount = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, win_amount)
            else:
                result = f"下一張牌為 {new_card}，你猜錯了。"
        elif guess_type == "smaller":
            if new_card < self.game.current_card:
                multiplier = await self.game.cog.config.global_().guess_small_multiplier()
                result = f"下一張牌為 {new_card}，你猜對了！"
                win_amount = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, win_amount)
            else:
                result = f"下一張牌為 {new_card}，你猜錯了。"
        elif guess_type == "odd":
            if new_card % 2 == 1:
                multiplier = await self.game.cog.config.global_().guess_odd_multiplier()
                result = f"下一張牌為 {new_card}（奇數），你猜對了！"
                win_amount = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, win_amount)
            else:
                result = f"下一張牌為 {new_card}（偶數），你猜錯了。"
        elif guess_type == "even":
            if new_card % 2 == 0:
                multiplier = await self.game.cog.config.global_().guess_even_multiplier()
                result = f"下一張牌為 {new_card}（偶數），你猜對了！"
                win_amount = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, win_amount)
            else:
                result = f"下一張牌為 {new_card}（奇數），你猜錯了。"
        await self.game.update_message(result)
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="較大", style=discord.ButtonStyle.green)
    async def larger(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        new_card = random.randint(1, 13)
        await self.process_guess("larger", new_card, interaction)

    @discord.ui.button(label="較小", style=discord.ButtonStyle.green)
    async def smaller(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        new_card = random.randint(1, 13)
        await self.process_guess("smaller", new_card, interaction)

    @discord.ui.button(label="單數", style=discord.ButtonStyle.blurple)
    async def odd(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        new_card = random.randint(1, 13)
        await self.process_guess("odd", new_card, interaction)

    @discord.ui.button(label="雙數", style=discord.ButtonStyle.blurple)
    async def even(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return
        new_card = random.randint(1, 13)
        await self.process_guess("even", new_card, interaction)
