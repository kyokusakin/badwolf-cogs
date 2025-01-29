import asyncio
import base64
import logging
from typing import Optional

import discord
import openai
from redbot.core import Config, commands
from redbot.core.bot import Red
from .sql_assistant import SQLAssistant
from .c_assistant import AssistantCommands

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)

class OpenAIChat(commands.Cog, AssistantCommands):
    """A RedBot cog for OpenAI API integration with advanced features."""

    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        # 主要的 OpenAI 設定
        self.config = Config.get_conf(
            self,
            identifier=1234567890,
            force_registration=True
        )
        default_global = {
            "api_key": None,
            "api_url_base": "https://api.openai.com/v1",
            "model": "gpt-4",
            "default_delay": 1,
        }
        default_guild = {
            "channels": {},
            "prompt": "",
        }
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        # 初始化 SQL 助手
        self.sql = SQLAssistant(bot)
        
        self.queue = asyncio.Queue()
        self.queue_task = None
        self.is_processing = False
        self.should_process = True
        
        asyncio.create_task(self.initialize())

    async def initialize(self):
        """Initialize components."""
        await self.sql.initialize()

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    async def process_queue(self):
        """處理訊息隊列，每次處理後等待一段時間"""
        try:
            while self.should_process:
                try:
                    message, api_key, api_url_base, model, prompt = await asyncio.wait_for(
                        self.queue.get(), 
                        timeout=30
                    )
                    response = await self.query_openai(api_key, api_url_base, model, prompt)
                    if response:
                        await self.send_response(message, response)
                        await self.save_chat_history(message.author.id, message.content, response)
                    
                    self.queue.task_done()

                    delay = await self.calculate_delay(response, await self.config.default_delay())

                    await asyncio.sleep(delay)
                    
                except asyncio.TimeoutError:
                    if self.queue.empty():
                        self.is_processing = False
                        break
                        
        except Exception as e:
            log.error(f"Error in process_queue: {e}")
            self.is_processing = False

    async def calculate_delay(self, response: Optional[dict], default_delay: float) -> float:
        if response and "x-ratelimit-limit-requests" in response:
            rate_limit = int(response["x-ratelimit-limit-requests"])
            return max(60 / rate_limit, 1)
        return default_delay

    async def send_response(self, message: discord.Message, response: str):
        """發送回應"""
        try:
            await message.reply(response)
        except discord.DiscordException as e:
            try:
                log.error(f"Error: {e}")
            except:
                log.error(f"Failed to send response: {e}")

    async def query_openai(self, api_key: str, api_url_base: str, model: str, prompt: str) -> Optional[str]:
        """查詢 OpenAI API"""
        client = openai.OpenAI(
            api_key=api_key,
            base_url=api_url_base
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": prompt.split("\n")[-1]}]
            )
            return response.choices[0].message.content
        except Exception as e:
            return log.error(f"Error querying OpenAI: {e}")
        
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = await self.config.guild(message.guild).all()
        channels = config["channels"]

        if str(message.channel.id) not in channels:
            return

        prompt = config["prompt"]
        user_input = message.content

        if not user_input:
            return

        api_key = await self.config.api_key()
        
        if not api_key:
            await message.channel.send("API key not set. Only the bot owner can set the key.")
            return

        api_key = self.decode_key(api_key)
        api_url_base = await self.config.api_url_base()
        model = await self.config.model()

        user_name = message.author.display_name
        user_id = message.author.id
        extended_prompt = (
            f"{prompt}\n"
            f"Discord User {user_name} (<@{user_id}>) said:\n{user_input}"
        )

        await self.queue.put((message, api_key, api_url_base, model, extended_prompt))
        
        if not self.is_processing:
            self.is_processing = True
            self.queue_task = asyncio.create_task(self.process_queue())

    async def set_sql_setting(self, setting: str, value: any):
        """代理到 SQL Assistant 的設定方法"""
        await self.sql.set_sql_setting(setting, value)

    async def get_sql_setting(self, setting: str) -> any:
        """代理到 SQL Assistant 的獲取設定方法"""
        return await self.sql.get_sql_setting(setting)

    async def save_chat_history(self, user_id: int, user_message: str, bot_response: str):
        """代理到 SQL Assistant 的儲存聊天記錄方法"""
        await self.sql.save_chat_history(user_id, user_message, bot_response)

    async def cog_unload(self):
        """Clean up resources."""
        self.should_process = False
        await self.sql.close()
        if self.queue_task and not self.queue_task.done():
            self.queue_task.cancel()
            try:
                await self.queue_task
            except asyncio.CancelledError:
                pass