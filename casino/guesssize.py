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
        self.message: discord.Message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        return True

    async def process_guess(self, guess_type: str, new_card: int, interaction: discord.Interaction):
        result = ""
        multiplier = 1  # 預設賠率為 1 (猜錯不賠不贏，但實際上會輸掉下注金)
        winnings = 0

        if guess_type == "larger":
            multiplier = await self.game.cog.config.global_().guess_large_multiplier()
            if new_card > self.game.current_card:
                result = f"下一張牌為 {new_card}，你猜對了！"
                winnings = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, winnings)
            else:
                result = f"下一張牌為 {new_card}，你猜錯了。"
        elif guess_type == "smaller":
            multiplier = await self.game.cog.config.global_().guess_small_multiplier()
            if new_card < self.game.current_card:
                result = f"下一張牌為 {new_card}，你猜對了！"
                winnings = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, winnings)
            else:
                result = f"下一張牌為 {new_card}，你猜錯了。"
        elif guess_type == "odd":
            multiplier = await self.game.cog.config.global_().guess_odd_multiplier()
            if new_card % 2 == 1:
                result = f"下一張牌為 {new_card}（單數），你猜對了！"
                winnings = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, winnings)
            else:
                result = f"下一張牌為 {new_card}（雙數），你猜錯了。"
        elif guess_type == "even":
            multiplier = await self.game.cog.config.global_().guess_even_multiplier()
            if new_card % 2 == 0:
                result = f"下一張牌為 {new_card}（雙數），你猜對了！"
                winnings = self.game.bet * multiplier
                await self.game.cog.update_balance(self.game.ctx.author, winnings)
            else:
                result = f"下一張牌為 {new_card}（單數），你猜錯了。"

        await self.game.update_message(result)
        self.disable_all_items() # 禁用所有按鈕
        await interaction.response.edit_message(view=self)
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="較大", style=discord.ButtonStyle.green)
    async def larger(self, button: discord.ui.Button, interaction: discord.Interaction):
        new_card = random.randint(1, 13)
        await self.process_guess("larger", new_card, interaction)

    @discord.ui.button(label="較小", style=discord.ButtonStyle.green)
    async def smaller(self, button: discord.ui.Button, interaction: discord.Interaction):
        new_card = random.randint(1, 13)
        await self.process_guess("smaller", new_card, interaction)

    @discord.ui.button(label="單數", style=discord.ButtonStyle.blurple)
    async def odd(self, button: discord.ui.Button, interaction: discord.Interaction):
        new_card = random.randint(1, 13)
        await self.process_guess("odd", new_card, interaction)

    @discord.ui.button(label="雙數", style=discord.ButtonStyle.blurple)
    async def even(self, button: discord.ui.Button, interaction: discord.Interaction):
        new_card = random.randint(1, 13)
        await self.process_guess("even", new_card, interaction)

    async def on_timeout(self) -> None:
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)