from typing import Optional, Tuple

import discord
from redbot.core import Config, commands

from .c_applicationreview import ApplicationReviewCommands
from .rules import can_reject, is_application_message, is_approved

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"
REJECT = "🚫"
APPROVED = "✅"
VOTES = (THUMBS_UP, THUMBS_DOWN)


class ApplicationReview(ApplicationReviewCommands, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=421765611811838116, force_registration=True
        )
        self.config.register_guild(channel_id=None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        channel_id = await self.config.guild(message.guild).channel_id()
        if message.channel.id != channel_id or not is_application_message(message.content):
            return
        for emoji in (THUMBS_UP, THUMBS_DOWN, REJECT):
            await message.add_reaction(emoji)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        emoji = str(payload.emoji)
        if emoji == REJECT:
            await self._reject(payload)
        elif emoji in VOTES:
            await self._sync_approval(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) in VOTES:
            await self._sync_approval(payload)

    async def _fetch_application(
        self, payload: discord.RawReactionActionEvent
    ) -> Optional[Tuple[discord.Guild, discord.TextChannel, discord.Message]]:
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
        return guild, channel, message

    async def _reject(self, payload: discord.RawReactionActionEvent):
        application = await self._fetch_application(payload)
        if application is None:
            return
        guild, channel, message = application
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
        guild, _, message = application
        counts = dict.fromkeys(VOTES, 0)
        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            if emoji in counts:
                # The bot seeds each vote emoji itself; its own reaction is not a vote.
                counts[emoji] = reaction.count - int(reaction.me)
        approved = is_approved(counts[THUMBS_UP], counts[THUMBS_DOWN])
        await self._set_approved(message, guild, approved)

    async def _set_approved(
        self, message: discord.Message, guild: discord.Guild, approved: bool
    ):
        marked = any(str(r.emoji) == APPROVED and r.me for r in message.reactions)
        if approved and not marked:
            await message.add_reaction(APPROVED)
        elif not approved and marked:
            await message.remove_reaction(APPROVED, guild.me)
