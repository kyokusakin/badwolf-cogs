# c_assistant.py
import os
import discord
import logging
from redbot.core import commands
from urllib.parse import urlparse, parse_qs
from .sql_assistant import SQLAssistant

log = logging.getLogger("red.BadwolfCogs.sql_assistant")

class AssistantCommands(SQLAssistant):
    """提供 OpenAI 聊天相關的指令。"""

    def __init__(self, bot):
        self.bot = bot
        self.sql = SQLAssistant(bot)
        bot.loop.create_task(self.sql.initialize())

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
            user_input
        )
        await ctx.reply(response)

    @openai.group(name="sql")
    @commands.is_owner()
    async def openai_sql(self, ctx: commands.Context):
        """Configure OpenAI SQL settings"""
        pass
    
    @openai_sql.command()
    async def host(self, ctx: commands.Context, host: str):
        """Set SQL host."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        await sql_assistant.set_sql_setting("host", host)
        await ctx.send(f"SQL host set to {host}")
    
    @openai_sql.command()
    async def port(self, ctx: commands.Context, port: int):
        """Set SQL port."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        await sql_assistant.set_sql_setting("port", port)
        await ctx.send(f"SQL port set to {port}")
    
    @openai_sql.command()
    async def user(self, ctx: commands.Context, user: str):
        """Set SQL user."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        await sql_assistant.set_sql_setting("user", user)
        await ctx.send(f"SQL user set to {user}")
    
    @openai_sql.command()
    async def password(self, ctx: commands.Context, password: str):
        """Set SQL password."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        await sql_assistant.set_sql_setting("password", password)
        await ctx.send("SQL password has been set.")
    
    @openai_sql.command()
    async def database(self, ctx: commands.Context, database: str):
        """Set SQL database name."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        await sql_assistant.set_sql_setting("database", database)
        await ctx.send(f"SQL database set to {database}")

    @openai_sql.command(name="connectstr")
    async def sql_connectstr(self, ctx: commands.Context, mysql_url: str):
        """Set SQL connection string."""
        sql_assistant = self.bot.get_cog("OpenAIChat")
        try:
            # Remove 'mysql://' if present
            if mysql_url.startswith('mysql://'):
                mysql_url = mysql_url[len('mysql://'):]
            
            # Parse the URL
            parsed = urlparse(f'//{mysql_url}')
            params = parse_qs(parsed.query)
    
            # Extract components
            user_pass, host_port = parsed.netloc.split('@')
            user, password = user_pass.split(':') if ':' in user_pass else (user_pass, '')
            host, port = host_port.split(':') if ':' in host_port else (host_port, '3306')
            
            port = int(port)
            database = parsed.path.lstrip('/')
            
            # Set each component
            await sql_assistant.set_sql_setting("host", host)
            await sql_assistant.set_sql_setting("port", port)
            await sql_assistant.set_sql_setting("user", user)
            await sql_assistant.set_sql_setting("password", password)
            await sql_assistant.set_sql_setting("database", database)

            await ctx.send(f"SQL connection settings configured:\n"
                         f"Host: {host}\n"
                         f"Port: {port}\n"
                         f"User: {user}\n"
                         f"Password: [Set]\n"
                         f"Database: {database}")

        except Exception as e:
            await ctx.send(f"Error setting SQL connection: {e}")