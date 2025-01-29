import asyncio
import base64
import logging
import os
import json
from typing import Optional

import discord
import openai
from redbot.core import Config, commands
from redbot.core.bot import Red
from .c_assistant import AssistantCommands

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)

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
        self.queue_task = None
        self.is_processing = False
        self.should_process = True
        
        asyncio.create_task(self.initialize())

    async def initialize(self):
        """Initialize components."""
        os.makedirs("chat_histories", exist_ok=True)

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    async def process_queue(self):
        """Process message queue, wait for some time after each processing."""
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
        """Send response"""
        try:
            await message.reply(response)
        except discord.DiscordException as e:
            log.error(f"Error sending response: {e}")

    async def query_openai(self, api_key: str, api_url_base: str, model: str, prompt: str) -> Optional[str]:
        """Query OpenAI API"""
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
            log.error(f"Error querying OpenAI: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = await self.config.guild(message.guild).all()
        channels = config["channels"]
    
        if str(message.channel.id) not in channels:
            return

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

        # Get the chat history for the guild, this will help in constructing the prompt
        history = await self.load_chat_history(message.guild.id)
        if not history:
            history = []

        prompt = config["prompt"]
        for entry in history:
            prompt += f"\nUser: {entry['user_message']}\nAssistant: {entry['bot_response']}"

        extended_prompt = (
            f"{prompt}\n"
            f"Discord User {user_name} (ID: <@{user_id}>) said:\n{user_input}"
        )

        # Query OpenAI
        response = await self.query_openai(api_key, api_url_base, model, extended_prompt)
        if response:
            await self.send_response(message, response)
            
            # Now save chat history after receiving response
            await self.save_chat_history(message.guild.id, user_input, response)

    async def load_chat_history(self, guild_id: int):
        """Load chat history for a specific guild."""
        file_path = os.path.join("chat_histories", f"{guild_id}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                return json.load(file)
        return []

    async def save_chat_history(self, guild_id: int, user_message: str, bot_response: str):
        """Save chat history to a file based on the guild ID."""
        file_path = os.path.join("chat_histories", f"{guild_id}.json")
        history = await self.load_chat_history(guild_id)

        history.append({
            "user_message": user_message,
            "bot_response": bot_response
        })

        with open(file_path, 'w') as file:
            json.dump(history, file, indent=4)

    async def cog_unload(self):
        """Clean up resources."""
        self.should_process = False
        if self.queue_task and not self.queue_task.done():
            self.queue_task.cancel()
            try:
                await self.queue_task
            except asyncio.CancelledError:
                pass