import discord
from redbot.core import Config, commands

from .c_fxembed import FxEmbedCommands
from .url_converter import build_reply_content, has_twitter_status_url, replace_twitter_urls


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

    def build_author_embed(self, message: discord.Message) -> discord.Embed:
        author = message.author
        color = getattr(author, "color", discord.Color.blurple())
        if color == discord.Color.default():
            color = discord.Color.blurple()

        embed = discord.Embed(color=color, timestamp=message.created_at)
        display_name = getattr(author, "display_name", str(author))
        username = str(author)
        author_name = f"原發送人：{display_name} ({username})" if display_name != username else f"原發送人：{username}"
        author_url = f"https://discord.com/users/{author.id}"
        avatar = getattr(author, "display_avatar", None)
        icon_url = getattr(avatar, "url", None)

        if icon_url:
            embed.set_author(name=author_name[:256], url=author_url, icon_url=icon_url)
        else:
            embed.set_author(name=author_name[:256], url=author_url)

        embed.set_footer(text=f"User ID: {author.id}")
        return embed

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

        try:
            sent_message = await message.channel.send(
                reply_content,
                embed=self.build_author_embed(message),
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

