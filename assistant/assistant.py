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
        asyncio.create_task(self.initialize())
    
    async def initialize(self):
        """初始化組件並建立聊天歷史資料夾"""
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
        """向 OpenAI API 查詢並回傳回應內容"""
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

        # 載入聊天歷史
        history = await self.load_chat_history(message.guild.id)
        if not history:
            history = []

        # 建構分層記憶內容，使用短期與長期記憶動態裁剪
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

        return self._blocking_openai_request(api_key, api_url_base, model, sysprompt, guild_history, formatted_user_input)

    def _blocking_openai_request(
        self, api_key: str, api_url_base: str, model: str,
        prompt: str, guild_history: str, user_input: str
    ) -> Optional[str]:
        """同步呼叫 OpenAI API，改用新版介面"""
        try:
            # 設定全域 API 金鑰與基底網址
            openai.api_key = api_key
            openai.api_base = api_url_base
            response = openai.ChatCompletion.create(
                model=model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "assistant", "content": "Chat histories:\n" + guild_history + "\nChat histories end."},
                    {"role": "user", "content": user_input}
                ]
            )
            return response.choices[0].message.content
        except openai.OpenAIError as e:
            log.error(f"OpenAI error: {e}")
            return f"⚠️ API 錯誤：{e}"

    async def process_queue(self):
        """背景任務：處理排程中的訊息"""
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
                log.error(f"處理排程時出錯: {e}")

    async def process_response(self, message: discord.Message, response: str):
        """處理回應並依據 AI 評估結果決定是否儲存記憶"""
        if response:
            await self.send_response(message, response)
            # 讓 AI 評估此次對話的重要性
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
            else:
                log.info("AI 評估此對話不需要儲存記憶")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """監聽訊息事件"""
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
        """非同步載入指定公會的聊天歷史"""
        file_path = os.path.join(self.chat_histories_path, f"{guild_id}.json")
        if os.path.exists(file_path):
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    return json.loads(content)
            except Exception as e:
                log.error(f"載入聊天歷史錯誤: {e}")
                return []
        return []

    async def save_chat_history(self, guild_id: int, user_id: int, user_name: str,
                                user_message: str, bot_response: str, importance: int = 1):
        """非同步儲存聊天歷史，加入時間戳記與重要性評分"""
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
            log.error(f"儲存聊天歷史錯誤: {e}")

    async def build_guild_history(self, history: List[Dict], current_time: float,
                                  short_term_seconds: int, max_records: int, bot_name: str) -> str:
        """
        根據短期與長期記憶動態裁剪聊天歷史，返回用於上下文的字串。
        短期記憶：最近 short_term_seconds 秒內的記錄
        長期記憶：其餘記錄中依重要性排序，取最高重要性的記錄，且總筆數不超過 max_records
        """
        # 分離短期記憶與長期記憶
        short_term = [
            record for record in history 
            if current_time - record.get("timestamp", 0) <= short_term_seconds
        ]
        long_term = [
            record for record in history 
            if current_time - record.get("timestamp", 0) > short_term_seconds
        ]

        # 對長期記憶依重要性及時間排序（重要性高且較新的優先）
        long_term.sort(key=lambda x: (x.get("importance", 1), x.get("timestamp", 0)), reverse=True)

        # 計算可容納的長期記憶數量
        remaining_slots = max_records - len(short_term)
        selected_long_term = long_term[:remaining_slots] if remaining_slots > 0 else []

        # 合併短期與長期記憶並依時間排序（由舊到新）
        combined = short_term + selected_long_term
        combined.sort(key=lambda x: x.get("timestamp", 0))

        # 建構歷史字串，每筆記錄格式：
        # {user_name} (ID: {user_id}): {user_message}
        # {bot_name}: {bot_response}
        history_str = ""
        for entry in combined:
            history_str += (
                f"\n{entry['user_name']} (ID: {entry['user_id']}): {entry['user_message']}"
                f"\n{bot_name}: {entry['bot_response']}"
            )
        return history_str

    async def evaluate_memory(self, user_message: str, bot_response: str) -> int:
        """
        讓 AI 評估此次對話的記憶重要性，回傳 0~5 的數值
        0 表示不重要，不儲存；數字越高表示重要性越高
        """
        # 以 asyncio.to_thread 包裝同步函式
        return await asyncio.to_thread(self._blocking_evaluate_memory, user_message, bot_response)

    def _blocking_evaluate_memory(self, user_message: str, bot_response: str) -> int:
        """
        同步呼叫 OpenAI API 評估記憶重要性
        請求格式要求僅回覆一個數字（0~5）
        """
        try:
            prompt = (
                "請評估以下對話的記憶重要性，"
                "並以數字表示（0 表示不重要，不儲存；1 至 5 表示重要性程度，數字越高表示越重要）。\n\n"
                f"用戶訊息: {user_message}\n"
                f"機器人回應: {bot_response}\n\n"
                "請僅回覆一個數字，不需要其他文字。"
            )
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "system", "content": prompt}]
            )
            result = response.choices[0].message.content.strip()
            importance = int(result)
            # 限制評分範圍 0~5
            importance = max(0, min(5, importance))
            return importance
        except Exception as e:
            log.error(f"記憶評估錯誤: {e}")
            return 1  # 若評估失敗，預設重要性為 1

    async def cog_unload(self):
        """Cog 卸載時停止背景任務"""
        if self.queue_task and not self.queue_task.done():
            await self.queue.put(None)
            await self.queue_task
