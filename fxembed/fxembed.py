import re
import discord
from redbot.core import Config, commands


class FxEmbed(commands.Cog):
    """指定頻道內將 Twitter/X 狀態網址轉成 fxtwitter."""

    TWITTER_STATUS_URL = re.compile(
        r"https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)"
        r"/[A-Za-z0-9_]{1,15}/status(?:es)?/\d+"
        r"(?:[/?#][^\s<]*)?",
        re.IGNORECASE,
    )

    TWITTER_HOST = re.compile(
        r"^https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)",
        re.IGNORECASE,
    )

    TRAILING_PUNCTUATION = ".,!?;:)]}"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=1654894156,
            force_registration=True,
        )
        self.config.register_guild(channels=[])

    def replace_twitter_urls(self, content: str) -> str:
        def replace(match: re.Match) -> str:
            url = match.group(0)
            trailing = ""

            while url and url[-1] in self.TRAILING_PUNCTUATION:
                trailing = url[-1] + trailing
                url = url[:-1]

            return self.TWITTER_HOST.sub("https://fxtwitter.com", url) + trailing

        return self.TWITTER_STATUS_URL.sub(replace, content)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        channel_ids = set(await self.config.guild(message.guild).channels())
        channel_id = message.channel.id
        parent_id = getattr(getattr(message.channel, "parent", None), "id", None)

        if channel_id not in channel_ids and parent_id not in channel_ids:
            return

        converted = self.replace_twitter_urls(message.content)

        if converted == message.content:
            return

        await message.reply(
            converted,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        permissions = message.channel.permissions_for(message.guild.me)
        if permissions.manage_messages:
            try:
                await message.edit(suppress=True)
            except discord.HTTPException:
                pass

    @commands.group(name="fxembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def fxembed(self, ctx):
        """設定 fxtwitter 轉址頻道。"""

    @fxembed.command(name="add")
    async def fxembed_add(self, ctx, channel: discord.TextChannel = None):
        """加入指定頻道。"""
        channel = channel or ctx.channel

        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id in channels:
                await ctx.send("這個頻道已經在清單中。")
                return

            channels.append(channel.id)

        await ctx.tick()

    @fxembed.command(name="remove")
    async def fxembed_remove(self, ctx, channel: discord.TextChannel = None):
        """移除指定頻道。"""
        channel = channel or ctx.channel

        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id not in channels:
                await ctx.send("這個頻道不在清單中。")
                return

            channels.remove(channel.id)

        await ctx.tick()

    @fxembed.command(name="list")
    async def fxembed_list(self, ctx):
        """列出目前啟用頻道。"""
        channels = await self.config.guild(ctx.guild).channels()

        if not channels:
            await ctx.send("目前沒有指定頻道。")
            return

        names = []
        for channel_id in channels:
            channel = ctx.guild.get_channel(channel_id)
            names.append(channel.mention if channel else f"`{channel_id}`")

        await ctx.send("啟用頻道：" + ", ".join(names))

    @fxembed.command(name="clear")
    async def fxembed_clear(self, ctx):
        """清空啟用頻道。"""
        await self.config.guild(ctx.guild).channels.set([])
        await ctx.tick()
