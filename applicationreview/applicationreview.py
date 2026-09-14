import discord
from redbot.core import Config, commands

from .rules import can_reject, is_application_message

THUMBS_UP = "👍"
REJECT = "🚫"


class ApplicationReview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=421765611811838116, force_registration=True
        )
        self.config.register_guild(channel_id=None)

    @commands.group(name="applicationreview")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def applicationreview(self, ctx: commands.Context):
        """Configure application review reactions."""

    @applicationreview.command(name="channel")
    async def applicationreview_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the application channel."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"已設定申請頻道為 {channel.mention}")

    @applicationreview.command(name="disable")
    async def applicationreview_disable(self, ctx: commands.Context):
        """Disable application review reactions."""
        await self.config.guild(ctx.guild).channel_id.set(None)
        await ctx.send("已停用申請頻道監聽")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        channel_id = await self.config.guild(message.guild).channel_id()
        if message.channel.id != channel_id or not is_application_message(message.content):
            return
        await message.add_reaction(THUMBS_UP)
        await message.add_reaction(REJECT)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or str(payload.emoji) != REJECT:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return
        channel_id = await self.config.guild(guild).channel_id()
        if payload.channel_id != channel_id:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        permissions = channel.permissions_for(member)
        if not can_reject(permissions.administrator, permissions.manage_channels):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        if not is_application_message(message.content):
            return
        await message.clear_reaction(THUMBS_UP)
