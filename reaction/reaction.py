import discord
import aiohttp
from typing import Optional
from redbot.core import commands, app_commands

# 動作名稱對應 Purrbot API v2 路徑
ACTIONS = {
    "slap": "https://api.purrbot.site/v2/img/sfw/slap/gif",
    "hug": "https://api.purrbot.site/v2/img/sfw/hug/gif",
    "kiss": "https://api.purrbot.site/v2/img/sfw/kiss/gif",
    "lick": "https://api.purrbot.site/v2/img/sfw/lick/gif",
}

class Reaction(commands.Cog):
    """提供多種動作指令，如 /slap、/hug、/kiss，使用統一處理流程。"""
    def __init__(self, bot):
        self.bot = bot

    async def _do_action(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        action_key: str,
        display_text: Optional[str] = None,
    ):
        # 防止對自己使用
        if member == interaction.user:
            await interaction.response.send_message("你不能對自己使用這個指令！", ephemeral=True)
            return

        await interaction.response.defer()
        api_url = ACTIONS[action_key]
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                image_url = data.get("link")

        # 決定顯示文字與過去式
        past_text = f"{action_key}ped" if not display_text else f"{display_text}了"

        content = f"{interaction.user.mention} {past_text} {member.mention}!"
        embed = discord.Embed(description=content, color=discord.Color.blue()).set_image(url=image_url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="slap", description="打巴掌！")
    @app_commands.describe(member="要被打的成員")
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "slap", "掌嘴")

    @app_commands.command(name="hug", description="給一個擁抱！")
    @app_commands.describe(member="要被擁抱的成員")
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "hug", "擁抱")

    @app_commands.command(name="kiss", description="飛個吻！")
    @app_commands.describe(member="要被親的成員")
    async def kiss(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "kiss", "親吻")
   
    @app_commands.command(name="lick", description="舔")
    @app_commands.describe(member="要被舔的成員")
    async def lick(self, interaction: discord.Interaction, member: discord.Member):
        await self._do_action(interaction, member, "lick", "舔")