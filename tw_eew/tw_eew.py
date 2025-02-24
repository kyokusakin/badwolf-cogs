import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from discord.ext import tasks
import aiohttp
import datetime
import logging
import re

log = logging.getLogger("red.BadwolfCogs.tw_eew")

class tweew(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(channel_id=None)
        self.global_config = Config.get_conf(None, identifier=1234567890, cog_name="tweew")
        self.global_config.register_global(api_key=None, latest_earthquake_no=None)
        self.latest_earthquake_no = None
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

    @commands.is_owner()
    @commands.command()
    async def updateeewno(self, ctx, earthquake_no: int):
        """手動更新地震編號"""
        self.latest_earthquake_no = earthquake_no
        # 同步寫入全域 Config
        await self.global_config.latest_earthquake_no.set(earthquake_no)
        await ctx.send(f"地震編號已更新為: {earthquake_no}")

    @commands.is_owner()
    @commands.command()
    async def settweewapikey(self, ctx, api_key: str):
        """設定全局 API 權杖"""
        await self.global_config.api_key.set(api_key)
        await ctx.send(f"API key已設定為: {api_key}")

    @tasks.loop(minutes=1)  # 每1分鐘檢查一次
    async def check_earthquake_map(self):
        """檢查等震度圖是否有更新並在設定的頻道中發布"""
        try:
            # 從全域配置中獲取 API 權杖
            api_key = await self.global_config.api_key()
            if not api_key:
                log.error("未設定 API key")
                return

            api_url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001?Authorization={api_key}&limit=1&format=JSON&AreaName=&StationName=---"

            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    response.raise_for_status()
                    data = await response.json()

            records = data.get('records', {})
            earthquakes = records.get('Earthquake', [])

            if not earthquakes:
                log.error("API 返回的地震數據為空")
                return

            earthquake = earthquakes[0]
            earthquake_no = earthquake.get('EarthquakeNo')
            origin_time = earthquake.get('EarthquakeInfo', {}).get('OriginTime', '未知時間')
            report_content = earthquake.get('ReportContent', '無報告內容')
            report_content_cleaned = re.sub(r'，最大震度.*$', '', report_content).strip()

            # 檢查地震編號是否與上次不同
            if earthquake_no != self.latest_earthquake_no:
                self.latest_earthquake_no = earthquake_no
                await self.global_config.latest_earthquake_no.set(earthquake_no)

                report_image_url = earthquake.get('ReportImageURI', '')

                description = (
                    f"**地震編號**: {earthquake_no}\n"
                    f"**報告內容**: {report_content_cleaned}\n"
                    f"**地震發生時間**: {origin_time}\n"
                    f"**詳細資料**: [點此查看報告]({earthquake.get('Web', '')})\n"
                    "\n**震度分布**:\n"
                )

                intensity_areas = earthquake.get('Intensity', {}).get('ShakingArea', [])
                intensity_dict = {}
                for area in intensity_areas:
                    counties = area.get('CountyName', '未知').split('、')
                    area_intensity = area.get('AreaIntensity', '未知')
                    for county in counties:
                        if area_intensity not in intensity_dict:
                            intensity_dict[area_intensity] = set()
                        intensity_dict[area_intensity].add(county)

                sorted_intensities = sorted(intensity_dict.items(), key=lambda x: x[0], reverse=True)

                for intensity, counties in sorted_intensities:
                    description += f"{', '.join(counties)} {intensity}\n"

                for guild in self.bot.guilds:
                    channel_id = await self.config.guild(guild).channel_id()
                    if channel_id:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            embed = discord.Embed(
                                title="最新地震報告",
                                description=description,
                                color=discord.Color.blue(),
                            )
                            if report_image_url:
                                embed.set_image(url=report_image_url)
                            embed.set_footer(text="資料為中華民國中央氣象署提供")
                            await channel.send(embed=embed)

        except aiohttp.ClientError as e:
            log.error("發送請求時發生錯誤: %s", e)
        except KeyError as e:
            log.error("解析 API 回應時發生錯誤: %s", e)
        except Exception as e:
            log.error("檢查地震報告時發生錯誤: %s", e)

    @check_earthquake_map.before_loop
    async def before_check_earthquake_map(self):
        await self.bot.wait_until_ready()
        self.latest_earthquake_no = await self.global_config.latest_earthquake_no()
