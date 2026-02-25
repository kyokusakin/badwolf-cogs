import discord
from redbot.core import commands
import logging
from typing import Optional

log = logging.getLogger("red.BadwolfCogs.casino.listener")

class CasinoMessageListener:
    """
    Listens for specific keywords in messages and triggers corresponding
    casino commands, providing a more natural language interface.
    Handles passing arguments for specific commands like 'transfer'.
    """
    def __init__(self, bot: commands.Bot, cog: commands.Cog):
        """
        Initializes the listener with bot and cog instances.
        Defines the mapping from command names to triggering keywords.
        """
        self.bot = bot
        self.cog = cog

        # 指令關鍵字映射表：指令名稱 → 關鍵字集合 (包含中文和英文)
        self.keyword_command_map = {
            "blackjack": ["21點", "二十一點", "blackjack"],
            "guesssize": ["猜大小", "骰寶", "guesssize"],
            "slots": ["拉霸", "slots"],
            "baccarat": ["百家樂", "百家乐", "baccarat"],
            "balance": ["餘額", "查詢餘額", "狗幣", "籌碼", "balance"],
            "work": ["工作", "打工", "work"],
            "dogmeat": ["賣狗肉", "賣狗哥", "dogmeat"],
            "transfer": ["轉移", "轉帳", "transfer", "v", "打錢"],
        }

    async def _trigger_command_by_keyword(self, message: discord.Message, command_name: str):

        prefix = (await self.bot.get_prefix(message))[0]

        message.content = f"{prefix}{command_name}"

        await self.bot.process_commands(message)
        
        log.debug(f"Simulated command trigger: {message.content}")

    async def handle_message(self, message: discord.Message):

        if message.author.bot or not message.guild:
            return

        # Get the command context for the message
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

        for command_name, keywords in self.keyword_command_map.items():
            if keyword in keywords:
                if command_name in ["blackjack", "guesssize", "slots", "baccarat"]:
                    value = None
                    if len(content) > 1:
                        try:
                            value = int(content[1])
                        except ValueError:
                            value = None

                    if command_name == "baccarat":
                        await ctx.invoke(getattr(self.cog, command_name), min_bet=value)
                        log.debug(
                            f"Keyword '{keyword}' triggered game command '{command_name}' with min_bet: {value}"
                        )
                    else:
                        await ctx.invoke(getattr(self.cog, command_name), bet=value)
                        log.debug(
                            f"Keyword '{keyword}' triggered game command '{command_name}' with bet: {value}"
                        )

                elif command_name == "transfer":
                    args = content[1:]
                    if len(args) < 2:
                        await message.channel.send("⚠️ 转账格式错误，正确格式：轉帳 @用戶 金額")
                        return

                    try:
                        converter = commands.MemberConverter()
                        member = await converter.convert(ctx, args[0])
                        amount = int(args[1])
                        await ctx.invoke(getattr(self.cog, command_name), member, amount)
                        log.debug(f"Keyword '{keyword}' triggered transfer command: {member.display_name} {amount}")
                    except commands.MemberNotFound:
                        await message.channel.send("❌ 找不到指定的用戶")
                    except ValueError:
                        await message.channel.send("❌ 金額必須是數字")
                    except Exception as e:
                        log.error(f"Transfer error: {str(e)}")
                        await message.channel.send("‼️ 轉賬時發生未知錯誤")

                else:
                    await self._trigger_command_by_keyword(message, command_name)
                    log.debug(f"Keyword '{keyword}' triggered simple command '{command_name}'")

                return

