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
            "ssl_ca": None,  # 儲存 CA 憑證的路徑
        }
        self.config.register_global(**default_global)
        self.connection = None
        self.pool = None
    
    async def initialize(self):
        """Initialize the MySQL connection session."""
        sql_host = await self.config.sql_host()
        sql_port = await self.config.sql_port()
        sql_user = await self.config.sql_user()
        sql_password = await self.config.sql_password()
        sql_database = await self.config.sql_database()
        ssl_ca = await self.config.ssl_ca()  # 讀取 SSL 憑證的路徑
        
        if not all([sql_host, sql_user, sql_password, sql_database]):
            log.warning("SQL connection details are not fully specified. Cannot initialize database connection session.")
            return
        
        try:
            # 使用 aiomysql 創建資料庫連接池
            self.pool = await aiomysql.create_pool(
                host=sql_host,
                port=sql_port,
                user=sql_user,
                password=sql_password,
                db=sql_database,
                ssl_ca=ssl_ca,  # 如果有指定 CA 憑證，使用它
                autocommit=True
            )
            await self.create_table()
            log.info("Successfully connected to MySQL database.")
        except Exception as e:
            log.error(f"SQL connection failed: {e}")
    
    async def create_table(self):
        """Create the chat history table if it doesn't exist."""
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
        """Execute SQL queries without returning results."""
        if not self.pool:
            log.warning("SQL session not initialized.")
            return
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, values)
                    log.info("Query executed successfully.")
        except Exception as e:
            log.error(f"Error executing query: {e}")
    
    async def fetch(self, query: str, *values):
        """Execute SQL queries and return results."""
        if not self.pool:
            log.warning("SQL session not initialized.")
            return None
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, values)
                    result = await cursor.fetchall()
                    return result
        except Exception as e:
            log.error(f"Error fetching query results: {e}")
            return None
    
    async def save_chat_history(self, user_id: int, user_message: str, bot_response: str):
        """Save chat history to the database."""
        query = """
        INSERT INTO chat_history (user_id, user_message, bot_response)
        VALUES (%s, %s, %s)"""
        await self.execute(query, user_id, user_message, bot_response)
        
        # Keep only the last 10 records per user
        delete_query = """
        DELETE FROM chat_history WHERE id NOT IN (
            SELECT id FROM (
                SELECT id FROM chat_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 10
            ) as temp
        )"""
        await self.execute(delete_query, user_id)

    async def close(self):
        """Close the MySQL session."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            log.info("MySQL session closed.")
