import discord
from redbot.core import commands
import logging
from typing import Optional

log = logging.getLogger("red.BadwolfCogs.casino.listener")

class CasinoMessageListener:
    def __init__(self, bot: commands.Bot, cog: commands.Cog):
        self.bot = bot
        self.cog = cog

        # 指令關鍵字映射表：指令名稱 → 關鍵字集合
        self.keyword_command_map = {
            "blackjack": ["21點", "二十一點", "blackjack"],
            "guesssize": ["猜大小", "骰寶", "guesssize"],
            "slots": ["拉霸", "slots"],
            "balance": ["餘額", "查詢餘額", "狗幣", "籌碼", "balance"],
            "work": ["工作", "打工", "work"],
            "dogmeat": ["賣狗肉", "賣狗哥", "dogmeat"],
        }

    async def _trigger_command_by_keyword(self, message: discord.Message, command_name: str):
        prefix = (await self.bot.get_prefix(message))[0]
        message.content = f"{prefix}{command_name}"
        await self.bot.process_commands(message)

    async def handle_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        if self.cog.is_playing(message.author.id):
            return

        if not await self.cog.is_allowed_channel(message):
            return

        content = message.content.strip().split()
        if not content:
            return

        keyword = content[0].lower()

        # 處理對應指令關鍵字（統一處理）
        for command_name, keywords in self.keyword_command_map.items():
            if keyword in keywords:
                # 有下注類型的遊戲：blackjack、guesssize、slots
                if command_name in ["blackjack", "guesssize", "slots"]:
                    bet = None
                    if len(content) > 1:
                        try:
                            bet = int(content[1])
                        except ValueError:
                            bet = None
                    await ctx.invoke(getattr(self.cog, command_name), bet=bet)
                else:
                    await self._trigger_command_by_keyword(message, command_name)
                return  # 成功處理後結束

        # 特殊處理：轉帳
        if keyword in ["V", "轉帳", "transfer"] and len(content) >= 3:
            try:
                member_mention = content[1]
                amount = int(content[2])
                member = await commands.MemberConverter().convert(ctx, member_mention)
                await ctx.invoke(self.cog.transfer, member=member, amount=amount)
            except Exception as e:
                await message.channel.send("❌ 格式錯誤，請使用 `轉帳 @使用者 金額`。")
                log.error(f"轉帳指令錯誤：{e}")
