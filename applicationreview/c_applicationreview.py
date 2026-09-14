import discord
from redbot.core import commands


class ApplicationReviewCommands:
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
