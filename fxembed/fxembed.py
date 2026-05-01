import discord
from redbot.core import Config, commands

from .c_fxembed import FxEmbedCommands
from .url_converter import DISCORD_MESSAGE_LIMIT, build_reply_content, has_twitter_status_url, replace_twitter_urls


class FxEmbed(FxEmbedCommands, commands.Cog):
    """指定頻道內將 Twitter/X 狀態網址轉成 fxtwitter."""

    def __init__(self, bot):
        self.bot = bot
        self._enabled_channel_ids = {}
        self.config = Config.get_conf(
            self,
            identifier=1654894156,
            force_registration=True,
        )
        self.config.register_guild(channels=[])

    async def get_enabled_channel_ids(self, guild: discord.Guild):
        guild_id = guild.id
        if guild_id not in self._enabled_channel_ids:
            channels = await self.config.guild(guild).channels()
            self.cache_guild_channels(guild_id, channels)

        return self._enabled_channel_ids[guild_id]

    def cache_guild_channels(self, guild_id: int, channel_ids):
        self._enabled_channel_ids[guild_id] = set(channel_ids)

    def is_enabled_message_channel(self, channel_ids, channel) -> bool:
        channel_id = getattr(channel, "id", None)
        parent_id = getattr(getattr(channel, "parent", None), "id", None)
        return channel_id in channel_ids or parent_id in channel_ids

    def can_delete_original_message(self, message: discord.Message) -> bool:
        me = message.guild.me
        permissions_for = getattr(message.channel, "permissions_for", None)
        return me is not None and permissions_for is not None and permissions_for(me).manage_messages

    def add_author_attribution(self, content: str, message: discord.Message) -> str:
        attribution = f"\n\n原發送人：{message.author.mention}"
        if len(content) + len(attribution) <= DISCORD_MESSAGE_LIMIT:
            return content + attribution

        return content

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        if not has_twitter_status_url(message.content):
            return

        channel_ids = await self.get_enabled_channel_ids(message.guild)
        if not self.is_enabled_message_channel(channel_ids, message.channel):
            return

        if not self.can_delete_original_message(message):
            return

        converted = replace_twitter_urls(message.content)

        if converted == message.content:
            return

        reply_content = build_reply_content(message.content, converted)
        if not reply_content:
            return
        reply_content = self.add_author_attribution(reply_content, message)

        try:
            sent_message = await message.channel.send(
                reply_content,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            return

        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            try:
                await sent_message.delete()
            except discord.HTTPException:
                pass
