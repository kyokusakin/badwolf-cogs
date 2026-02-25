import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
import logging

from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame
from .baccarat import BaccaratRoom
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
        self.active_baccarat_rooms: dict[int, BaccaratRoom] = {}
        self.active_baccarat_user_rooms: dict[int, int] = {}
        self.stats_db = StatsDatabase(bot, self)
        self.listener = CasinoMessageListener(bot, self)
        self.config.register_guild(allowed_channels=[])

        self.default_blackjack_bet = 100
        self.default_guesssize_bet = 50
        self.default_slots_bet = 50
        self.default_baccarat_min_bet = 100

    # ——— 遊戲狀態管理 ————————————————————————

    def is_playing(self, user_id: int) -> bool:
        return (
            user_id in self.active_blackjack_games or
            user_id in self.active_guesssize_games or
            user_id in self.active_slots_games or
            user_id in self.active_baccarat_user_rooms
        )

    def end_game(self, user_id: int):
        if user_id in self.active_blackjack_games:
            del self.active_blackjack_games[user_id]
        elif user_id in self.active_guesssize_games:
            del self.active_guesssize_games[user_id]
        elif user_id in self.active_slots_games:
            del self.active_slots_games[user_id]

    # ——— 餘額操作 (使用 StatsDatabase) ———————————————————————

    async def get_balance(self, user: discord.Member) -> int:
        """從資料庫獲取用戶餘額"""
        return await self.stats_db.get_balance(user.id)

    async def update_balance(self, user: discord.Member, amount: int) -> int:
        """更新用戶餘額並寫入資料庫"""
        new_balance = await self.stats_db.update_balance(user.id, amount)
        return new_balance

    async def set_balance(self, user: discord.Member, amount: int) -> int:
        """設置用戶餘額並寫入資料庫"""
        new_balance = await self.stats_db.set_balance(user.id, amount)
        return new_balance

    # ——— 頻道白名單檢查 (保留使用 Config) ———————————————————————

    async def is_allowed_channel(self, message: discord.Message) -> bool:
        allowed_channels = await self.config.guild(message.guild).allowed_channels()
        return message.guild is not None and message.channel.id in allowed_channels

    # ——— on_message ———————————————————————

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        if message.guild and not await self.is_allowed_channel(message):
            return

        await self.listener.handle_message(message)

    # ——— 卸載清理 ————————————————————————

    def cog_unload(self):
        for room in list(self.active_baccarat_rooms.values()):
            self.bot.loop.create_task(room.close_room("系統正在卸載 Casino 模組，百家樂房間已關閉。"))
        self.active_blackjack_games.clear()
        self.active_guesssize_games.clear()
        self.active_slots_games.clear()
        self.active_baccarat_rooms.clear()
        self.active_baccarat_user_rooms.clear()
        self.bot.loop.create_task(self.stats_db.close())
