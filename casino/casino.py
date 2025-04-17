import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
import logging

# 匯入其他子模組
from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame
from .listener import CasinoMessageListener

log = logging.getLogger("red.BadwolfCogs.casino")

class Casino(commands.Cog):
    """綜合賭場插件，整合 21 點、猜大小（含猜單雙）與拉霸遊戲，並支援 on_message 觸發。"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.active_games = set()
        self.active_blackjack_games: dict[int, BlackjackGame] = {}
        self.active_guesssize_games: dict[int, GuessGame] = {}
        self.active_slots_games: dict[int, SlotGame] = {}
        self.listener = CasinoMessageListener(bot, self, self.allowed_channel_ids)

        default_user = {"balance": 1000}
        self.config.register_user(**default_user)
        self.config.register_global(
            guess_large_multiplier=1.8,
            guess_small_multiplier=1.8,
            guess_odd_multiplier=1.5,
            guess_even_multiplier=1.5
        )
        self.config.register_guild(allowed_channels=[])

        self.default_blackjack_bet = 100
        self.default_guesssize_bet = 50
        self.default_slots_bet = 50

    # ——— 遊戲狀態管理 ————————————————————————

    def is_playing(self, user_id: int) -> bool:
        return user_id in self.active_games

    def start_game(self, user_id: int):
        self.active_games.add(user_id)

    def end_game(self, user_id: int):
        self.active_games.discard(user_id)

    async def get_balance(self, user: discord.Member) -> int:
        return await self.config.user(user).balance()

    async def update_balance(self, user: discord.Member, amount: int):
        bal = await self.get_balance(user)
        newbal = bal + amount
        await self.config.user(user).balance.set(newbal)
        return newbal

    # ——— 指令觸發 ————————————————————————

    @commands.guild_only()
    @commands.command(name="blackjack")
    async def blackjack(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發 21 點遊戲。"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_blackjack_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        self.start_game(ctx.author.id)
        try:
            game = BlackjackGame(ctx, self, bet)
            self.active_blackjack_games[ctx.author.id] = game
            await game.start()
        finally:
            self.end_game(ctx.author.id)

    @commands.guild_only()
    @commands.command(name="guesssize")
    async def guesssize(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發猜大小遊戲（含猜單雙）。"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_guesssize_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        self.start_game(ctx.author.id)
        try:
            game = GuessGame(ctx, self, bet)
            self.active_guesssize_games[ctx.author.id] = game
            await game.start()
        finally:
            self.end_game(ctx.author.id)

    @commands.guild_only()
    @commands.command(name="slots")
    async def slots(self, ctx: commands.Context, bet: int = None):
        """使用指令觸發拉霸遊戲。"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_slots_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        self.start_game(ctx.author.id)
        try:
            game = SlotGame(ctx, self, bet)
            self.active_slots_games[ctx.author.id] = game
            await game.start()
        finally:
            self.end_game(ctx.author.id)

    # ——— 頻道白名單檢查 ———————————————————————

    async def is_allowed_channel(self, message: discord.Message) -> bool:
        allowed_channels = await self.config.guild(message.guild).allowed_channels()
        return message.channel.id in allowed_channels

    # ——— on_message ———————————————————————

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self.listener.handle_message(message)

    # ——— 頻道設定指令 ———————————————————————

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="casinochan")
    async def casinochan(self, ctx: commands.Context):
        """設定允許使用 on_message 賭場的頻道。"""
        pass

    @casinochan.command(name="add")
    async def casinochan_add(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = self.config.guild(ctx.guild)
        allowed = await cfg.allowed_channels()
        if channel.id in allowed:
            await ctx.send(f"{channel.mention} 已經是允許頻道。")
        else:
            allowed.append(channel.id)
            await cfg.allowed_channels.set(allowed)
            await ctx.send(f"✅ 已新增 {channel.mention} 為賭場頻道。")

    @casinochan.command(name="remove")
    async def casinochan_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = self.config.guild(ctx.guild)
        allowed = await cfg.allowed_channels()
        if channel.id not in allowed:
            await ctx.send(f"{channel.mention} 並不在允許清單中。")
        else:
            allowed.remove(channel.id)
            await cfg.allowed_channels.set(allowed)
            await ctx.send(f"✅ 已移除 {channel.mention}。")

    @casinochan.command(name="list")
    async def casinochan_list(self, ctx: commands.Context):
        allowed = await self.config.guild(ctx.guild).allowed_channels()
        if not allowed:
            await ctx.send("目前尚未設定任何允許的頻道。")
            return
        mentions = [f"<#{cid}>" for cid in allowed]
        await ctx.send("🎰 允許的賭場頻道如下：\n" + "\n".join(mentions))

    # ——— 卸載清理 ————————————————————————

    def cog_unload(self):
        for game in self.active_blackjack_games.values():
            self.bot.loop.create_task(
                game.ctx.send("⚠️ 插件已重新載入，你的 21 點 遊戲已中止並退還下注。")
            )
        for game in self.active_guesssize_games.values():
            self.bot.loop.create_task(
                game.ctx.send("⚠️ 插件已重新載入，你的猜大小遊戲已中止並退還下注。")
            )
        for game in self.active_slots_games.values():
            self.bot.loop.create_task(
                game.ctx.send("⚠️ 插件已重新載入，你的拉霸遊戲已中止並退還下注。")
            )
        self.active_blackjack_games.clear()
        self.active_guesssize_games.clear()
        self.active_slots_games.clear()
        self.active_games.clear()
        log.info("Casino cog 已成功卸載，並清除所有遊戲資料。")
