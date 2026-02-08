import discord
import logging
import os
import time
from redbot.core import commands, data_manager
import pathlib

log = logging.getLogger("red.BadwolfCogs.c_assistant")

class AssistantCommands():
    """提供 Gemini 聊天相關的指令。"""

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
        """Gemini 設定指令群組。"""
        pass

    @openai.command(name="setkey")
    @commands.is_owner()
    async def setkey_owner(self, ctx: commands.Context, key: str):
        """設定 Gemini API 金鑰 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        encoded_key = cog.encode_key(key)
        await cog.config.api_keys.set({encoded_key: True})
        await ctx.send("API 金鑰已安全存儲，並已重設金鑰池（1 把）。")

    @openai.command(name="addkey")
    @commands.is_owner()
    async def addkey_owner(self, ctx: commands.Context, key: str):
        """新增 Gemini API 金鑰到金鑰池 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        encoded_key = cog.encode_key(key)

        raw_keys = await cog.config.api_keys()
        key_map = dict(raw_keys) if isinstance(raw_keys, dict) else {}

        if encoded_key in key_map:
            await ctx.send("此 API 金鑰已存在於金鑰池中。")
            return

        key_map[encoded_key] = True
        await cog.config.api_keys.set(key_map)
        await ctx.send(f"已新增 API 金鑰，目前金鑰池共有 {len(key_map)} 把，將以 round-robin 輪詢使用。")

    @openai.command(name="delkey")
    @commands.is_owner()
    async def delkey_owner(self, ctx: commands.Context, index: int):
        """從金鑰池移除指定序號的 API 金鑰 (僅限擁有者)。"""
        if index < 1:
            await ctx.send("序號必須從 1 開始。")
            return

        cog = self.bot.get_cog("OpenAIChat")
        raw_keys = await cog.config.api_keys()
        key_map = dict(raw_keys) if isinstance(raw_keys, dict) else {}

        keys = [k for k, enabled in key_map.items() if enabled]

        if not keys:
            await ctx.send("目前金鑰池是空的（可用 `[p]genai addkey` 新增）。")
            return

        if index > len(keys):
            await ctx.send(f"序號超出範圍，目前金鑰池只有 {len(keys)} 把。")
            return

        removed = keys[index - 1]
        key_map.pop(removed, None)

        await cog.config.api_keys.set(key_map)
        remaining = sum(1 for enabled in key_map.values() if enabled)

        decoded = cog.decode_key(removed)
        await ctx.send(
            f"已移除第 {index} 把金鑰（{self._mask_api_key(decoded)}），目前剩 {remaining} 把。"
        )

    @openai.command(name="listkeys")
    @commands.is_owner()
    async def listkeys_owner(self, ctx: commands.Context):
        """列出已設定的 API 金鑰（遮罩顯示，僅限擁有者）。"""
        cog = self.bot.get_cog("OpenAIChat")
        raw_keys = await cog.config.api_keys()
        keys = [k for k, enabled in raw_keys.items() if enabled] if isinstance(raw_keys, dict) else []

        if not keys:
            await ctx.send("尚未設定任何 API 金鑰。")
            return

        lines = []
        for i, encoded in enumerate(keys, start=1):
            decoded = cog.decode_key(encoded)
            lines.append(f"{i}. {self._mask_api_key(decoded)}")

        await ctx.send(f"已設定的 API 金鑰（共 {len(keys)} 把）：\n" + "\n".join(lines))

    @openai.command(name="clearkeys")
    @commands.is_owner()
    async def clearkeys_owner(self, ctx: commands.Context):
        """清除所有 API 金鑰設定 (僅限擁有者)。"""
        cog = self.bot.get_cog("OpenAIChat")
        await cog.config.api_keys.set({})
        await ctx.send("已清除所有 API 金鑰設定。")

    @openai.command()
    @commands.is_owner()
    async def setmodel(self, ctx: commands.Context, model: str):
        """設定 Gemini 使用的模型（例如 gemini-2.0-flash）。"""
        await self.bot.get_cog("OpenAIChat").config.model.set(model)
        await ctx.send(f"模型已設置為: {model}")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """設定 Gemini 回應的頻道。"""
        async with self.bot.get_cog("OpenAIChat").config.guild(ctx.guild).channels() as channels:
            channels[str(channel.id)] = {}
        await ctx.send(f"頻道 {channel.mention} 已設置為 Gemini 回應頻道。")

    @openai.command()
    @commands.has_permissions(administrator=True)
    async def delchannel(self, ctx: commands.Context):
        """刪除所有已設定的 Gemini 回應頻道。"""
        async with self.bot.get_cog("OpenAIChat").config.guild(ctx.guild).channels() as channels:
            if not channels:
                await ctx.send("目前沒有設定任何 Gemini 回應頻道。")
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

    @openai.command(name="memory")
    @commands.guild_only()
    async def memory_settings(self, ctx: commands.Context):
        """顯示目前伺服器的記憶系統設定。"""
        cog = self.bot.get_cog("OpenAIChat")
        conf = cog.config.guild(ctx.guild)

        short_term_seconds = await conf.memory_short_term_seconds()
        context_max_records = await conf.memory_context_max_records()
        short_term_max_records = await conf.memory_short_term_max_records()
        long_term_min_importance = await conf.memory_long_term_min_importance()
        max_field_chars = await conf.memory_max_field_chars()
        history_max_records = await conf.memory_history_max_records()
        relevance_max_tokens = await conf.memory_relevance_max_tokens()
        chat_retention_seconds = await conf.memory_chat_retention_seconds()
        retention_days = await conf.memory_retention_days()
        long_term_enabled = await conf.memory_long_term_enabled()
        long_term_max_records = await conf.memory_long_term_max_records()
        long_term_fetch_limit = await conf.memory_long_term_fetch_limit()
        guild_long_term_enabled = await conf.memory_guild_long_term_enabled()
        guild_retention_days = await conf.memory_guild_retention_days()
        guild_long_term_max_records = await conf.memory_guild_long_term_max_records()
        guild_long_term_fetch_limit = await conf.memory_guild_long_term_fetch_limit()
        guild_auto_upgrade_enabled = await conf.memory_guild_auto_upgrade_enabled()
        guild_upgrade_min_score = await conf.memory_guild_upgrade_min_score()
        embedding_enabled = await conf.memory_embedding_enabled()
        embedding_model = await conf.memory_embedding_model()
        embedding_top_k = await conf.memory_embedding_top_k()
        guild_embedding_top_k = await conf.memory_guild_embedding_top_k()
        opt_out_ids = await conf.memory_opt_out_user_ids()

        await ctx.send(
            "記憶系統設定：\n"
            f"- short_term_seconds: {short_term_seconds}\n"
            f"- context_max_records: {context_max_records}\n"
            f"- short_term_max_records: {short_term_max_records} (0 = 自動)\n"
            f"- long_term_min_importance: {long_term_min_importance}\n"
            f"- max_field_chars: {max_field_chars}\n"
            f"- history_max_records: {history_max_records} (0 = 不修剪)\n"
            f"- relevance_max_tokens: {relevance_max_tokens}\n"
            f"- chat_retention_seconds: {chat_retention_seconds} (0 = 不落盤)\n"
            f"- retention_days: {retention_days} (0 = 永久保存)\n"
            f"- long_term_enabled: {long_term_enabled}\n"
            f"- long_term_max_records: {long_term_max_records}\n"
            f"- long_term_fetch_limit: {long_term_fetch_limit}\n"
            f"- guild_long_term_enabled: {guild_long_term_enabled}\n"
            f"- guild_retention_days: {guild_retention_days} (0 = 永久保存)\n"
            f"- guild_long_term_max_records: {guild_long_term_max_records}\n"
            f"- guild_long_term_fetch_limit: {guild_long_term_fetch_limit}\n"
            f"- guild_auto_upgrade_enabled: {guild_auto_upgrade_enabled}\n"
            f"- guild_upgrade_min_score: {guild_upgrade_min_score}\n"
            f"- embedding_enabled: {embedding_enabled}\n"
            f"- embedding_model: {embedding_model}\n"
            f"- embedding_top_k: {embedding_top_k}\n"
            f"- guild_embedding_top_k: {guild_embedding_top_k}\n"
            f"- opt_out_users: {len(opt_out_ids) if isinstance(opt_out_ids, list) else 0}\n"
            "\n"
            "設定方式：`[p]openai setmemory <key> <value>`"
        )

    @openai.command(name="setmemory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setmemory(self, ctx: commands.Context, key: str, *, value: str):
        """調整記憶系統設定（管理員）。例如：`[p]openai setmemory context_max_records 20`"""
        cog = self.bot.get_cog("OpenAIChat")
        conf = cog.config.guild(ctx.guild)

        key = (key or "").strip().lower()
        key_map = {
            "short_term_seconds": ("memory_short_term_seconds", "int"),
            "context_max_records": ("memory_context_max_records", "int"),
            "short_term_max_records": ("memory_short_term_max_records", "int"),
            "long_term_min_importance": ("memory_long_term_min_importance", "int"),
            "max_field_chars": ("memory_max_field_chars", "int"),
            "history_max_records": ("memory_history_max_records", "int"),
            "relevance_max_tokens": ("memory_relevance_max_tokens", "int"),
            "chat_retention_seconds": ("memory_chat_retention_seconds", "int"),
            "retention_days": ("memory_retention_days", "int"),
            "long_term_enabled": ("memory_long_term_enabled", "bool"),
            "long_term_max_records": ("memory_long_term_max_records", "int"),
            "long_term_fetch_limit": ("memory_long_term_fetch_limit", "int"),
            "guild_long_term_enabled": ("memory_guild_long_term_enabled", "bool"),
            "guild_retention_days": ("memory_guild_retention_days", "int"),
            "guild_long_term_max_records": ("memory_guild_long_term_max_records", "int"),
            "guild_long_term_fetch_limit": ("memory_guild_long_term_fetch_limit", "int"),
            "guild_auto_upgrade_enabled": ("memory_guild_auto_upgrade_enabled", "bool"),
            "guild_upgrade_min_score": ("memory_guild_upgrade_min_score", "int"),
            "embedding_enabled": ("memory_embedding_enabled", "bool"),
            "embedding_model": ("memory_embedding_model", "str"),
            "embedding_top_k": ("memory_embedding_top_k", "int"),
            "guild_embedding_top_k": ("memory_guild_embedding_top_k", "int"),
        }

        field_info = key_map.get(key)
        if not field_info:
            await ctx.send(
                "不支援的 key。可用 key：\n"
                + "\n".join(f"- {k}" for k in key_map.keys())
            )
            return

        field, kind = field_info
        raw_value = (value or "").strip()

        def parse_bool(s: str):
            v = s.strip().lower()
            if v in ("1", "true", "on", "yes", "y"):
                return True
            if v in ("0", "false", "off", "no", "n"):
                return False
            return None

        parsed_value = None
        if kind == "int":
            try:
                parsed_value = int(raw_value)
            except ValueError:
                await ctx.send("此 key 需要整數 value。")
                return
        elif kind == "bool":
            parsed_value = parse_bool(raw_value)
            if parsed_value is None:
                await ctx.send("此 key 需要布林 value（0/1/true/false/on/off）。")
                return
        elif kind == "str":
            parsed_value = raw_value
            if not parsed_value:
                await ctx.send("此 key 需要非空字串 value。")
                return
        else:
            await ctx.send("不支援的設定型別。")
            return

        if field == "memory_long_term_min_importance" and not (0 <= int(parsed_value) <= 5):
            await ctx.send("long_term_min_importance 必須在 0~5。")
            return
        if field == "memory_guild_upgrade_min_score" and not (0 <= int(parsed_value) <= 5):
            await ctx.send("guild_upgrade_min_score 必須在 0~5。")
            return
        if field == "memory_max_field_chars" and int(parsed_value) < 80:
            await ctx.send("max_field_chars 建議至少 80。")
            return
        if field in (
            "memory_context_max_records",
            "memory_short_term_max_records",
            "memory_short_term_seconds",
            "memory_history_max_records",
            "memory_relevance_max_tokens",
            "memory_chat_retention_seconds",
            "memory_retention_days",
            "memory_long_term_max_records",
            "memory_long_term_fetch_limit",
            "memory_guild_retention_days",
            "memory_guild_long_term_max_records",
            "memory_guild_long_term_fetch_limit",
            "memory_embedding_top_k",
            "memory_guild_embedding_top_k",
        ) and kind == "int" and int(parsed_value) < 0:
            await ctx.send(f"{key} 必須 >= 0。")
            return

        await getattr(conf, field).set(parsed_value)
        await ctx.send(f"已更新 `{key}` = {parsed_value}")

    @openai.command(name="optout")
    @commands.guild_only()
    async def optout(self, ctx: commands.Context):
        """使用者選擇退出記憶系統（不再儲存你的對話/記憶）。"""
        cog = self.bot.get_cog("OpenAIChat")
        conf = cog.config.guild(ctx.guild)
        async with conf.memory_opt_out_user_ids() as ids:
            if ctx.author.id not in ids:
                ids.append(ctx.author.id)
        await ctx.send("已將你加入 opt-out：未來不會再儲存你的對話/長期記憶。要清除既有資料請用 `[p]openai forgetme`。")

    @openai.command(name="optin")
    @commands.guild_only()
    async def optin(self, ctx: commands.Context):
        """使用者重新加入記憶系統。"""
        cog = self.bot.get_cog("OpenAIChat")
        conf = cog.config.guild(ctx.guild)
        async with conf.memory_opt_out_user_ids() as ids:
            if ctx.author.id in ids:
                ids.remove(ctx.author.id)
        await ctx.send("已將你移出 opt-out：之後會依設定保存必要的短期對話/長期記憶。")

    @openai.command(name="forgetme")
    @commands.guild_only()
    async def forgetme(self, ctx: commands.Context):
        """刪除你在此伺服器的既有對話/長期記憶。"""
        cog = self.bot.get_cog("OpenAIChat")
        result = await cog.delete_user_data(guild_id=ctx.guild.id, user_id=ctx.author.id)
        await ctx.send(
            f"已刪除你的資料：chat {result.get('chat', 0)} 筆、user memory {result.get('user_memory', 0)} 筆。"
        )

    @openai.command(name="forgetuser")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def forgetuser(self, ctx: commands.Context, member: discord.Member):
        """管理員：刪除指定使用者在此伺服器的既有對話/長期記憶。"""
        cog = self.bot.get_cog("OpenAIChat")
        result = await cog.delete_user_data(guild_id=ctx.guild.id, user_id=member.id)
        await ctx.send(
            f"已刪除 {member.mention} 的資料：chat {result.get('chat', 0)} 筆、user memory {result.get('user_memory', 0)} 筆。"
        )

    @openai.command(name="listguildmemory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def listguildmemory(self, ctx: commands.Context, limit: int = 5):
        """管理員：列出伺服器層級長期記憶（最近 N 筆）。"""
        limit = max(1, min(limit, 20))
        cog = self.bot.get_cog("OpenAIChat")
        try:
            items = await cog._fetch_guild_long_term_memories(guild_id=ctx.guild.id, now=time.time(), limit=limit)
        except Exception as e:
            await ctx.send(f"讀取 guild memory 失敗：{e}")
            return

        if not items:
            await ctx.send("目前沒有 guild memory。")
            return

        lines = []
        for item in items:
            mem_id = item.get("memory_id", 0)
            summary = (item.get("summary") or "").strip()
            lines.append(f"- #{mem_id}: {summary[:120]}")
        await ctx.send("Guild memory（最近）：\n" + "\n".join(lines))

    @openai.command(name="delguildmemory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def delguildmemory(self, ctx: commands.Context, memory_id: int):
        """管理員：刪除一筆伺服器層級長期記憶（用 ID）。"""
        cog = self.bot.get_cog("OpenAIChat")
        try:
            removed = await cog._delete_guild_long_term_memory_by_id(guild_id=ctx.guild.id, memory_id=memory_id)
        except Exception as e:
            await ctx.send(f"刪除失敗：{e}")
            return
        if removed:
            await ctx.send(f"已刪除 guild memory #{memory_id}。")
        else:
            await ctx.send(f"找不到 guild memory #{memory_id}。")

    @openai.command(name="clearguildmemory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearguildmemory(self, ctx: commands.Context):
        """管理員：清空伺服器層級長期記憶（不影響 user memory / chat）。"""
        cog = self.bot.get_cog("OpenAIChat")
        try:
            removed = await cog._delete_guild_long_term_memories_for_guild(guild_id=ctx.guild.id)
        except Exception as e:
            await ctx.send(f"清除失敗：{e}")
            return
        await ctx.send(f"已清空 guild memory，共刪除 {removed} 筆。")

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
    async def chat_command(self, ctx: commands.Context, *, message: str):
        """發送訊息至 Gemini 並獲得回應。"""
        ctx.message.content = message
        cog = self.bot.get_cog("OpenAIChat")
        response = await cog.query_genai(ctx.message)
        if response:
            await ctx.send(response)
        else:
            await ctx.send("無法獲得回應。")

    @openai.command(name="clearhistory")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearhistory(self, ctx: commands.Context):
        """清除伺服器的聊天歷史與長期記憶。"""
        cog = self.bot.get_cog("OpenAIChat")
        result = await cog.clear_guild_data(guild_id=ctx.guild.id)
        await ctx.send(
            f"已清除伺服器資料：chat {result.get('chat', 0)} 筆、user memory {result.get('user_memory', 0)} 筆、guild memory {result.get('guild_memory', 0)} 筆。"
        )
