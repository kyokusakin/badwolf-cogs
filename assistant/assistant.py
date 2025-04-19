import asyncio
import base64
import logging
import os
import json
import aiofiles
import time
import discord
import openai
import pathlib
from redbot.core import Config, commands, data_manager
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
    
    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    def chat_histories_path(self) -> pathlib.Path:
        base_path = data_manager.cog_data_path(raw_name="OpenAIChat")
        chat_histories_folder = base_path / "chat_histories"
        os.makedirs(chat_histories_folder, exist_ok=True)
        return chat_histories_folder

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
            #log.info(f"\nGuild ID:{message.guild.id}\nUser: {message.author.display_name}({message.author.id})\nUser Message: {message.content}\nBot response: {response}\nImportance: {importance}")

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
        file_path = os.path.join(str(self.chat_histories_path()), f"{guild_id}.json")
        if os.path.exists(file_path):
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    return json.loads(content)
            except Exception as e:
                log.error(f"Error loading chat history: {e}")
                return []
        return []

    async def save_chat_history(self, guild_id: int, user_id: int, user_name: str, user_message: str, bot_response: str, importance: int = 1):
        """Asynchronously save chat history with timestamp and importance rating"""
        file_path = os.path.join(str(self.chat_histories_path()), f"{guild_id}.json")
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
        """优化后的记忆筛选逻辑，确保严格的数量控制和更合理的记忆排序"""
        # 分离短期记忆（按时间倒序）
        short_term = sorted(
            [r for r in history if current_time - r.get("timestamp", 0) <= short_term_seconds],
            key=lambda x: x["timestamp"],
            reverse=True
        )[:max_records]  # 直接限制最大数量

        # 剩余可补充的长期记忆数量
        remaining_slots = max(0, max_records - len(short_term))

        # 长期记忆处理（按重要性和时间综合排序）
        long_term = [
            r for r in history 
            if current_time - r.get("timestamp", 0) > short_term_seconds
            and r not in short_term
        ]

        # 优先保留高重要性且较新的记忆
        long_term.sort(
            key=lambda x: (-x.get("importance", 1), -x.get("timestamp", 0))
        )

        # 合并最终记录（保留原始时间顺序）
        combined = (short_term + long_term[:remaining_slots])[:max_records]
        combined.sort(key=lambda x: x["timestamp"])  # 按时间正序排列

        # 格式化历史字符串
        return "\n".join(
            f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(entry['timestamp']))}] "
            f"{entry['user_name']}: {entry['user_message']}\n"
            f"{bot_name}: {entry['bot_response']}"
            for entry in combined
        )


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
        """强化版记忆评分提示词"""
        import re
        
        try:
            client = openai.OpenAI(api_key=api_key, base_url=api_url_base)
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "system",
                    "content": """# 记忆价值评估专家
    
    ## 任务说明
    用[[数字]]格式(0-5)评估以下对话的记忆存储价值
    
    ## 评分标准
    0️⃣ 无价值：日常寒暄/重复内容  
      例："早安"、"哈哈真好笑"
    
    1️⃣ 低价值：简单事实询问  
      例："今天星期几？"、"天气如何？"
    
    2️⃣ 基础价值：一次性实用信息  
      例："推荐附近的餐厅"、"翻译这句话"
    
    3️⃣ 中等价值：个人偏好/常规需求  
      例："我喜歡藍色"、"常用Python编程"
    
    4️⃣ 高价值：情感交流/重要习惯  
      例："我失戀了很難過"、"每天晨跑是我的習慣"
    
    5️⃣ 关键价值：安全相关/长期承诺  
      例："我对花生过敏"、"下个月要结婚"
    
    ## 特殊情形
    ⚠️ 包含这些内容自动+2分：
    - 过敏/疾病信息
    - 长期习惯
    - 重要日程
    - 情感状态变化
    
    ## 输出格式
    严格按此格式：「[[数字]]」
    示例：「[[3]]」""",
                }, {
                    "role": "user",
                    "content": f"[对话内容]\n用户：{user_message}\nAI：{bot_response}"
                }],
                temperature=0.1,
                max_tokens=10
            )
            
            # 强化格式匹配
            match = re.search(r'「\[\[(\d)]]」', response.choices[0].message.content)
            if match:
                score = int(match.group(1))
                return min(max(score, 0), 5)  # 双重保险
            return 1  # 格式错误默认值
        except Exception as e:
            log.error(f"记忆评分故障: {str(e)[:150]}")
            return 1

    async def cog_unload(self):
        """Stop background tasks when Cog is unloaded"""
        if self.queue_task and not self.queue_task.done():
            await self.queue.put(None)
            await self.queue_task
        self.executor.shutdown(wait=False)
