import discord
import logging
import os
from redbot.core import commands

log = logging.getLogger("red.BadwolfCogs.c_assistant")

class AssistantCommands():
    """提供 OpenAI 聊天相關的指令。"""

    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @commands.group()
    @commands.guild_only()
    async def openai(self, ctx: commands.Context):
        """OpenAI 設定指令群組。"""
        pass

    @openai.command(name="setkey")
    @commands.is_owner()
    async def setkey_owner(self, ctx: commands.Context, key: str):
        """設定 OpenAI API 金鑰 (僅限擁有者)。"""
        encoded_key = self.bot.get_cog("OpenAIChat").encode_key(key)
        await self.bot.get_cog("OpenAIChat").config.api_key.set(encoded_key)
        await ctx.send("API 金鑰已安全存儲。")

    @openai.command()
    @commands.is_owner()
    async def seturl(self, ctx: commands.Context, url_base: str):
        """設定 OpenAI API 的基礎 URL。"""
        await self.bot.get_cog("OpenAIChat").config.api_url_base.set(url_base.rstrip("/"))
        await ctx.send(f"API 基礎 URL 已設置為: {url_base.rstrip('/')}")

    @openai.command()
    @commands.is_owner()
    async def setmodel(self, ctx: commands.Context, model: str):
        """設定 OpenAI 使用的模型。"""
        await self.bot.get_cog("OpenAIChat").config.model.set(model)
        await ctx.send(f"模型已設置為: {model}")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """設定 OpenAI 回應的頻道。"""
        async with self.bot.get_cog("OpenAIChat").config.guild(ctx.guild).channels() as channels:
            channels[str(channel.id)] = {}
        await ctx.send(f"頻道 {channel.mention} 已設置為 OpenAI 回應頻道。")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def delchannel(self, ctx: commands.Context):
        """刪除所有已設定的 OpenAI 回應頻道。"""
        async with self.bot.get_cog("OpenAIChat").config.guild(ctx.guild).channels() as channels:
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
        """設定自訂提示詞 (Prompt)。"""
        await self.bot.get_cog("OpenAIChat").config.guild(ctx.guild).prompt.set(prompt)
        await ctx.send("自訂提示詞已設置。")

    @openai.command()
    @commands.is_owner()
    async def setdelay(self, ctx: commands.Context, delay: float):
        """設定請求之間的延遲時間。"""
        if delay < 0:
            await ctx.send("延遲時間必須大於等於 0 秒。")
            return
        await self.bot.get_cog("OpenAIChat").config.default_delay.set(delay)
        await ctx.send(f"延遲時間已設置為 {delay} 秒。")

    @openai.command(name="chat")
    @commands.guild_only()
    async def chat_command(self, ctx: commands.Context, *, user_input: str):
        """發送訊息至 OpenAI 並獲得回應。"""
        cog = self.bot.get_cog("OpenAIChat")
        response = await cog.query_openai(
            await cog.config.api_key(),
            await cog.config.api_url_base(),
            await cog.config.model(),
            await cog.config.guild(ctx.guild).prompt(),
            guild_history = None,
            user_input = user_input
        )
        await ctx.reply(response)

    @openai.command(name="clearhistory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearhistory(self, ctx: commands.Context):
        """清除伺服器的聊天歷史記錄。"""
        file_path = os.path.join(os.path.dirname(__file__), "chat_histories", f"{ctx.guild.id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
            await ctx.send("聊天歷史記錄已清除。")
        else:
            await ctx.send("找不到聊天歷史記錄。")
