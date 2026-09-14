import discord
from redbot.core import Config, commands

from .c_applicationreview import ApplicationReviewCommands
from .rules import can_reject, is_application_message

THUMBS_UP = "👍"
REJECT = "🚫"


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
