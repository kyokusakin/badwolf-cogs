import discord
from redbot.core import commands
import logging
from typing import Optional

log = logging.getLogger("red.BadwolfCogs.casino.listener")

class CasinoMessageListener:
    def __init__(self, bot: commands.Bot, cog: commands.Cog):
        self.bot = bot
        self.cog = cog

    async def handle_message(self, message: discord.Message):
        # 忽略 Bot 自己或非公會訊息
        if message.author.bot or not message.guild:
            return
        
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        # 檢查玩家是否正在進行遊戲
        if self.cog.is_playing(message.author.id):
            return

        # 限制頻道
        if not await self.cog.is_allowed_channel(message):
            return

        content = message.content.strip().split()
        keyword = content[0]
        if not content:
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        bet = None
        if len(content) > 1:
            try:
                bet = int(content[1])
            except ValueError:
                bet = None  # 僅部分指令需要數字，後面處理

        # 遊戲類指令
        if keyword in ["21點", "二十一點", "blackjack"]:
            await ctx.invoke(self.cog.blackjack, bet=bet)
        elif keyword in ["猜大小", "骰寶", "guesssize"]:
            await ctx.invoke(self.cog.guesssize, bet=bet)
        elif keyword in ["拉霸", "slots"]:
            await ctx.invoke(self.cog.slots, bet=bet)

        # 金融類指令（balance、transfer、work、dogmeat）
        elif keyword in ["餘額", "查詢餘額", "狗幣", "籌碼", "balance"]:
            await ctx.invoke(self.cog.balance)
        elif keyword in ["工作", "打工", "work"]:
            await ctx.invoke(self.cog.work)
        elif keyword in ["賣狗肉", "賣狗哥", "dogmeat"]:
            await ctx.invoke(self.cog.dogmeat)
        elif keyword in ["V","轉帳","transfer"] and len(content) >= 3:
            try:
                member_mention = content[1]
                amount = int(content[2])
                member = await commands.MemberConverter().convert(ctx, member_mention)
                await ctx.invoke(self.cog.transfer, member=member, amount=amount)
            except Exception as e:
                await message.channel.send("❌ 格式錯誤，請使用 `轉移 @使用者 金額`。")
                log.error(f"轉移指令錯誤：{e}")
