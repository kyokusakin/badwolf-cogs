# assistant.py
import asyncio
import base64
import logging
from typing import Optional

import discord
import openai
from redbot.core import Config, commands
from redbot.core.bot import Red
from .c_assistant import AssistantCommands
from .sql_assistant import SQLAssistant

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)


class OpenAIChat(
  commands.Cog,
  AssistantCommands,
  SQLAssistant
):
    """A RedBot cog for OpenAI API integration with advanced features."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
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

        self.queue = asyncio.Queue()
        self.queue_task = None
        self.is_processing = False
        self.should_process = True

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

    async def cog_unload(self):
        """清理資源"""
        self.should_process = False
        await self.sql.close()
        if self.queue_task and not self.queue_task.done():
            self.queue_task.cancel()
            try:
                await self.queue_task
            except asyncio.CancelledError:
                pass
