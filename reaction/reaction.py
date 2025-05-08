import discord
import aiohttp
from redbot.core import commands, app_commands

# 動作名稱對應 Purrbot API v2 路徑
ACTIONS = {
    "slap": "https://api.purrbot.site/v2/img/sfw/slap/gif",
    "hug": "https://api.purrbot.site/v2/img/sfw/hug/gif",
    "kiss": "https://api.purrbot.site/v2/img/sfw/kiss/gif",
    "lick": "https://api.purrbot.site/v2/img/sfw/lick/gif",
}

class ReactionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _do_action(self, interaction: discord.Interaction, member: discord.Member, action: str):
        """
        共用動作處理：
        1. 從 ACTIONS 取得 v2 API URL
        2. 非同步呼叫取得 GIF
        3. 建立並回傳 Embed
        """
        await interaction.response.defer()
        api_url = ACTIONS[action]
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                image_url = data.get("link")

        title = f"{interaction.user.mention} {action} {member.mention}"
        embed = discord.Embed(title=title, color=discord.Color.blue()).set_image(url=image_url)
        await interaction.followup.send(embed=embed)

###############################################################################

    @app_commands.command(name="slap", description="打巴掌！")
    @app_commands.describe(member="要被打的成員")
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "slap")

    @app_commands.command(name="hug", description="給一個擁抱！")
    @app_commands.describe(member="要被擁抱的成員")
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "hug")

    @app_commands.command(name="kiss", description="飛個吻！")
    @app_commands.describe(member="要被親的成員")
    async def kiss(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "kiss")
    
    @app_commands.command(name="lick", description="舔！")
    @app_commands.describe(member="要被舔的成員")
    async def lick(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "lick")