import asyncio
import base64
import logging
import os
import json
import aiofiles
import time
import discord
import openai
from redbot.core import Config, commands
from redbot.core.bot import Red
from .c_assistant import AssistantCommands
from typing import Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

class OpenAIChat(commands.Cog, AssistantCommands):
    """A RedBot cog for OpenAI API integration with advanced features,
    including a layered memory system where the AI decides which memories to store."""
    
    def __init__(self, bot: Red):
        self.bot = bot
        super().__init__(bot)
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
        self.queue_task = asyncio.create_task(self.process_queue())
        self.executor = ThreadPoolExecutor(max_workers=4)
        asyncio.create_task(self.initialize())
    
    async def initialize(self):
        """Initialize component and create chat history folder"""
        chat_histories_path = os.path.join(os.path.dirname(__file__), "chat_histories")
        os.makedirs(chat_histories_path, exist_ok=True)
        self.chat_histories_path = chat_histories_path

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    async def send_response(self, message: discord.Message, response: str):
        await self._send_in_chunks(message, response)

    async def _send_in_chunks(self, message: discord.Message, response: str):
        try:
            chunk_size = 2000
            chunks = [response[i: i + chunk_size] for i in range(0, len(response), chunk_size)]
            for chunk in chunks:
                await message.reply(chunk)
                await asyncio.sleep(1)
        except discord.DiscordException as e:
            log.error(f"Error sending response: {e}")

    async def query_openai(self, message: discord.Message) -> Optional[str]:
        """Query OpenAI API and return response content"""
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
        config = await self.config.guild(message.guild).all()
        prompt = config["prompt"]

        # Load chat history
        history = await self.load_chat_history(message.guild.id)
        if not history:
            history = []

        # Build layered memory content with dynamic trimming
        current_time = time.time()
        guild_history = await self.build_guild_history(
            history, current_time, short_term_seconds=600, max_records=20, bot_name=bot_name
        )

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

        # Use thread executor for blocking API call
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._blocking_openai_request,
            api_key, api_url_base, model, sysprompt, guild_history, formatted_user_input
        )

    def _blocking_openai_request(
        self, api_key: str, api_url_base: str, model: str,
        prompt: str, guild_history: str, user_input: str
    ) -> Optional[str]:
        """Synchronous call to OpenAI API using client.chat.completions.create"""
        try:
            # Create client and set API key and base URL
            client = openai.OpenAI(api_key=api_key, base_url=api_url_base)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "assistant", "content": "Chat histories:\n" + guild_history + "\nChat histories end."},
                {"role": "user", "content": user_input}
            ]
            response = client.chat.completions.create(
                model=model,
                messages=messages
            )
            return response.choices[0].message.content
        except openai.OpenAIError as e:
            log.error(f"OpenAI error: {e}")
            return f"⚠️ API Error: {e}"

    async def process_queue(self):
        """Background task: process messages in queue"""
        delay = await self.config.default_delay()
        while True:
            try:
                message = await self.queue.get()
                if message is None:
                    break
                response = await self.query_openai(message)
                if response:
                    await self.process_response(message, response)
                await asyncio.sleep(delay)
            except Exception as e:
                log.error(f"Error processing queue: {e}")

    async def process_response(self, message: discord.Message, response: str):
        """Process response and decide whether to store memory based on AI evaluation"""
        if response:
            await self.send_response(message, response)
            # Let AI evaluate the importance of this conversation
            importance = await self.evaluate_memory(message.content, response)
            if importance > 0:
                await self.save_chat_history(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    user_message=message.content,
                    bot_response=response,
                    importance=importance
                )
            log.info(f"\nGuild ID:{message.guild.id}\nUser: {message.author.display_name}({message.author.id})\nUser Message: {message.content}\nBot response: {response}\nImportance: {importance}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for message events"""
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

    async def load_chat_history(self, guild_id: int) -> List[Dict]:
        """Asynchronously load chat history for specified guild"""
        file_path = os.path.join(self.chat_histories_path, f"{guild_id}.json")
        if os.path.exists(file_path):
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    return json.loads(content)
            except Exception as e:
                log.error(f"Error loading chat history: {e}")
                return []
        return []

    async def save_chat_history(self, guild_id: int, user_id: int, user_name: str,
                                user_message: str, bot_response: str, importance: int = 1):
        """Asynchronously save chat history with timestamp and importance rating"""
        file_path = os.path.join(self.chat_histories_path, f"{guild_id}.json")
        history = await self.load_chat_history(guild_id)
        record = {
            "user_id": user_id,
            "user_name": user_name,
            "user_message": user_message,
            "bot_response": bot_response,
            "timestamp": time.time(),
            "importance": importance
        }
        history.append(record)
        try:
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as file:
                await file.write(json.dumps(history, indent=4, ensure_ascii=False))
        except Exception as e:
            log.error(f"Error saving chat history: {e}")

    async def build_guild_history(self, history: List[Dict], current_time: float, short_term_seconds: int, max_records: int, bot_name: str) -> str:
        """
        Dynamically trim chat history based on short-term and long-term memory, return string for context.
        Short-term memory: Records within short_term_seconds
        Long-term memory: Remaining records sorted by importance, taking highest importance records
        up to max_records total
        """
        short_term = [
            record for record in history 
            if current_time - record.get("timestamp", 0) <= short_term_seconds
        ]
        long_term = [
            record for record in history 
            if current_time - record.get("timestamp", 0) > short_term_seconds
        ]

        long_term.sort(key=lambda x: (x.get("importance", 1), x.get("timestamp", 0)), reverse=True)
        remaining_slots = max_records - len(short_term)
        selected_long_term = long_term[:remaining_slots] if remaining_slots > 0 else []
        combined = short_term + selected_long_term
        combined.sort(key=lambda x: x.get("timestamp", 0))

        history_str = ""
        for entry in combined:
            history_str += (
                f"\n{entry['user_name']} (ID: {entry['user_id']}): {entry['user_message']}"
                f"\n{bot_name}: {entry['bot_response']}"
            )
        return history_str

    async def evaluate_memory(self, user_message: str, bot_response: str) -> int:
        """
        Let AI evaluate the memory importance of this conversation, return value 0-5
        0 means not important, don't store; higher number means more important
        """
        api_key = await self.config.api_key()
        if not api_key:
            return 1  # Default importance if API key not set
        
        api_key = self.decode_key(api_key)
        api_url_base = await self.config.api_url_base()
        model = await self.config.model()
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._blocking_evaluate_memory,
            api_key, api_url_base, model, user_message, bot_response
        )

    def _blocking_evaluate_memory(self, api_key: str, api_url_base: str, model: str, user_message: str, bot_response: str) -> int:
        """
        Synchronous OpenAI API call to evaluate memory importance,
        Request format requires only a number (0-5) response
        """
        try:
            # Create client and call evaluation API with improved prompt
            client = openai.OpenAI(api_key=api_key, base_url=api_url_base)
            response = client.chat.completions.create(
                model=model,
                messages = [
                    {"role": "system", "content": """
                    You are a memory evaluation assistant. Your task is to evaluate conversations and assign them an importance score from 0 to 5.
                    IMPORTANCE SCALE:
                    0 = Not important at all (e.g., everyday greetings, casual small talk)
                    1 = Slightly important (e.g., basic information, simple questions)
                    2 = Moderately important (e.g., specific details that may be referenced later)
                    3 = Important (e.g., personal preferences, significant details)
                    4 = Very important (e.g., critical information, complex emotional topics)
                    5 = Extremely important (e.g., essential information that must be remembered for future interactions)
    
                    Examples:
                    - "Hi, how are you?" → Rating: 0
                    - "What's your favorite color?" → Rating: 1
                    - "I like pizza, and I’m allergic to nuts." → Rating: 3
                    - "I'm going through a tough time and need someone to talk to." → Rating: 4
    
                    Please evaluate the following conversation carefully. Most casual conversations will rate between 0-2, while more significant interactions should be rated 3-5.
                    """},
                    {"role": "user", "content": f"Rate the importance of this conversation (0-5):\n\nUser: {user_message}\nBot: {bot_response}"}
                ],
                temperature=0.3
            )
            result = response.choices[0].message.content.strip()
            
            for char in result:
                if char.isdigit() and int(char) >= 0 and int(char) <= 5:
                    return int(char)
            return 1
            
        except Exception as e:
            log.error(f"Memory evaluation error: {e}")
            return 1

    async def cog_unload(self):
        """Stop background tasks when Cog is unloaded"""
        if self.queue_task and not self.queue_task.done():
            await self.queue.put(None)
            await self.queue_task
        self.executor.shutdown(wait=False)
