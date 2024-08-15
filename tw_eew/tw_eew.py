import discord
from redbot.core import commands, tasks, Config
from redbot.core.bot import Red
import requests
from io import BytesIO
import datetime

class EarthquakeMapMonitor(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(channel_id=None)  # 每個伺服器的預設頻道 ID 為 None
        self.latest_identifier = None  # 儲存最近一次的等震度圖識別碼
        self.init_tasks()

    def init_tasks(self):
        """初始化定時任務"""
        self.check_earthquake_map.start()  # 開始定時檢查

    def cog_unload(self):
        """取消任務"""
        self.check_earthquake_map.cancel()

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    async def setquakechannel(self, ctx, channel: discord.TextChannel):
        """設定接收等震度圖更新的頻道"""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"等震度圖更新頻道已設定為: {channel.mention}")

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    async def clearquakechannel(self, ctx):
        """清除等震度圖更新頻道設定"""
        await self.config.guild(ctx.guild).channel_id.set(None)
        await ctx.send("等震度圖更新頻道已清除。")

    @tasks.loop(minutes=10)  # 每10分鐘檢查一次
    async def check_earthquake_map(self):
        """檢查等震度圖是否有更新並在設定的頻道中發布"""
        try:
            # API URL
            api_url = "https://opendata.cwa.gov.tw/"#set to yours

            # 發送 GET 請求
            response = requests.get(api_url)
            response.raise_for_status()

            # 解析 JSON 回應
            data = response.json()
            identifier = data['cwaopendata']['identifier']

            # 檢查識別碼是否與上次不同
            if identifier != self.latest_identifier:
                self.latest_identifier = identifier  # 更新識別碼

                # 找到等震度圖的 URL
                product_url = data['cwaopendata']['Dataset']['Resource']['ProductURL']

                # 下載等震度圖
                img_response = requests.get(product_url)
                img_response.raise_for_status()

                # 使用 BytesIO 儲存圖片數據
                image_data = BytesIO(img_response.content)

                # 為所有設定了頻道的伺服器發送更新
                for guild in self.bot.guilds:
                    channel_id = await self.config.guild(guild).channel_id()
                    if channel_id:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            embed = discord.Embed(
                                title="最新等震度圖更新",
                                description=f"識別碼: {identifier}\n發送時間: {datetime.datetime.now()}",
                                color=discord.Color.blue(),
                            )
                            embed.set_image(url="attachment://quake_map.png")
                            embed.set_footer(text="由中央氣象局提供的等震度圖")
                            await channel.send(embed=embed, file=discord.File(fp=image_data, filename="quake_map.png"))

        except Exception as e:
            print(f"檢查等震度圖時發生錯誤: {e}")

    @check_earthquake_map.before_loop
    async def before_check_earthquake_map(self):
        await self.bot.wait_until_ready()
