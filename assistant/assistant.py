import base64
from io import BytesIO
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from typing import Optional
import openai
import urllib.parse
import asyncio
import logging

log = logging.getLogger("red.BadwolfCogs.assistant")
logging.getLogger("httpx").setLevel(logging.WARNING)


class OpenAIChat(commands.Cog):
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

        # 初始化訊息處理隊列
        self.queue = asyncio.Queue()
        self.queue_task = None
        self.is_processing = False
        self.should_process = True

        

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    @commands.group()
    @commands.guild_only()
    async def openai(self, ctx: commands.Context):
        """Group command for OpenAI settings."""
        pass

    @openai.command(name="setkey")
    @commands.is_owner()
    async def setkey_owner(self, ctx: commands.Context, key: str):
        """Set the OpenAI API key (Owner only)."""
        encoded_key = self.encode_key(key)
        await self.config.api_key.set(encoded_key)
        await ctx.send("API key has been securely stored.")

    @openai.command()
    @commands.is_owner()
    async def seturl(self, ctx: commands.Context, url_base: str):
        """Set the API base URL for OpenAI requests."""
        parsed_url = urllib.parse.urlparse(url_base)
        if not parsed_url.scheme or not parsed_url.netloc:
            await ctx.send("Invalid URL. Please provide a valid API base URL.")
            return
        await self.config.api_url_base.set(url_base.rstrip("/"))
        await ctx.send(f"API base URL has been set to: {url_base.rstrip('/')}")

    @openai.command()
    @commands.is_owner()
    async def setmodel(self, ctx: commands.Context, model: str):
        """Set the model for OpenAI requests."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to: {model}")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for OpenAI responses in this guild."""
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[str(channel.id)] = {}
        await ctx.send(f"Channel {channel.mention} has been set for OpenAI responses.")
    
    @openai.command()
    @commands.has_permissions(administrator=True)
    async def delchannel(self, ctx: commands.Context):
        """刪除所有已設定的 OpenAI 回應頻道。"""
        async with self.config.guild(ctx.guild).channels() as channels:
            if not channels:
                await ctx.send("目前沒有設定任何 OpenAI 回應頻道。")
                return
            for channel_id in list(channels.keys()):
                channel = ctx.guild.get_channel(int(channel_id))
                if channel:
                    del channels[channel_id]
                    await ctx.send(f"已從設定中移除頻道 {channel.mention}。")
                else:
                    await ctx.send(f"頻道 ID {channel_id} 找不到，無法移除。")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def setprompt(self, ctx: commands.Context, *, prompt: str):
        """Set a custom prompt for this guild."""
        await self.config.guild(ctx.guild).prompt.set(prompt)
        await ctx.send("Custom prompt has been set.")

    @openai.command()
    @commands.is_owner()
    async def setdelay(self, ctx: commands.Context, delay: float):
        """Set the default delay time between requests."""
        if delay < 0:
            await ctx.send("Delay must be greater than or equal to 0 seconds.")
            return
        await self.config.default_delay.set(delay)
        await ctx.send(f"Default delay has been set to {delay} seconds.")

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
            f"User {user_name} (ID: {user_id}) said: \n{user_input}"
        )

        await self.queue.put((message, api_key, api_url_base, model, extended_prompt))
        
        # 如果隊列處理尚未啟動，則啟動它
        if not self.is_processing:
            self.is_processing = True
            self.queue_task = asyncio.create_task(self.process_queue())

    async def process_queue(self):
        """處理訊息隊列，每次處理後等待一段時間"""
        try:
            while self.should_process:
                try:
                    # 從隊列中取得訊息
                    message, api_key, api_url_base, model, prompt = await asyncio.wait_for(
                        self.queue.get(), 
                        timeout=30
                    )
                    
                    # 處理單一訊息
                    response = await self.query_openai(api_key, api_url_base, model, prompt)
                    if response:
                        await self.send_response(message, response)
                    
                    # 標記此訊息已完成處理
                    self.queue.task_done()
                    
                    # 根據 API 限速計算延遲
                    delay = await self.calculate_delay(response, await self.config.default_delay())
                    
                    # 等待計算後的延遲時間
                    await asyncio.sleep(delay)
                    
                except asyncio.TimeoutError:
                    # 如果隊列空了，就停止處理
                    if self.queue.empty():
                        self.is_processing = False
                        break
                        
        except Exception as e:
            log.error(f"Error in process_queue: {e}")
            self.is_processing = False

    async def calculate_delay(self, response: Optional[dict], default_delay: float) -> float:
        """計算延遲時間，根據 x-ratelimit-limit-requests 如果可用，否則使用預設值"""
        if response and "x-ratelimit-limit-requests" in response:
            rate_limit = int(response["x-ratelimit-limit-requests"])
            return max(60 / rate_limit, 1)  # 確保延遲至少 1 秒
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
            log.error(f"Error querying OpenAI: {e}")
            return f"Error: {e}"

    async def cog_unload(self):
        """清理資源"""
        self.should_process = False
        if self.queue_task and not self.queue_task.done():
            self.queue_task.cancel()
            try:
                await self.queue_task
            except asyncio.CancelledError:
                pass
