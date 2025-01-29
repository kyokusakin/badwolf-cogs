# sql_assistant.py
import logging
import aiomysql
from redbot.core import Config
from redbot.core.bot import Red

log = logging.getLogger("red.BadwolfCogs.sql_assistant")

class SQLAssistant:
    def __init__(self, bot: Red):
        self.bot = bot
        # 使用獨立的 config 實例
        self._config = Config.get_conf(
            None,  # 這裡不傳入 self，因為我們只需要一個全局配置
            identifier=987654321,
            force_registration=True,
            cog_name="OpenAIChat"  # 指定 cog 名稱
        )
        
        default_global = {
            "sql_settings": {
                "host": None,
                "port": 3306,
                "user": None,
                "password": None,
                "database": None,
                "ssl_ca": None
            }
        }
        self._config.register_global(**default_global)
        self.pool = None

    @property
    def config(self):
        return self._config

    async def initialize(self):
        """Initialize the MySQL connection session."""
        try:
            all_settings = await self._config.all()
            settings = all_settings.get("sql_settings", {})
            
            if not all([settings.get("host"), settings.get("user"), 
                       settings.get("password"), settings.get("database")]):
                log.warning("SQL connection details are not fully specified.")
                return
            
            ssl = {'ca': settings.get("ssl_ca")} if settings.get("ssl_ca") else None
            
            if self.pool:
                self.pool.close()
                await self.pool.wait_closed()
            
            self.pool = await aiomysql.create_pool(
                host=settings["host"],
                port=settings.get("port", 3306),
                user=settings["user"],
                password=settings["password"],
                db=settings["database"],
                ssl=ssl,
                autocommit=True
            )
            await self.create_table()
            log.info("Successfully connected to MySQL database.")
        except Exception as e:
            log.error(f"SQL connection failed: {e}")

    async def set_sql_setting(self, setting: str, value: any):
        """Update a specific SQL setting."""
        async with self._config.sql_settings() as settings:
            settings[setting] = value
        # 使用新設定重新初始化連接
        await self.initialize()

    async def get_sql_setting(self, setting: str) -> any:
        """Get a specific SQL setting."""
        all_settings = await self._config.all()
        return all_settings.get("sql_settings", {}).get(setting)

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