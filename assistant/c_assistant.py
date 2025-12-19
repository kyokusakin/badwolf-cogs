import discord
import logging
import os
from redbot.core import commands, data_manager
import pathlib

log = logging.getLogger("red.BadwolfCogs.c_assistant")

class AssistantCommands():
    """提供 OpenAI 聊天相關的指令。"""

    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        if not api_key:
            return ""
        if len(api_key) <= 8:
            return "*" * len(api_key)
        return f"{api_key[:4]}...{api_key[-4:]}"

    def chat_histories_path(self) -> pathlib.Path:
        base_path = data_manager.cog_data_path(raw_name="OpenAIChat")
        chat_histories_folder = base_path / "chat_histories"
        os.makedirs(chat_histories_folder, exist_ok=True)
        return chat_histories_folder

    @commands.group()
    @commands.guild_only()
    async def openai(self, ctx: commands.Context):
        """OpenAI 設定指令群組。"""
        pass

    @openai.command(name="setkey")
    @commands.is_owner()
    async def setkey_owner(self, ctx: commands.Context, key: str):
        """設定 OpenAI API 金鑰 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        encoded_key = cog.encode_key(key)
        await cog.config.api_key.set(encoded_key)
        await cog.config.api_keys.set([encoded_key])
        await ctx.send("API 金鑰已安全存儲，並已重設金鑰池（1 把）。")

    @openai.command(name="addkey")
    @commands.is_owner()
    async def addkey_owner(self, ctx: commands.Context, key: str):
        """新增 OpenAI API 金鑰到金鑰池 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        encoded_key = cog.encode_key(key)

        keys = await cog.config.api_keys()
        if not keys:
            legacy = await cog.config.api_key()
            if legacy:
                keys = [legacy]

        if encoded_key in keys:
            await ctx.send("此 API 金鑰已存在於金鑰池中。")
            return

        keys.append(encoded_key)
        await cog.config.api_keys.set(keys)
        await cog.config.api_key.set(keys[0])
        await ctx.send(f"已新增 API 金鑰，目前金鑰池共有 {len(keys)} 把，將以 round-robin 輪詢使用。")

    @openai.command(name="delkey")
    @commands.is_owner()
    async def delkey_owner(self, ctx: commands.Context, index: int):
        """從金鑰池移除指定序號的 API 金鑰 (僅限擁有者)。"""
        if index < 1:
            await ctx.send("序號必須從 1 開始。")
            return

        cog = self.bot.get_cog("OpenAIChat")
        keys = await cog.config.api_keys()

        if not keys:
            legacy = await cog.config.api_key()
            if legacy and index == 1:
                await cog.config.api_key.clear()
                await ctx.send("已清除 legacy API 金鑰。")
                return
            await ctx.send("目前金鑰池是空的（可用 `[p]openai addkey` 新增）。")
            return

        if index > len(keys):
            await ctx.send(f"序號超出範圍，目前金鑰池只有 {len(keys)} 把。")
            return

        removed = keys.pop(index - 1)
        await cog.config.api_keys.set(keys)
        await cog.config.api_key.set(keys[0] if keys else None)

        decoded = cog.decode_key(removed)
        await ctx.send(
            f"已移除第 {index} 把金鑰（{self._mask_api_key(decoded)}），目前剩 {len(keys)} 把。"
        )

    @openai.command(name="listkeys")
    @commands.is_owner()
    async def listkeys_owner(self, ctx: commands.Context):
        """列出已設定的 API 金鑰（遮罩顯示，僅限擁有者）。"""
        cog = self.bot.get_cog("OpenAIChat")
        keys = await cog.config.api_keys()
        source = "金鑰池"

        if not keys:
            legacy = await cog.config.api_key()
            if legacy:
                keys = [legacy]
                source = "legacy"

        if not keys:
            await ctx.send("尚未設定任何 API 金鑰。")
            return

        lines = []
        for i, encoded in enumerate(keys, start=1):
            decoded = cog.decode_key(encoded)
            lines.append(f"{i}. {self._mask_api_key(decoded)}")

        await ctx.send(f"{source}（共 {len(keys)} 把）：\n" + "\n".join(lines))

    @openai.command(name="clearkeys")
    @commands.is_owner()
    async def clearkeys_owner(self, ctx: commands.Context):
        """清除所有 API 金鑰設定 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        await cog.config.api_keys.set([])
        await cog.config.api_key.clear()
        await ctx.send("已清除所有 API 金鑰設定。")

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
    async def chat_command(self, ctx: commands.Context):
        """發送訊息至 OpenAI 並獲得回應。"""
        cog = self.bot.get_cog("OpenAIChat")
        response = await cog.query_openai(ctx.message)
        if response:
            await ctx.send(response)
        else:
            await ctx.send("無法獲得回應。")

    @openai.command(name="clearhistory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearhistory(self, ctx: commands.Context):
        """清除伺服器的聊天歷史記錄。"""
        guild_id = ctx.guild.id
        file_path = os.path.join(str(self.chat_histories_path()), f"{guild_id}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
            await ctx.send("聊天歷史記錄已清除。")
        else:
            await ctx.send("找不到聊天歷史記錄。")
