import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

import discord
from discord.ext import tasks
from redbot.core import Config, commands

from .c_applicationreview import ApplicationReviewCommands
from .proposals import ProposalMixin
from .proposal_view import ProposalView
from .rules import (
    can_reject,
    human_reaction_count,
    is_application_message,
    is_approved,
)

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"
REJECT = "🚫"
APPROVED = "✅"
TIMER = "⏲️"
VOTES = (THUMBS_UP, THUMBS_DOWN)
log = logging.getLogger("red.badwolf.applicationreview")


class ApplicationReview(ApplicationReviewCommands, ProposalMixin, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=421765611811838116, force_registration=True
        )
        self.config.register_guild(
            channel_id=None, disqualified_role_id=None, applications={}
        )
        self._proposal_lock = asyncio.Lock()
        self.expire_applications.start()

    def cog_unload(self):
        self.expire_applications.cancel()
        view = getattr(self, "_proposal_view", None)
        if view is not None:
            view.stop()

    async def cog_load(self):
        self._proposal_view = ProposalView(self, confirm_enabled=True)
        self.bot.add_view(self._proposal_view)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        emoji = str(payload.emoji)
        if emoji == REJECT:
            await self._reject(payload)
        elif emoji == APPROVED:
            await self._finalize(payload)
        elif emoji in VOTES:
            await self._sync_approval(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) in VOTES:
            await self._sync_approval(payload)

    @tasks.loop(hours=1)
    async def expire_applications(self):
        await self._expire_due_applications(datetime.now(timezone.utc).timestamp())

    @expire_applications.before_loop
    async def before_expire_applications(self):
        await self.bot.wait_until_red_ready()

    async def _expire_due_applications(self, now: float):
        for guild_id, guild_data in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for message_id, record in list(
                guild_data.get("applications", {}).items()
            ):
                if record["expires_at"] <= now:
                    await self._expire_application(guild, message_id, record)

    async def _expire_application(self, guild, message_id: str, record: dict):
        channel = guild.get_channel(record["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await self.config.guild(guild).clear_raw("applications", message_id)
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.clear_reactions()
            await message.add_reaction(TIMER)
        except discord.NotFound:
            await self.config.guild(guild).clear_raw("applications", message_id)
            return
        except (discord.Forbidden, discord.HTTPException) as error:
            log.warning(
                "Could not expire application %s in guild %s; retrying next hour",
                message_id,
                guild.id,
                exc_info=error,
            )
            return
        await self.config.guild(guild).clear_raw("applications", message_id)

    async def _fetch_application(
        self, payload: discord.RawReactionActionEvent
    ) -> Optional[
        Tuple[discord.Guild, discord.TextChannel, discord.Message, Optional[dict]]
    ]:
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return None
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return None
        if payload.channel_id != await self.config.guild(guild).channel_id():
            return None
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return None
        if not is_application_message(message.content):
            return None
        record = await self._get_application_record(guild, message.id)
        if record is None or record.get("schema_version") is not None:
            return None
        return guild, channel, message, record

    async def _get_application_record(self, guild: discord.Guild, message_id: int):
        return await self.config.guild(guild).get_raw(
            "applications", str(message_id), default=None
        )

    def _vote_counts(self, message: discord.Message):
        counts = dict.fromkeys(VOTES, 0)
        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            if emoji in counts:
                counts[emoji] = human_reaction_count(reaction.count, reaction.me)
        return counts

    async def _reject(self, payload: discord.RawReactionActionEvent):
        application = await self._fetch_application(payload)
        if application is None:
            return
        guild, channel, message, _ = application
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        permissions = channel.permissions_for(member)
        if not can_reject(permissions.administrator, permissions.manage_channels):
            return
        await message.clear_reaction(THUMBS_UP)
        await self._set_approved(message, guild, False)

    async def _sync_approval(self, payload: discord.RawReactionActionEvent):
        application = await self._fetch_application(payload)
        if application is None:
            return
        guild, _, message, record = application
        if record is not None and record.get("finalized"):
            return
        counts = self._vote_counts(message)
        approved = is_approved(counts[THUMBS_UP], counts[THUMBS_DOWN])
        await self._set_approved(message, guild, approved)

    async def _finalize(self, payload: discord.RawReactionActionEvent):
        application = await self._fetch_application(payload)
        if application is None:
            return
        guild, channel, message, record = application
        if record is None or record.get("finalized"):
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        permissions = channel.permissions_for(member)
        if not can_reject(permissions.administrator, permissions.manage_channels):
            return
        counts = self._vote_counts(message)
        if not is_approved(counts[THUMBS_UP], counts[THUMBS_DOWN]):
            return
        for emoji in (THUMBS_UP, THUMBS_DOWN, REJECT):
            await message.clear_reaction(emoji)
        await self.config.guild(guild).set_raw(
            "applications", str(message.id), "finalized", value=True
        )

    async def _set_approved(
        self, message: discord.Message, guild: discord.Guild, approved: bool
    ):
        marked = any(str(r.emoji) == APPROVED and r.me for r in message.reactions)
        if approved and not marked:
            await message.add_reaction(APPROVED)
        elif not approved and marked:
            await message.remove_reaction(APPROVED, guild.me)
