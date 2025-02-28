import asyncio
import base64
import logging
import os
import json
import concurrent.futures
from typing import Optional

import discord
import openai
from redbot.core import Config, commands
from redbot.core.bot import Red
from .c_assistant import AssistantCommands

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

class OpenAIChat(commands.Cog, AssistantCommands):
    """A RedBot cog for OpenAI API integration with advanced features."""

    def __init__(self, bot: Red):
        self.bot = bot
        super().__init__(bot)
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

        self.queue = asyncio.Queue()
        self.processing = False
        self.queue_task = asyncio.create_task(self.process_queue())

        asyncio.create_task(self.initialize())

    async def initialize(self):
        """Initialize components."""
        chat_histories_path = os.path.join(os.path.dirname(__file__), "chat_histories")
        os.makedirs(chat_histories_path, exist_ok=True)

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    async def send_response(self, message: discord.Message, response: str):
        await self._send_in_chunks(message, response)

    async def _send_in_chunks(self, message: discord.Message, response: str):
        try:
            chunk_size = 2000
            chunks = [response[i : i + chunk_size] for i in range(0, len(response), chunk_size)]
    
            for chunk in chunks:
                await message.reply(chunk)
                await asyncio.sleep(1)

        except discord.DiscordException as e:
            log.error(f"Error sending response: {e}")

    async def query_openai(self, message: discord.Message) -> Optional[str]:
        """Query OpenAI API and return the response."""
        user_input = message.content
        if not user_input:
            return None

        api_key = await self.config.api_key()
        if not api_key:
            await message.channel.send("API key not set. Only the bot owner can set the key.")
            return None

        api_key = self.decode_key(api_key)
        api_url_base = await self.config.api_url_base()
        model = await self.config.model()

        user_name = message.author.display_name
        user_id = message.author.id
        bot_name = self.bot.user.display_name
        default_delay = await self.config.default_delay()

        config = await self.config.guild(message.guild).all()
        prompt = config["prompt"]
    
        history = await self.load_chat_history(message.guild.id)
        if not history:
            history = []

        guild_history = ""
        for entry in history:
            guild_history += f"\n{entry['user_name']} (ID: {entry['user_id']}): {entry['user_message']}\n{bot_name}: {entry['bot_response']}"

        sysprompt = (
            f"{prompt}\n"
            f"You are {bot_name}\n"
            "Respond naturally in the same language as the user\n"
            "Do not state who said what or repeat the user ID\n"
            "Respond directly without repeating the user's message\n"
            "Format code using Discord's markdown\n"
            "Must follow Discord Community Guidelines\n"
            "Avoid the same responses as history\n"
        )
        formatted_user_input = f"Discord User {user_name} (ID: <@{user_id}>) said:\n{user_input}"

        return self._blocking_openai_request(api_key, api_url_base, model, sysprompt, guild_history, formatted_user_input)

    def _blocking_openai_request(self, api_key: str, api_url_base: str, model: str, prompt: str, guild_history: str, user_input: str) -> Optional[str]:
        """Make a blocking request to OpenAI API."""
        try:
            client = openai.OpenAI(api_key=api_key, base_url=api_url_base)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": prompt}, {"role": "assistant", "content": "Chat histories:\n" + guild_history + "\nChat histories end."}, {"role": "user", "content": user_input}]
            )
            return response.choices[0].message.content
        except openai.OpenAIError as e:
            log.error(f"OpenAI error: {e}")
            return f"⚠️ API 錯誤：{e}"

    async def process_queue(self):
        """背景任務：處理排程中的訊息"""
        while True:
            try:
                message = await self.queue.get()
                if message is None:
                    break

                response = await self.query_openai(message)
                if response:
                    await self.process_response(message, response)
                
                await asyncio.sleep(4)
            except Exception as e:
                log.error(f"處理排程時出錯: {e}")

    async def process_response(self, message: discord.Message, response: str):
        """Handle the response and save chat history."""
        if response:
            await self.send_response(message, response)
            await self.save_chat_history(
                guild_id=message.guild.id,
                user_id=message.author.id,
                user_name=message.author.display_name,
                user_message=message.content,
                bot_response=response
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        if message.author.bot or not message.guild:
            return

        if message.stickers:
            return

        config = await self.config.guild(message.guild).all()
        channels = config["channels"]

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        
        if str(message.channel.id) not in channels:
            return

        await self.queue.put(message)

    async def load_chat_history(self, guild_id: int):
        """Load chat history for a guild."""
        file_path = os.path.join(os.path.dirname(__file__), "chat_histories", f"{guild_id}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        return []

    async def save_chat_history(self, guild_id: int, user_id: int, user_name: str, user_message: str, bot_response: str):
        """Save chat history for a guild."""
        file_path = os.path.join(os.path.dirname(__file__), "chat_histories", f"{guild_id}.json")
        history = await self.load_chat_history(guild_id)

        if len(history) >= 20:
            history = history[-19:]

        history.append({
            "user_id": user_id,
            "user_name": user_name,
            "user_message": user_message,
            "bot_response": bot_response
        })

        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(history, file, indent=4, ensure_ascii=False)

    async def cog_unload(self):
        """Clean up resources."""
        # 停止排程任務
        if self.queue_task and not self.queue_task.done():
            await self.queue.put(None)  # 發送終止信號
            await self.queue_task