import base64
from io import BytesIO
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from typing import Optional
import openai
import urllib.parse
import asyncio

class OpenAIChat(commands.Cog):
    """A RedBot cog for OpenAI API integration with advanced features."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {
            "api_key": None,
            "api_url_base": "https://api.openai.com/v1",
            "model": "gpt-4",
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

    def encode_image(self, image_path) -> str:
        """將圖片轉換為 base64 字串"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

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

            # 顯示所有已設定的頻道並刪除
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

        # 檢查圖片附件
        image_data = None
        if message.attachments:
            for attachment in message.attachments:
                if attachment.url.lower().endswith(('jpg', 'jpeg', 'png', 'gif')):
                    image_data = await attachment.read()  # 讀取附件圖片

        if not user_input and not image_data:
            return

        api_key = await self.config.api_key()
        
        if not api_key:
            await message.channel.send("API key not set. Only the bot owner can set the key.")
            return

        api_key = self.decode_key(api_key)
        api_url_base = await self.config.api_url_base()
        model = await self.config.model()

        # 將訊息加入隊列
        if image_data:
            # 轉換圖片為 base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            prompt += f"\n[Image: data:image/jpeg;base64,{base64_image}]"

        await self.queue.put((message, api_key, api_url_base, model, prompt + "\n" + user_input))
        
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
                    
                    # 等待 3 秒後再處理下一條訊息
                    await asyncio.sleep(3)
                    
                except asyncio.TimeoutError:
                    # 如果隊列空了，就停止處理
                    if self.queue.empty():
                        self.is_processing = False
                        break
                        
        except Exception as e:
            print(f"Error in process_queue: {e}")
            self.is_processing = False

    async def send_response(self, message: discord.Message, response: str):
        """發送回應"""
        try:
            await message.reply(response)
        except discord.DiscordException as e:
            try:
                await message.channel.send(f"Error: {e}")
            except:
                print(f"Failed to send response: {e}")

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
