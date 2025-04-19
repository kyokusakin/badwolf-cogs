import pathlib
import os
import aiosqlite
from redbot.core import data_manager
from redbot.core.bot import Red

class StatsDatabase:
    """統計數據庫管理器，採用與CasinoCommands相同的設計模式"""

    def __init__(self, bot: Red, casino_cog):
        self.bot = bot
        self.casino = casino_cog
        self.db_path = self._get_db_path()
        self.connection = None
        bot.loop.create_task(self.initialize_db())

    def _get_db_path(self) -> pathlib.Path:
        """建立統計專用資料庫路徑"""
        base_path = data_manager.cog_data_path(raw_name="Casino") / "stats"
        os.makedirs(base_path, exist_ok=True)
        return base_path / "stats.db"

    async def initialize_db(self):
        """初始化統計數據庫表結構"""
        self.connection = await aiosqlite.connect(self.db_path)

        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                total_bet INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                total_losses INTEGER DEFAULT 0,
                total_profit INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0
            )
        ''')
        
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS game_stats (
                user_id INTEGER,
                game_type TEXT CHECK(game_type IN ('blackjack', 'slots', 'guesssize')),
                bet INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                profit INTEGER DEFAULT 0,
                games INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, game_type),
                FOREIGN KEY (user_id) REFERENCES user_stats(user_id)
            )
        ''')
        
        await self.connection.commit()

    # === 數據操作接口 ===
    async def update_stats(self, user_id: int, game_type: str, bet: int, profit: int):
        """原子化更新統計數據"""
        async with self.connection.cursor() as cursor:
            await cursor.execute('''
                INSERT INTO user_stats (user_id, total_bet, total_wins, total_losses, total_profit, total_games)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_bet = total_bet + excluded.total_bet,
                    total_wins = total_wins + excluded.total_wins,
                    total_losses = total_losses + excluded.total_losses,
                    total_profit = total_profit + excluded.total_profit,
                    total_games = total_games + excluded.total_games
            ''', (
                user_id,
                bet,
                1 if profit > 0 else 0,
                1 if profit < 0 else 0,
                profit,
                1
            ))

            await cursor.execute('''
                INSERT INTO game_stats (user_id, game_type, bet, wins, losses, profit, games)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, game_type) DO UPDATE SET
                    bet = bet + excluded.bet,
                    wins = wins + excluded.wins,
                    losses = losses + excluded.losses,
                    profit = profit + excluded.profit,
                    games = games + excluded.games
            ''', (
                user_id,
                game_type,
                bet,
                1 if profit > 0 else 0,
                1 if profit < 0 else 0,
                profit,
                1
            ))
            
        await self.connection.commit()

    async def get_stats(self, user_id: int) -> dict:
        """獲取完整統計數據"""
        stats = {"total": {}, "games": {}}
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM user_stats WHERE user_id = ?",
                (user_id,)
            )
            total_data = await cursor.fetchone()
            if total_data:
                stats["total"] = {
                    "bet": total_data[1],
                    "wins": total_data[2],
                    "losses": total_data[3],
                    "profit": total_data[4],
                    "games": total_data[5]
                }
            
            await cursor.execute(
                "SELECT * FROM game_stats WHERE user_id = ?",
                (user_id,)
            )
            games_data = await cursor.fetchall()
            for game in games_data:
                stats["games"][game[1]] = {
                    "bet": game[2],
                    "wins": game[3],
                    "losses": game[4],
                    "profit": game[5],
                    "games": game[6]
                }
        
        return stats
    async def get_top_users_by_profit(self, limit: int = 20) -> list[tuple[int, int]]:
            """
            獲取總盈虧排行榜前 N 名用戶。
            回傳：[(user_id, total_profit), ...]
            """
            async with self.connection.cursor() as cursor:
                await cursor.execute('''
                    SELECT user_id, total_profit
                    FROM user_stats
                    ORDER BY total_profit DESC
                    LIMIT ?
                ''', (limit,))
                top_users = await cursor.fetchall()
            return top_users
    
    async def close(self):
        """關閉數據庫連接"""
        if self.connection:
            await self.connection.close()