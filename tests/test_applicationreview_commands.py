import importlib
import sys
import types
import unittest


def _identity_decorator(*args, **kwargs):
    def decorator(function):
        return function

    return decorator


def _group_decorator(*args, **kwargs):
    def decorator(function):
        function.command = _identity_decorator
        return function

    return decorator


discord = types.ModuleType("discord")
discord.TextChannel = object

commands = types.SimpleNamespace(
    Context=object,
    admin_or_permissions=_identity_decorator,
    group=_group_decorator,
    guild_only=_identity_decorator,
)
redbot = types.ModuleType("redbot")
redbot_core = types.ModuleType("redbot.core")
redbot_core.commands = commands

sys.modules.setdefault("discord", discord)
sys.modules.setdefault("redbot", redbot)
sys.modules.setdefault("redbot.core", redbot_core)

ApplicationReviewCommands = importlib.import_module(
    "applicationreview.c_applicationreview"
).ApplicationReviewCommands


class ChannelSetting:
    def __init__(self):
        self.value = None

    async def set(self, value):
        self.value = value


class GuildConfig:
    def __init__(self):
        self.channel_id = ChannelSetting()


class Config:
    def __init__(self, guild, guild_config):
        self.expected_guild = guild
        self.guild_config = guild_config

    def guild(self, guild):
        if guild is not self.expected_guild:
            raise AssertionError("command used wrong guild")
        return self.guild_config


class Context:
    def __init__(self, guild):
        self.guild = guild
        self.messages = []

    async def send(self, content):
        self.messages.append(content)


class ApplicationReviewCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = object()
        self.guild_config = GuildConfig()
        self.cog = ApplicationReviewCommands()
        self.cog.config = Config(self.guild, self.guild_config)
        self.ctx = Context(self.guild)

    async def test_channel_command_stores_selected_channel(self):
        channel = types.SimpleNamespace(id=42, mention="#applications")

        await self.cog.applicationreview_channel(self.ctx, channel)

        self.assertEqual(self.guild_config.channel_id.value, 42)
        self.assertEqual(self.ctx.messages, ["已設定申請頻道為 #applications"])

    async def test_disable_command_clears_selected_channel(self):
        self.guild_config.channel_id.value = 42

        await self.cog.applicationreview_disable(self.ctx)

        self.assertIsNone(self.guild_config.channel_id.value)
        self.assertEqual(self.ctx.messages, ["已停用申請頻道監聽"])


if __name__ == "__main__":
    unittest.main()
