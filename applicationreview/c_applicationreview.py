from typing import Literal

import discord
from redbot.core import commands


class ApplicationReviewCommands:
    @commands.hybrid_command(name="proposal")
    @commands.guild_only()
    async def proposal(
        self,
        ctx: commands.Context,
        item: str,
        reason: str,
        kind: Literal["普通", "重大"],
    ):
        """Submit a proposal in the configured channel."""
        await self._create_proposal(ctx, item, reason, kind)

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

    @applicationreview.command(name="disqualifiedrole")
    async def applicationreview_disqualifiedrole(
        self, ctx: commands.Context, role: discord.Role
    ):
        """Set the role whose members cannot propose or vote."""
        await self.config.guild(ctx.guild).disqualified_role_id.set(role.id)
        await ctx.send(f"已設定褫奪公權身分組為 {role.mention}")

    @applicationreview.command(name="invalidate")
    async def applicationreview_invalidate(
        self, ctx: commands.Context, message_id: int, member: discord.Member
    ):
        """Invalidate one proposal ballot without allowing a replacement."""
        await self._invalidate_vote(ctx, message_id, member)
