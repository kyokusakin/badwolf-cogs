import pathlib
import os
import aiosqlite
import time
from redbot.core import data_manager, commands
from redbot.core.bot import Red
import logging

log = logging.getLogger("red.BadwolfCogs.casino.database")

class StatsDatabase:
    """統計數據庫管理器，包含統計、冷卻與餘額功能"""

    def __init__(self, bot: Red, casino_cog):
        self.casino = casino_cog
        self.db_path = data_manager.cog_data_path(raw_name="Casino") / "casino.db"
        os.makedirs(self.db_path.parent, exist_ok=True)
        self.connection = None
        bot.loop.create_task(self.initialize_db())

    @staticmethod
    def _game_stats_create_sql(table_name: str = "game_stats") -> str:
        return f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                user_id INTEGER,
                game_type TEXT CHECK(game_type IN ('blackjack', 'slots', 'guesssize', 'baccarat')),
                bet INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                profit INTEGER DEFAULT 0,
                games INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, game_type),
                FOREIGN KEY (user_id) REFERENCES user_stats(user_id) ON DELETE CASCADE
            )
        '''

    async def _ensure_baccarat_in_game_stats(self):
        if self.connection is None:
            return

        async with self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='game_stats'"
        ) as cursor:
            row = await cursor.fetchone()

        table_sql = (row[0] or "").lower() if row else ""
        if "baccarat" in table_sql:
            return

        log.info("Detected legacy game_stats schema. Migrating to include 'baccarat'.")
        await self._migrate_game_stats_table()

    async def _migrate_game_stats_table(self):
        if self.connection is None:
            return

        try:
            await self.connection.execute("PRAGMA foreign_keys = OFF")
            await self.connection.execute("BEGIN")

            await self.connection.execute(self._game_stats_create_sql("game_stats_new"))
            await self.connection.execute('''
                INSERT INTO game_stats_new (user_id, game_type, bet, wins, losses, profit, games)
                SELECT user_id, game_type, bet, wins, losses, profit, games
                FROM game_stats
            ''')
            await self.connection.execute("DROP TABLE game_stats")
            await self.connection.execute("ALTER TABLE game_stats_new RENAME TO game_stats")

            await self.connection.commit()
            log.info("Migration completed: game_stats now supports 'baccarat'.")
        except Exception:
            await self.connection.rollback()
            log.exception("Failed migrating game_stats to include 'baccarat'. Keeping existing schema.")
        finally:
            try:
                await self.connection.execute("PRAGMA foreign_keys = ON")
            except Exception:
                log.exception("Failed to re-enable foreign_keys pragma after migration.")

    async def initialize_db(self):
        """初始化統計、冷卻與餘額表結構"""
        if self.connection is not None:
            return

        try:
            self.connection = await aiosqlite.connect(self.db_path)
            log.info(f"Database connected: {self.db_path}")

            # 使用者總體統計
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

            # 各遊戲類型統計
            await self.connection.execute(self._game_stats_create_sql())

            # 冷卻時間資料表
            await self.connection.execute('''
                CREATE TABLE IF NOT EXISTS cooldowns (
                    user_id INTEGER,
                    command_name TEXT,
                    expires_at REAL,
                    bucket_type TEXT,
                    PRIMARY KEY (user_id, command_name)
                )
            ''')

            # 餘額資料表
            await self.connection.execute('''
                CREATE TABLE IF NOT EXISTS balances (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                )
            ''')

            await self.connection.commit()
            await self._ensure_baccarat_in_game_stats()
            log.info("Database tables checked/created successfully.")

        except Exception as e:
            log.exception("Failed to initialize database.")
            if self.connection:
                await self.connection.close()
                self.connection = None # 確保失敗時連接被關閉

    # === 餘額操作 ===

    async def get_balance(self, user_id: int) -> int:
        """從資料庫獲取用戶餘額，如果不存在則初始化"""
        if self.connection is None:
            log.warning("Database connection not initialized when trying to get balance.")
            await self.initialize_db()
            if self.connection is None:
                 log.error(f"Database connection failed for user {user_id} balance get.")
                 return 0

        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "SELECT balance FROM balances WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
            else:
                default_balance = 77777
                try:
                    await cursor.execute(
                        "INSERT INTO balances (user_id, balance) VALUES (?, ?)",
                        (user_id, default_balance)
                    )
                    await self.connection.commit()
                    log.info(f"Initialized balance for user {user_id} with {default_balance}.")
                    return default_balance
                except Exception as e:
                    log.error(f"Failed to initialize balance for user {user_id}: {e}")
                    await self.connection.rollback()
                    return 0

    # 這個函式在 StatsDatabase 內部使用，名稱可以獨立於 Casino Cog
    async def update_balance(self, user_id: int, amount: int) -> int:
        """更新用戶餘額，原子操作"""
        if self.connection is None:
            log.warning("Database connection not initialized when trying to update balance.")
            await self.initialize_db()
            if self.connection is None:
                log.error(f"Database connection failed for user {user_id} balance update.")
                return await self.get_balance(user_id)

        # 確保用戶存在，如果不存在則初始化
        async with self.connection.cursor() as cursor:
            await cursor.execute(
               "INSERT INTO balances (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO NOTHING",
               (user_id, 77777)
            )
            await self.connection.commit()

        # 現在執行更新操作
        new_balance = 0
        try:
            async with self.connection.execute("BEGIN EXCLUSIVE TRANSACTION"):
                cursor = await self.connection.cursor()
                await cursor.execute("SELECT sqlite_version()")
                version = await cursor.fetchone()
                sqlite_version = tuple(map(int, version[0].split('.')))

                if sqlite_version >= (3, 35, 0):
                    await cursor.execute(
                        "UPDATE balances SET balance = balance + ? WHERE user_id = ? RETURNING balance",
                        (amount, user_id)
                    )
                    new_balance_row = await cursor.fetchone()
                    new_balance = new_balance_row[0] if new_balance_row else await self.get_balance(user_id)
                else:
                    await cursor.execute(
                        "UPDATE balances SET balance = balance + ? WHERE user_id = ?",
                        (amount, user_id)
                    )
                    await cursor.execute(
                        "SELECT balance FROM balances WHERE user_id = ?",
                        (user_id,)
                    )
                    new_balance_row = await cursor.fetchone()
                    new_balance = new_balance_row[0] if new_balance_row else 0

            await self.connection.commit()
            return new_balance
        except Exception as e:
            log.error(f"Failed to update balance for user {user_id} with amount {amount}: {e}")
            await self.connection.rollback()
            return await self.get_balance(user_id)
        
    async def set_balance(self, user_id: int, amount: int) -> int:
        if self.connection is None:
            log.warning("Database connection not initialized when trying to set balance.")
            await self.initialize_db()
            if self.connection is None:
                log.error(f"Database connection failed for user {user_id} balance set.")
                return 0

        try:
            async with self.connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO balances (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = ?",
                    (user_id, amount, amount)
                )
                await self.connection.commit()
                return amount
        except Exception as e:
             log.error(f"Failed to set balance for user {user_id}: {e}")
             await self.connection.rollback()
             return 0


    # === 統計操作 ===

    async def update_stats(self, user_id: int, game_type: str, bet: int, profit: int):
        """原子化更新統計數據"""
        if self.connection is None:
            log.warning(f"Database connection not initialized when trying to update stats for user {user_id}.")
            await self.initialize_db()
            if self.connection is None:
                 log.error(f"Database connection failed for user {user_id} stats update.")
                 return

        try:
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
        except Exception as e:
             log.error(f"Failed to update stats for user {user_id}: {e}")
             await self.connection.rollback()


    async def get_stats(self, user_id: int) -> dict:
        """獲取完整統計數據"""
        if self.connection is None:
            log.warning(f"Database connection not initialized when trying to get stats for user {user_id}.")
            await self.initialize_db()
            if self.connection is None:
                 log.error(f"Database connection failed for user {user_id} stats get.")
                 return {"total": {}, "games": {}}

        stats = {"total": {}, "games": {}}
        try:
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
        except Exception as e:
             log.error(f"Failed to get stats for user {user_id}: {e}")

        return stats

    async def get_top_users_by_profit(self, limit: int) -> list[tuple[int, int]]:
        """獲取總盈虧排行榜前 N 名用戶"""
        if self.connection is None:
            log.warning("Database connection not initialized when trying to get top users.")
            await self.initialize_db()
            if self.connection is None:
                 log.error("Database connection failed for getting top users.")
                 return []

        try:
            async with self.connection.cursor() as cursor:
                await cursor.execute('''
                    SELECT user_id, total_profit
                    FROM user_stats
                    ORDER BY total_profit DESC
                    LIMIT ?
                ''', (limit,))
                return await cursor.fetchall()
        except Exception as e:
             log.error(f"Failed to get top users: {e}")
             return []

    async def get_cooldown(self, user_id: int, command_name: str) -> float | None:
        """獲取指定指令的冷卻時間（若過期則自動清除）"""
        if self.connection is None:
            log.warning(f"Database connection not initialized when trying to get cooldown for user {user_id}.")
            await self.initialize_db()
            if self.connection is None:
                 log.error(f"Database connection failed for user {user_id} cooldown get.")
                 return None

        try:
            async with self.connection.execute(
                "SELECT expires_at FROM cooldowns WHERE user_id = ? AND command_name = ?",
                (user_id, command_name)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    expires_at = row[0]
                    if expires_at > time.time():
                        return expires_at
                    else:
                        # 冷卻已過期，清除資料庫記錄
                        await self.connection.execute(
                            "DELETE FROM cooldowns WHERE user_id = ? AND command_name = ?",
                            (user_id, command_name)
                        )
                        await self.connection.commit()
            return None
        except Exception as e:
             log.error(f"Failed to get cooldown for user {user_id}: {e}")
             return None


    async def set_cooldown(self, user_id: int, command_name: str, duration: float, bucket_type: commands.BucketType):
        """設定指令冷卻時間"""
        if self.connection is None:
            log.warning(f"Database connection not initialized when trying to set cooldown for user {user_id}.")
            await self.initialize_db()
            if self.connection is None:
                 log.error(f"Database connection failed for user {user_id} cooldown set.")
                 return

        expires_at = time.time() + duration
        try:
            await self.connection.execute(
                "REPLACE INTO cooldowns (user_id, command_name, expires_at, bucket_type) VALUES (?, ?, ?, ?)",
                (user_id, command_name, expires_at, bucket_type.name.lower())
            )
            await self.connection.commit()
        except Exception as e:
             log.error(f"Failed to set cooldown for user {user_id}: {e}")


    async def close(self):
        """關閉資料庫連接"""
        if self.connection:
            await self.connection.close()
            self.connection = None
            log.info("Database connection closed.")
