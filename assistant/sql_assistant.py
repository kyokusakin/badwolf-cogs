import aiomysql
from redbot.core import Config, commands
from redbot.core.bot import Red
import logging

log = logging.getLogger("red.BadwolfCogs.sql_assistant")

class SQLAssistant:
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321, force_registration=True)
        default_global = {
            "sql_host": None,
            "sql_port": 3306,
            "sql_user": None,
            "sql_password": None,
            "sql_database": None,
        }
        self.config.register_global(**default_global)
        self.pool = None
    
    async def initialize(self):
        """初始化 SQL 連線池"""
        sql_host = await self.config.sql_host()
        sql_port = await self.config.sql_port()
        sql_user = await self.config.sql_user()
        sql_password = await self.config.sql_password()
        sql_database = await self.config.sql_database()
        
        if not all([sql_host, sql_user, sql_password, sql_database]):
            log.warning("SQL 資訊未設定，無法初始化資料庫連線池。")
            return
        
        try:
            self.pool = await aiomysql.create_pool(
                host=sql_host,
                port=sql_port,
                user=sql_user,
                password=sql_password,
                db=sql_database,
                autocommit=True
            )
            await self.create_table()
            log.info("成功連接至 SQL 資料庫。")
        except Exception as e:
            log.error(f"SQL 連線失敗: {e}")
    
    async def create_table(self):
        """建立對話記錄表格"""
        query = """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            user_message TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
        await self.execute(query)
    
    async def execute(self, query: str, *values):
        """執行 SQL 查詢 (不回傳結果)"""
        if not self.pool:
            log.warning("SQL 連線池尚未初始化。")
            return
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, values)
    
    async def fetch(self, query: str, *values):
        """執行 SQL 查詢並回傳結果"""
        if not self.pool:
            log.warning("SQL 連線池尚未初始化。")
            return None
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, values)
                return await cur.fetchall()
    
    async def save_chat_history(self, user_id: int, user_message: str, bot_response: str):
        """儲存對話記錄"""
        query = """
        INSERT INTO chat_history (user_id, user_message, bot_response)
        VALUES (%s, %s, %s)"""
        await self.execute(query, user_id, user_message, bot_response)
        
        # 保持每個用戶最多 10 條記錄
        delete_query = """
        DELETE FROM chat_history WHERE id NOT IN (
            SELECT id FROM (
                SELECT id FROM chat_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 10
            ) as temp
        )"""
        await self.execute(delete_query, user_id)
    
    async def close(self):
        """關閉 SQL 連線池"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            log.info("SQL 連線池已關閉。")