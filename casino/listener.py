import discord
from redbot.core import commands

class CasinoMessageListener:
    def __init__(self, bot: commands.Bot, cog: commands.Cog, allowed_channel_ids: list[int]):
        self.bot = bot
        self.cog = cog
        self.allowed_channel_ids = allowed_channel_ids

    async def handle_message(self, message: discord.Message):
        # 忽略 Bot 自己或非公會訊息
        if message.author.bot or not message.guild:
            return

        # 限制頻道
        if message.channel.id not in self.allowed_channel_ids:
            return

        content = message.content.strip().split()
        keyword = content[0]
        if keyword not in ("21點", "猜大小", "拉霸"):
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        bet = None
        if len(content) > 1:
            try:
                bet = int(content[1])
            except ValueError:
                await message.channel.send("請輸入有效的下注金額。")
                return

        if keyword == "21點":
            await ctx.invoke(self.cog.blackjack, bet=bet)
        elif keyword == "猜大小":
            await ctx.invoke(self.cog.guesssize, bet=bet)
        elif keyword == "拉霸":
            await ctx.invoke(self.cog.slots, bet=bet)
