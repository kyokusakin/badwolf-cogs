import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
import logging

# 匯入其他子模組
from . import blackjack, guesssize, slots

log = logging.getLogger("red.BadwolfCogs.casino")

class Casino(commands.Cog):
    """綜合賭場插件，整合 21 點、猜大小（含猜單雙）與拉霸遊戲，
    並支援 on_message 觸發。
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        # 為每位使用者設定初始餘額（預設 1000）
        default_user = {"balance": 1000}
        self.config.register_user(**default_user)
        # 全域設定：猜大小各選項的賠率，預設均為 2 倍
        self.config.register_global(
            guess_large_multiplier=2,
            guess_small_multiplier=2,
            guess_odd_multiplier=2,
            guess_even_multiplier=2
        )
        # 預設下注金額（可依需求調整）
        self.default_blackjack_bet = 100
        self.default_guesssize_bet = 50
        self.default_slots_bet = 50

    async def get_balance(self, user: discord.Member) -> int:
        return await self.config.user(user).balance()

    async def update_balance(self, user: discord.Member, amount: int):
        bal = await self.get_balance(user)
        newbal = bal + amount
        await self.config.user(user).balance.set(newbal)
        return newbal

    @commands.command(name="blackjack")
    async def blackjack(self, ctx: commands.Context, bet: int):
        """使用指令觸發 21 點遊戲。"""
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = blackjack.BlackjackGame(ctx, self, bet)
        await game.start()

    @commands.command(name="guesssize")
    async def guesssize(self, ctx: commands.Context, bet: int):
        """使用指令觸發猜大小遊戲（含猜單雙）。"""
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = guesssize.GuessGame(ctx, self, bet)
        await game.start()

    @commands.command(name="slots")
    async def slots(self, ctx: commands.Context, bet: int):
        """使用指令觸發拉霸遊戲。"""
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = slots.SlotGame(ctx, self, bet)
        await game.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 忽略機器人訊息
        if message.author.bot:
            return

        content = message.content.strip()
        # 若僅輸入關鍵字且非已呼叫指令，則以預設下注金額觸發遊戲
        if content in ("21點", "猜大小", "拉霸"):
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return
            if content == "21點":
                await ctx.invoke(self.blackjack, bet=self.default_blackjack_bet)
            elif content == "猜大小":
                await ctx.invoke(self.guesssize, bet=self.default_guesssize_bet)
            elif content == "拉霸":
                await ctx.invoke(self.slots, bet=self.default_slots_bet)