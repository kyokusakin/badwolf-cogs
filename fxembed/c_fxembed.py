import re

import discord
from redbot.core import commands


MENTION_OR_ID = re.compile(r"^(?:<#([0-9]{15,20})>|([0-9]{15,20}))$")
SUPPORTED_CHANNEL_TYPES = tuple(
    getattr(discord, name) for name in ("TextChannel", "Thread", "ForumChannel") if hasattr(discord, name)
)


def is_supported_fxembed_channel(channel) -> bool:
    return isinstance(channel, SUPPORTED_CHANNEL_TYPES)


def iter_supported_channels(guild):
    for channel in guild.channels:
        if is_supported_fxembed_channel(channel):
            yield channel

    for thread in getattr(guild, "threads", []):
        if is_supported_fxembed_channel(thread):
            yield thread


def get_channel_or_thread(guild, channel_id: int):
    if hasattr(guild, "get_channel_or_thread"):
        return guild.get_channel_or_thread(channel_id)

    channel = guild.get_channel(channel_id)
    if channel is not None:
        return channel

    for thread in getattr(guild, "threads", []):
        if thread.id == channel_id:
            return thread

    return None


class FxEmbedChannelConverter(commands.Converter):
    async def convert(self, ctx, argument):
        match = MENTION_OR_ID.match(argument)

        if match:
            channel = get_channel_or_thread(ctx.guild, int(match.group(1) or match.group(2)))
            if is_supported_fxembed_channel(channel):
                return channel

        lowered = argument[1:].casefold() if argument.startswith("#") else argument.casefold()
        for channel in iter_supported_channels(ctx.guild):
            if channel.name.casefold() == lowered:
                return channel

        raise commands.BadArgument("找不到可用的文字頻道、公告頻道、討論串或論壇頻道。")


class FxEmbedCommands:
    @commands.group(name="fxembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def fxembed(self, ctx):
        """設定 fxtwitter 轉址頻道。"""

    @fxembed.command(name="add")
    async def fxembed_add(self, ctx, channel: FxEmbedChannelConverter = None):
        """加入指定頻道。"""
        channel = channel or ctx.channel
        if not is_supported_fxembed_channel(channel):
            await ctx.send("請指定文字頻道、公告頻道、討論串或論壇頻道。")
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id in channels:
                await ctx.send("這個頻道已經在清單中。")
                return

            channels.append(channel.id)
            self.cache_guild_channels(ctx.guild.id, channels)

        await ctx.tick()

    @fxembed.command(name="remove")
    async def fxembed_remove(self, ctx, channel: FxEmbedChannelConverter = None):
        """移除指定頻道。"""
        channel = channel or ctx.channel
        if not is_supported_fxembed_channel(channel):
            await ctx.send("請指定文字頻道、公告頻道、討論串或論壇頻道。")
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id not in channels:
                await ctx.send("這個頻道不在清單中。")
                return

            channels.remove(channel.id)
            self.cache_guild_channels(ctx.guild.id, channels)

        await ctx.tick()

    @fxembed.command(name="list")
    async def fxembed_list(self, ctx):
        """列出目前啟用頻道。"""
        channels = await self.config.guild(ctx.guild).channels()
        self.cache_guild_channels(ctx.guild.id, channels)

        if not channels:
            await ctx.send("目前沒有指定頻道。")
            return

        names = []
        for channel_id in channels:
            channel = get_channel_or_thread(ctx.guild, channel_id)
            names.append(channel.mention if channel else f"`{channel_id}`")

        await ctx.send("啟用頻道：" + ", ".join(names))

    @fxembed.command(name="clear")
    async def fxembed_clear(self, ctx):
        """清空啟用頻道。"""
        await self.config.guild(ctx.guild).channels.set([])
        self.cache_guild_channels(ctx.guild.id, [])
        await ctx.tick()
