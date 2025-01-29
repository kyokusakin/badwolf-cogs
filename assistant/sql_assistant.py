import mysqlx
from redbot.core import Config, commands
from redbot.core.bot import Red
import logging
import os

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
        self.session = None
    
    async def initialize(self):
        """Initialize the MySQL connection session."""
        sql_host = await self.config.sql_host()
        sql_port = await self.config.sql_port()
        sql_user = await self.config.sql_user()
        sql_password = await self.config.sql_password()
        sql_database = await self.config.sql_database()
        
        # 設定 SSL 檔案路徑
        ssl_dir = os.path.join(os.path.dirname(__file__), 'ssl')
        ssl_options = {
            'ca': os.path.join(ssl_dir, 'ca-cert.pem'),
            'cert': os.path.join(ssl_dir, 'client-cert.pem'),
            'key': os.path.join(ssl_dir, 'client-key.pem')
        }

        if not all([sql_host, sql_user, sql_password, sql_database]):
            log.warning("SQL connection details are not fully specified. Cannot initialize database connection session.")
            return
        
        try:
            self.session = mysqlx.get_client(
                host=sql_host,
                port=sql_port,
                user=sql_user,
                password=sql_password,
                database=sql_database,
                ssl_context=ssl_options  # 設定 SSL 參數
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
        if not self.session:
            log.warning("SQL session not initialized.")
            return
        try:
            schema = self.session.get_schema()
            table = schema.get_table('chat_history')
            table.sql(query).execute(*values)
        except Exception as e:
            log.error(f"Error executing query: {e}")
    
    async def fetch(self, query: str, *values):
        """Execute SQL queries and return results."""
        if not self.session:
            log.warning("SQL session not initialized.")
            return None
        try:
            schema = self.session.get_schema()
            table = schema.get_table('chat_history')
            result = table.sql(query).execute(*values)
            return result.fetch_all()
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
        if self.session:
            self.session.close()
            log.info("MySQL session closed.")
