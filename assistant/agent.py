from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import discord
import re
from redbot.core import commands


AGENT_GUILD_DEFAULTS = {
    "agent_mode_enabled": False,
    "agent_trigger_on_mention": True,
}

AGENT_MEMORY_SCOPE = "agent"
CHAT_MEMORY_SCOPE = "chat"

AGENT_MODE_PROMPT = (
    "12. 目前為 agent 模式。你應主動拆解任務、判斷是否需要查證、整合結果後再輸出最終答案。\n"
    "13. 你可以分多步使用工具，但每一步都要以完成任務為目標，不要無限重複相同查詢。\n"
    "14. 若你判定這一輪任務已完成，可在最後單獨一行輸出 END，系統會移除此標記但保留其餘回覆內容並正常發送給使用者。\n"
    "15. 若你判定這一輪不需要對使用者顯示任何訊息，可在最後單獨一行輸出 NO_REPLY，系統會視為隱藏結束，不發送任何訊息。\n"
    "16. 若有 safe_exec 工具可用，它只允許白名單 command/action；不可要求任意 shell、破壞性操作或超出白名單的指令。\n"
    "17. 在 agent 模式中，凡是使用者詢問目前日期、時間、時區、數學計算或隨機數，必須呼叫 safe_exec 取得結果，不可心算、憑模型知識或自行推測。\n"
)

AGENT_SEARCH_TOOL_NAME = "agent_search_web"
AGENT_SEARCH_MAX_CALLS = 25
CHAT_SEARCH_TOOL_NAME = "search_web"
CHAT_SEARCH_MAX_CALLS = 4
WEB_FETCH_TOOL_NAME = "web_fetch"
SAFE_EXEC_TOOL_NAME = "safe_exec"

_AGENT_CONTROL_MAP = {
    "END": "end",
    "[END]": "end",
    "<END>": "end",
    "<<END>>": "end",
    "NO_REPLY": "no_reply",
    "[NO_REPLY]": "no_reply",
    "<NO_REPLY>": "no_reply",
    "<<NO_REPLY>>": "no_reply",
}


@dataclass
class AgentChatRequest:
    message: discord.Message
    user_input: str
    agent_mode: bool = False


class AgentRuntimeMixin:
    @staticmethod
    def _strip_end_marker(response: str) -> Tuple[str, Optional[str]]:
        text = str(response or "").strip()
        if not text:
            return "", None

        lines = text.splitlines()
        if not lines:
            return text, None

        control = _AGENT_CONTROL_MAP.get(lines[-1].strip().upper())
        if control is None:
            return text, None

        cleaned = "\n".join(lines[:-1]).strip()
        return cleaned, control

    def _strip_bot_mention(self, content: str) -> str:
        if not content or self.bot.user is None:
            return str(content or "").strip()
        pattern = re.compile(rf"<@!?{self.bot.user.id}>")
        return pattern.sub("", content).strip()

    async def _is_agent_trigger(self, message: discord.Message, guild_config: Optional[Dict[str, Any]] = None) -> bool:
        if self.bot.user is None:
            return False

        mention_enabled = True
        if isinstance(guild_config, dict):
            mention_enabled = bool(guild_config.get("agent_trigger_on_mention", True))

        if mention_enabled and self.bot.user in message.mentions:
            return True

        reference = message.reference
        if reference is None or reference.message_id is None:
            return False

        resolved = reference.resolved
        if isinstance(resolved, discord.Message):
            return resolved.author.id == self.bot.user.id

        try:
            referenced = await message.channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
        return referenced.author.id == self.bot.user.id

    async def _build_agent_request(
        self,
        message: discord.Message,
        guild_config: Dict[str, Any],
    ) -> Optional[AgentChatRequest]:
        if not guild_config.get("agent_mode_enabled", False):
            return None

        if not await self._is_agent_trigger(message, guild_config):
            return None

        user_input = self._strip_bot_mention(message.content)
        if not user_input:
            return None

        return AgentChatRequest(message=message, user_input=user_input, agent_mode=True)

    @staticmethod
    def _format_interaction_input(
        *,
        user_name: str,
        user_id: int,
        user_input: str,
        agent_mode: bool,
    ) -> str:
        interaction_mode = "agent" if agent_mode else "chat"
        return (
            f"Interaction mode: {interaction_mode}\n"
            f"Discord User {user_name} (ID: <@{user_id}>) said:\n{user_input}"
        )

    @staticmethod
    def _memory_scope(agent_mode: bool) -> str:
        return AGENT_MEMORY_SCOPE if agent_mode else CHAT_MEMORY_SCOPE

    @staticmethod
    def _search_tool_name(agent_mode: bool) -> str:
        return AGENT_SEARCH_TOOL_NAME if agent_mode else CHAT_SEARCH_TOOL_NAME

    @staticmethod
    def _search_call_cap(agent_mode: bool) -> int:
        return AGENT_SEARCH_MAX_CALLS if agent_mode else CHAT_SEARCH_MAX_CALLS

    @staticmethod
    def _mode_prompt(agent_mode: bool) -> str:
        return AGENT_MODE_PROMPT if agent_mode else ""

    def _build_tools(self, *, agent_mode: bool, types_module, safe_exec_enabled: bool = False) -> List[Any]:
        search_tool_name = self._search_tool_name(agent_mode)
        search_description = (
            "Search the web for real-time information, then continue the task as an autonomous agent."
            if agent_mode
            else "Search the web for real-time information or current events."
        )
        fetch_description = (
            "Fetch a web page by URL, extract readable text content, and continue the task as an autonomous agent."
            if agent_mode
            else "Fetch a web page by URL and extract readable text content."
        )
        declarations = [
            types_module.FunctionDeclaration(
                name=search_tool_name,
                description=search_description,
                parameters=types_module.Schema(
                    type=types_module.Type.OBJECT,
                    properties={
                        "query": types_module.Schema(
                            type=types_module.Type.STRING,
                            description="The search query.",
                        )
                    },
                    required=["query"],
                ),
            ),
            types_module.FunctionDeclaration(
                name=WEB_FETCH_TOOL_NAME,
                description=fetch_description,
                parameters=types_module.Schema(
                    type=types_module.Type.OBJECT,
                    properties={
                        "url": types_module.Schema(
                            type=types_module.Type.STRING,
                            description="The absolute http/https URL to fetch.",
                        )
                    },
                    required=["url"],
                ),
            ),
        ]

        if safe_exec_enabled:
            declarations.append(
                types_module.FunctionDeclaration(
                    name=SAFE_EXEC_TOOL_NAME,
                    description=(
                        "Run a small whitelist of safe project inspection/check shell commands. "
                        "Pass either a whitelisted command string or an action. Arbitrary shell commands are not supported."
                    ),
                    parameters=types_module.Schema(
                        type=types_module.Type.OBJECT,
                        properties={
                            "command": types_module.Schema(
                                type=types_module.Type.STRING,
                                description=(
                                    "A shell-like command string. Allowed forms include: "
                                    "date; time; datetime; timezone; timezone AREA/LOCATION; "
                                    "math EXPRESSION; random; random MIN MAX."
                                ),
                            ),
                            "action": types_module.Schema(
                                type=types_module.Type.STRING,
                                description="Allowed values: date, time, datetime, timezone, math, random.",
                            ),
                            "path": types_module.Schema(
                                type=types_module.Type.STRING,
                                description="Optional relative path inside the project.",
                            ),
                            "expression": types_module.Schema(
                                type=types_module.Type.STRING,
                                description="Math expression for the math action.",
                            ),
                            "min": types_module.Schema(
                                type=types_module.Type.INTEGER,
                                description="Minimum integer for the random action.",
                            ),
                            "max": types_module.Schema(
                                type=types_module.Type.INTEGER,
                                description="Maximum integer for the random action.",
                            ),
                        },
                        required=["command"],
                    ),
                )
            )

        return [
            types_module.Tool(
                function_declarations=declarations
            )
        ]


async def send_agent_status(bot, ctx: commands.Context):
    conf = bot.get_cog("OpenAIChat").config.guild(ctx.guild)
    enabled = await conf.agent_mode_enabled()
    mention_enabled = await conf.agent_trigger_on_mention()
    status = "已啟用" if enabled else "未啟用"
    mention_status = "已啟用" if mention_enabled else "已停用"
    await ctx.send(
        "目前 guild 的 agent 模式狀態："
        f"{status}\n"
        f"- mention 觸發：{mention_status}\n"
        "- reply 觸發：已啟用\n"
        "啟用後，成員在此 guild 內可依設定用 mention 機器人，或回覆機器人的訊息來觸發 agent 互動。"
    )


async def enable_agent_mode(bot, ctx: commands.Context):
    conf = bot.get_cog("OpenAIChat").config.guild(ctx.guild)
    if await conf.agent_mode_enabled():
        await ctx.send("這個 guild 已經啟用 agent 模式。")
        return
    await conf.agent_mode_enabled.set(True)
    await ctx.send(
        "已啟用 agent 模式。之後在這個 guild 內 mention 機器人，或回覆機器人的訊息時，會觸發 agent 互動。"
    )


async def disable_agent_mode(bot, ctx: commands.Context):
    conf = bot.get_cog("OpenAIChat").config.guild(ctx.guild)
    if not await conf.agent_mode_enabled():
        await ctx.send("這個 guild 目前沒有啟用 agent 模式。")
        return
    await conf.agent_mode_enabled.set(False)
    await ctx.send("已停用這個 guild 的 agent 模式。")


async def list_agent_guilds(bot, ctx: commands.Context):
    cog = bot.get_cog("OpenAIChat")
    all_guilds = await cog.config.all_guilds()
    enabled_guild_ids = [
        guild_id
        for guild_id, settings in all_guilds.items()
        if isinstance(settings, dict) and settings.get("agent_mode_enabled", False)
    ]

    if not enabled_guild_ids:
        await ctx.send("目前沒有任何 guild 啟用 agent 模式。")
        return

    lines = []
    for guild_id in enabled_guild_ids:
        guild = bot.get_guild(int(guild_id))
        if guild:
            lines.append(f"- {guild.name} ({guild.id})")
        else:
            lines.append(f"- Unknown Guild ({guild_id})")

    await ctx.send("已啟用 agent 模式的 guild：\n" + "\n".join(lines))


def _parse_toggle(value: str) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "on", "yes", "y", "enable", "enabled"}:
        return True
    if text in {"0", "false", "off", "no", "n", "disable", "disabled"}:
        return False
    return None


async def send_agent_mention_status(bot, ctx: commands.Context):
    enabled = await bot.get_cog("OpenAIChat").config.guild(ctx.guild).agent_trigger_on_mention()
    status = "已啟用" if enabled else "已停用"
    await ctx.send(f"目前 guild 的 agent mention 觸發：{status}")


async def set_agent_mention_trigger(bot, ctx: commands.Context, value: str):
    parsed = _parse_toggle(value)
    if parsed is None:
        await ctx.send("請使用 on/off、true/false、enable/disable。")
        return

    conf = bot.get_cog("OpenAIChat").config.guild(ctx.guild)
    await conf.agent_trigger_on_mention.set(parsed)
    status = "已啟用" if parsed else "已停用"
    await ctx.send(f"已將 agent mention 觸發設為：{status}")
