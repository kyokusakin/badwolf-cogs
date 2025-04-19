import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
import logging

# 匯入其他子模組
from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame
from .listener import CasinoMessageListener
from .command_casino import CasinoCommands
from .db_casino import StatsDatabase

log = logging.getLogger("red.BadwolfCogs.casino")

class Casino(commands.Cog, CasinoCommands):
    """綜合賭場插件"""

    def __init__(self, bot: Red):
        super().__init__(bot, self)
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.active_blackjack_games: dict[int, BlackjackGame] = {}
        self.active_guesssize_games: dict[int, GuessGame] = {}
        self.active_slots_games: dict[int, SlotGame] = {}
        self.listener = CasinoMessageListener(bot, self)
        self.stats_db = StatsDatabase(bot, self)

        default_user = {"balance": 1000}
        self.config.register_user(**default_user)
        self.config.register_guild(allowed_channels=[])

        self.default_blackjack_bet = 100
        self.default_guesssize_bet = 50
        self.default_slots_bet = 50

    # ——— 遊戲狀態管理 ————————————————————————

    def is_playing(self, user_id: int) -> bool:
        return (
            user_id in self.active_blackjack_games or
            user_id in self.active_guesssize_games or
            user_id in self.active_slots_games
        )

    def end_game(self, user_id: int):
        if user_id in self.active_blackjack_games:
            del self.active_blackjack_games[user_id]
        elif user_id in self.active_guesssize_games:
            del self.active_guesssize_games[user_id]
        elif user_id in self.active_slots_games:
            del self.active_slots_games[user_id]

    async def get_balance(self, user: discord.Member) -> int:
        return await self.config.user(user).balance()

    async def update_balance(self, user: discord.Member, amount: int):
        bal = await self.get_balance(user)
        newbal = bal + amount
        await self.config.user(user).balance.set(newbal)
        return newbal

    # ——— 頻道白名單檢查 ———————————————————————

    async def is_allowed_channel(self, message: discord.Message) -> bool:
        allowed_channels = await self.config.guild(message.guild).allowed_channels()
        return message.channel.id in allowed_channels

    # ——— on_message ———————————————————————

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self.listener.handle_message(message)

    # ——— 卸載清理 ————————————————————————

    def cog_unload(self):
        self.active_blackjack_games.clear()
        self.active_guesssize_games.clear()
        self.active_slots_games.clear()
        self.bot.loop.create_task(self.stats_db.close())