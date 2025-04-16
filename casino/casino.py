import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
import logging

# 匯入其他子模組
from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame

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
            guess_large_multiplier=1.8,
            guess_small_multiplier=1.8,
            guess_odd_multiplier=1.5,
            guess_even_multiplier=1.5
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

    @commands.guild_only()
    @commands.command(name="blackjack")
    async def blackjack(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發 21 點遊戲。

        若未指定下注金額，則使用預設下注金額。
        """
        if bet is None:
            bet = self.default_blackjack_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = BlackjackGame(ctx, self, bet)
        await game.start()

    @commands.guild_only()
    @commands.command(name="guesssize")
    async def guesssize(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發猜大小遊戲（含猜單雙）。

        若未指定下注金額，則使用預設下注金額。
        """
        if bet is None:
            bet = self.default_guesssize_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = GuessGame(ctx, self, bet)
        await game.start()

    @commands.guild_only()
    @commands.command(name="slots")
    async def slots(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發拉霸遊戲。

        若未指定下注金額，則使用預設下注金額。
        """
        if bet is None:
            bet = self.default_slots_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return
        game = SlotGame(ctx, self, bet)
        await game.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 忽略機器人訊息
        if message.author.bot or not message.guild:
            return

        content = message.content.strip()
        parts = content.split()
        keyword = parts[0]

        if keyword in ("21點", "猜大小", "拉霸"):
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return

            balance = await self.get_balance(ctx.author)
            bet_amount = None

            if len(parts) > 1:
                try:
                    bet_amount = int(parts[1])
                    if bet_amount <= 0:
                        await ctx.send("下注金額必須大於 0。")
                        return
                    if bet_amount > balance:
                        await ctx.send(f"你的餘額不足以進行 {bet_amount} 的下注。")
                        return
                except ValueError:
                    await ctx.send("請輸入有效的下注金額。")
                    return

            if keyword == "21點":
                bet = bet_amount if bet_amount is not None else self.default_blackjack_bet
                if bet > balance:
                    await ctx.send(f"你的餘額不足以進行 {bet} 的 21 點下注。")
                    return
                await ctx.invoke(self.blackjack, bet=bet)
            elif keyword == "猜大小":
                bet = bet_amount if bet_amount is not None else self.default_guesssize_bet
                if bet > balance:
                    await ctx.send(f"你的餘額不足以進行 {bet} 的猜大小下注。")
                    return
                await ctx.invoke(self.guesssize, bet=bet)
            elif keyword == "拉霸":
                bet = bet_amount if bet_amount is not None else self.default_slots_bet
                if bet > balance:
                    await ctx.send(f"你的餘額不足以進行 {bet} 的拉霸下注。")
                    return
                await ctx.invoke(self.slots, bet=bet)