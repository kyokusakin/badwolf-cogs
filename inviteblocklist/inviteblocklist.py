import re
from typing import Pattern, Union
import asyncio

import discord
from discord.ext.commands.converter import IDConverter
from discord.ext.commands.errors import BadArgument
from discord.utils import resolve_invite
from red_commons.logging import getLogger
from redbot.core import Config, VersionInfo, commands, version_info
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import humanize_list, pagify

log = getLogger("red.trusty-cogs.inviteblocklist")

_ = Translator("ExtendedModLog", __file__)

INVITE_RE: Pattern = re.compile(
    r"(?:https?\:\/\/)?discord(?:\.gg|(?:app)?\.com\/invite)\/[^/\W]+", re.I
)
# https://github.com/Rapptz/discord.py/blob/9806aeb83179d0d1e90d903e30db7e69e0d492e5/discord/utils.py#L887
# Slightly modified to ignore whitespace characters in the event multiple invite links
# are in the same message


class ChannelUserRole(IDConverter):
    """
    This will check to see if the provided argument is a channel, user, or role

    Guidance code on how to do this from:
    https://github.com/Rapptz/discord.py/blob/rewrite/discord/ext/commands/converter.py#L85
    https://github.com/Cog-Creators/Red-DiscordBot/blob/V3/develop/redbot/cogs/mod/mod.py#L24
    """

    async def convert(
        self, ctx: commands.Context, argument: str
    ) -> Union[discord.TextChannel, discord.Member, discord.Role]:
        guild = ctx.guild
        result = None
        id_match = self._get_id_match(argument)
        channel_match = re.match(r"<#([0-9]+)>$", argument)
        member_match = re.match(r"<@!?([0-9]+)>$", argument)
        role_match = re.match(r"<@&([0-9]+)>$", argument)
        for converter in ["channel", "role", "member"]:
            if converter == "channel":
                match = id_match or channel_match
                if match:
                    channel_id = match.group(1)
                    result = guild.get_channel(int(channel_id))
                else:
                    result = discord.utils.get(guild.text_channels, name=argument)
            if converter == "member":
                match = id_match or member_match
                if match:
                    member_id = match.group(1)
                    result = guild.get_member(int(member_id))
                else:
                    result = guild.get_member_named(argument)
            if converter == "role":
                match = id_match or role_match
                if match:
                    role_id = match.group(1)
                    result = guild.get_role(int(role_id))
                else:
                    result = discord.utils.get(guild._roles.values(), name=argument)
            if result:
                break
        if not result:
            msg = ("{arg} is not a valid channel, user or role.").format(arg=argument)
            raise BadArgument(msg)
        return result


class InviteBlocklist(commands.Cog):
    __author__ = ["TrustyJAID"]
    __version__ = "1.1.6"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=218773382617890828)
        self.config.register_guild(
            blacklist=[],
            whitelist=[],
            all_invites=False,
            staff_role=None,
            immunity_list=[],
        )
        self.warnsystem = None
        self.warnsystem_available = False

    async def initialize(self):
        for _ in range(5):
            warnsystem = self.bot.get_cog('WarnSystem')
            if warnsystem is not None:
                self.warnsystem = warnsystem.api
                self.warnsystem_available = True
                return True
            await asyncio.sleep(1)
        log.warning("WarnSystem cog is not available. Some functionalities will be disabled.")
        return False

    async def red_delete_data_for_user(self, **kwargs):
        """
        Nothing to delete
        """
        return

    async def check_immunity_list(self, message: discord.Message) -> bool:
        is_immune = False
        if not message.guild:
            return True
        if await self.bot.is_owner(message.author):
            return True
        global_perms = await self.bot.allowed_by_whitelist_blacklist(message.author)
        if not global_perms:
            return global_perms
        immunity_list = await self.config.guild(message.guild).immunity_list()
        channel = message.channel
        if immunity_list:
            if channel.id in immunity_list:
                is_immune = True
            if getattr(channel, "category_id", None) in immunity_list:
                is_immune = True
            if message.author.id in immunity_list:
                is_immune = True
            for role in getattr(message.author, "roles", []):
                if role.is_default():
                    continue
                if role.id in immunity_list:
                    is_immune = True
        return is_immune

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        await self._handle_message_search(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """
        Handle messages edited with links
        """
        if not payload.guild_id:
            return
        if payload.cached_message:
            guild = payload.cached_message.guild
        else:
            guild = self.bot.get_guild(int(payload.guild_id))
        if guild is None:
            return
        chan = guild.get_channel(payload.channel_id)
        if chan is None:
            return
        if version_info >= VersionInfo.from_str("3.4.0"):
            if await self.bot.cog_disabled_in_guild(self, guild):
                return
        guild_settings = await self.config.guild(guild).all()
        if (
            guild_settings["blacklist"]
            or guild_settings["whitelist"]
            or guild_settings["all_invites"]
        ):
            if payload.cached_message is not None:
                await self._handle_message_search(payload.cached_message)
            else:
                if "edited_timestamp" not in payload.data:
                    # This should only be happening on links posted by users
                    return
                msg = discord.Message(state=chan._state, channel=chan, data=payload.data)
                # Construct a message object when discord.py does not.
                await self._handle_message_search(msg)

    async def _handle_message_search(self, message: discord.Message):
        if await self.bot.is_automod_immune(message.author):
            return
        if version_info >= VersionInfo.from_str("3.4.0"):
            if await self.bot.cog_disabled_in_guild(self, message.guild):
                return
        if await self.check_immunity_list(message) is True:
            log.debug("%r is immune from invite blocklist", message)
            return
        find = INVITE_RE.findall(message.clean_content)
        guild = message.guild
        if guild is None or not find:
            return
        staff_role_id = await self.config.guild(guild).staff_role()
        if staff_role_id:
            staff_role_mention = f"<@&{staff_role_id}>"
        else:
            staff_role_mention = None

        await self._process_invites(guild, message, find, staff_role_mention)

    async def _process_invites(self, guild, message, invites, staff_role_mention):
        error_message = (
            "There was an error fetching a potential invite link. "
            f"The server ID could not be obtained so message ID {repr(message)} "
            "may not have been properly deleted."
        )
        if invites and await self.config.guild(guild).all_invites():
            await self._handle_unauthorized_invite(guild, message, staff_role_mention)
            return
        if whitelist := await self.config.guild(guild).whitelist():
            for i in invites:
                inv = resolve_invite(i)
                try:
                    invite = await self.bot.fetch_invite(inv.code)
                except discord.errors.NotFound:
                    log.error(error_message)
                    continue
                except Exception:
                    log.exception(error_message)
                    continue
                if invite.guild.id == guild.id:
                    continue
                if invite.guild.id not in whitelist:
                    await self._handle_unauthorized_invite(guild, message, staff_role_mention)
                    return
            return
        if blacklist := await self.config.guild(guild).blacklist():
            for i in invites:
                inv = resolve_invite(i)
                try:
                    invite = await self.bot.fetch_invite(inv.code)
                except discord.errors.NotFound:
                    log.error(error_message)
                    continue
                except Exception:
                    log.exception(error_message)
                    continue
                if invite.guild.id == guild.id:
                    continue
                if invite.guild.id in blacklist:
                    await self._handle_unauthorized_invite(guild, message, staff_role_mention)
                    return
            return

    async def _handle_unauthorized_invite(self, guild, message, staff_role_mention):
        try:
            embed = discord.Embed(
                title="邀請鏈接已被刪除",
                description=f"{message.author.mention}，您發送的邀請鏈接已被刪除\n如果你已被允許請聯繫管理員\n",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            if staff_role_mention is not None:
                await message.channel.send(f"{staff_role_mention}", allowed_mentions=discord.AllowedMentions(roles=True))
            await message.delete()
            if self.warnsystem_available:
                await self.warnsystem.warn(guild, [message.author], guild.me, 1, reason="未授權的Discord邀請連結")
        except discord.errors.Forbidden:
            log.error("I tried to delete an invite link posted in %s but lacked the permission to do so", guild.name)

    @commands.group(name="inviteblock", aliases=["ibl", "inviteblocklist"])
    @commands.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def invite_block(self, ctx: commands.Context):
        """
        Settings for managing invite link blocking
        """
        pass

    @invite_block.group(name="blocklist", aliases=["blacklist", "bl", "block"])
    @commands.guild_only()
    async def invite_blocklist(self, ctx: commands.Context):
        """
        Commands for setting the blocklist
        """
        pass

    @invite_block.group(name="allowlist", aliases=["whitelist", "wl", "al", "allow"])
    @commands.guild_only()
    async def invite_allowlist(self, ctx: commands.Context):
        """
        Commands for setting the blocklist
        """
        pass

    @invite_block.group(name="immunity", aliases=["immune"])
    @commands.guild_only()
    async def invite_immunity(self, ctx: commands.Context):
        """
        Commands for fine tuning allowed channels, users, or roles
        """
        pass
    
    @invite_block.group(name="staffrole")
    async def staffrole(self, ctx: commands.Context):
        """
        Commands for tag
        """
        pass
    ##########################################################################################
    #                                    Blocklist Settings                                  #
    ##########################################################################################

    @invite_block.command()
    @commands.mod_or_permissions(manage_messages=True)
    async def blockall(self, ctx: commands.Context, set_to: bool):
        """
        Automatically remove all invites regardless of their destination
        """
        await self.config.guild(ctx.guild).all_invites.set(set_to)
        if set_to:
            await ctx.send(_("Okay, I will delete all invite links posted."))
        else:
            await ctx.send(
                _(
                    "Okay I will only delete invites if the server "
                    "destination is in my blocklist or allowlist."
                )
            )

    @invite_blocklist.command(name="add")
    async def add_to_blocklist(
        self,
        ctx: commands.Context,
        *invite_or_guild_id: Union[discord.Invite, discord.Guild, int],
    ):
        """
        Add a guild ID to the blocklist, providing an invite link will also work

        `[invite_or_guild_id]` The guild ID or invite to the guild you want to have
        invite links blocked from.
        """
        guilds_blocked = []
        async with self.config.guild(ctx.guild).blacklist() as blacklist:
            for i in invite_or_guild_id:
                if isinstance(i, int):
                    if i not in blacklist:
                        blacklist.append(i)
                        guilds_blocked.append(str(i))
                elif isinstance(i, discord.Invite):
                    if i.guild and i.guild.id not in blacklist:
                        guilds_blocked.append(f"{i.guild.name} - {i.guild.id}")
                        blacklist.append(i.guild.id)
                elif isinstance(i, discord.Guild):
                    if i.id not in blacklist:
                        guilds_blocked.append(f"{i.name} - {i.id}")
                        blacklist.append(i.id)
        if guilds_blocked:
            await ctx.send(
                _("Now blocking invites from {guild}.").format(guild=humanize_list(guilds_blocked))
            )
        else:
            await ctx.send(_("None of the provided invite links or guild ID's are new."))

    @invite_blocklist.command(name="remove", aliases=["del", "rem"])
    async def remove_from_blocklist(
        self,
        ctx: commands.Context,
        *thing_to_block: Union[discord.Invite, discord.Guild, int],
    ):
        """
        Add a guild ID to the blocklist, providing an invite link will also work

        `[invite_or_guild_id]` The guild ID or invite to the guild you not longer want to have
        invite links blocked from.
        """
        guilds_blocked = []
        async with self.config.guild(ctx.guild).blacklist() as blacklist:
            for i in thing_to_block:
                if isinstance(i, int):
                    if i in blacklist:
                        blacklist.remove(i)
                        guilds_blocked.append(str(i))
                elif isinstance(i, discord.Invite):
                    if i.guild and i.guild.id in blacklist:
                        guilds_blocked.append(f"{i.guild.name} - {i.guild.id}")
                        blacklist.remove(i.guild.id)
                elif isinstance(i, discord.Guild):
                    if i.id in blacklist:
                        guilds_blocked.append(f"{i.name} - {i.id}")
                        blacklist.remove(i.id)
        if guilds_blocked:
            await ctx.send(
                _("Removed {guild} from blocklist.").format(guild=humanize_list(guilds_blocked))
            )
        else:
            await ctx.send(_("None of the provided invite links or guild ID's are being blocked."))

    @invite_blocklist.command(name="info")
    async def blocklist_info(self, ctx: commands.Context):
        """
        Show what guild ID's are in the invite link blocklist
        """
        blacklist = await self.config.guild(ctx.guild).blacklist()
        msg = _("__Guild ID's Blocked__:\n{guilds}").format(
            guilds="\n".join(str(g) for g in blacklist)
        )
        block_list = await self.config.guild(ctx.guild).channel_user_role_allow()
        if block_list:
            msg += _("__Blocked Channels, Users, and Roles:__\n{chan_user_roel}").format(
                chan_user_role="\n".join(
                    await ChannelUserRole().convert(ctx, str(obj_id)) for obj_id in block_list
                )
            )
        for page in pagify(msg):
            await ctx.maybe_send_embed(page)

    ##########################################################################################
    #                                    Alowlist Settings                                   #
    ##########################################################################################

    @invite_allowlist.command(name="add")
    async def add_to_allowlist(
        self,
        ctx: commands.Context,
        *invite_or_guild_id: Union[discord.Invite, discord.Guild, int],
    ):
        """
        Add a guild ID to the allowlist, providing an invite link will also work

        `[invite_or_guild_id]` The guild ID or invite to the guild you want to have
        invites allowed from.
        """
        guilds_blocked = []
        async with self.config.guild(ctx.guild).whitelist() as whitelist:
            for i in invite_or_guild_id:
                if isinstance(i, int):
                    if i not in whitelist:
                        whitelist.append(i)
                        guilds_blocked.append(str(i))
                elif isinstance(i, discord.Invite):
                    if i.guild and i.guild.id not in whitelist:
                        guilds_blocked.append(f"{i.guild.name} - {i.guild.id}")
                        whitelist.append(i.guild.id)
                elif isinstance(i, discord.Guild):
                    if i.id not in whitelist:
                        guilds_blocked.append(f"{i.name} - {i.id}")
                        whitelist.append(i.id)
        if guilds_blocked:
            await ctx.send(
                _("Now Allowing invites from {guild}.").format(guild=humanize_list(guilds_blocked))
            )
        else:
            await ctx.send(_("None of the provided invite links or ID's are new."))

    @invite_allowlist.command(name="remove", aliases=["del", "rem"])
    async def remove_from_allowlist(
        self,
        ctx: commands.Context,
        *invite_or_guild_id: Union[discord.Invite, discord.Guild, int],
    ):
        """
        Add a guild ID to the allowlist, providing an invite link will also work

        `[invite_or_guild_id]` The guild ID or invite to the guild you not longer want to have
        invites allowed from.
        """
        guilds_blocked = []
        async with self.config.guild(ctx.guild).whitelist() as whitelist:
            for i in invite_or_guild_id:
                if isinstance(i, int):
                    if i in whitelist:
                        whitelist.remove(i)
                        guilds_blocked.append(str(i))
                elif isinstance(i, discord.Invite):
                    if i.guild and i.guild.id in whitelist:
                        guilds_blocked.append(f"{i.guild.name} - {i.guild.id}")
                        whitelist.remove(i.guild.id)
                elif isinstance(i, discord.Guild):
                    if i.id in whitelist:
                        guilds_blocked.append(f"{i.name} - {i.id}")
                        whitelist.remove(i.id)
        if guilds_blocked:
            await ctx.send(
                _("Removed {guild} from allowlist.").format(guild=humanize_list(guilds_blocked))
            )
        else:
            await ctx.send(
                _("None of the provided invite links or guild ID's are currently allowed.")
            )

    @invite_allowlist.command(name="info")
    async def allowlist_info(self, ctx: commands.Context):
        """
        Show what guild ID's are in the invite link allowlist
        """
        whitelist = await self.config.guild(ctx.guild).whitelist()
        msg = _("__Guild ID's Allowed__:\n{guilds}").format(
            guilds="\n".join(str(g) for g in whitelist)
        )
        allow_list = await self.config.guild(ctx.guild).channel_user_role_allow()
        if allow_list:
            msg += _("__Allowed Channels, Users, and Roles:__\n{chan_user_roel}").format(
                chan_user_role="\n".join(
                    await ChannelUserRole().convert(ctx, str(obj_id)) for obj_id in allow_list
                )
            )
        for page in pagify(msg):
            await ctx.maybe_send_embed(page)

    ##########################################################################################
    #                                  Immunity Settings                                     #
    ##########################################################################################

    @invite_immunity.command(name="add")
    async def add_to_invite_immunity(
        self, ctx: commands.Context, *channel_user_role: ChannelUserRole
    ):
        """
        Add a channel, user, or role to the immunity list.
        Any invite links posted in these channels, by users with this role, or users added
        to this list will not have messages with invite links deleted.

        `[channel_user_role...]` is the channel, user or role to make immune.
        (You can supply more than one of any at a time)
        """
        if len(channel_user_role) < 1:
            return await ctx.send(
                _("You must supply 1 or more channels users or roles to be allowed.")
            )
        async with self.config.guild(ctx.guild).immunity_list() as whitelist:
            for obj in channel_user_role:
                if obj.id not in whitelist:
                    whitelist.append(obj.id)
        msg = _("`{list_type}` added to the whitelist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @invite_immunity.command(name="remove", aliases=["del", "rem"])
    async def remove_from_invite_immunity(
        self, ctx: commands.Context, *channel_user_role: ChannelUserRole
    ):
        """
        remove a channel, user, or role from the immunity list.
        Any invite links posted in these channels, by users with this role, or users added
        to immunity will not have messages with invite links deleted.

        `[channel_user_role...]` is the channel, user or role to remove from the immunity list
        (You can supply more than one of any at a time)
        """
        if len(channel_user_role) < 1:
            return await ctx.send(
                _("You must supply 1 or more channels users or roles to be whitelisted.")
            )
        async with self.config.guild(ctx.guild).immunity_list() as whitelist:
            for obj in channel_user_role:
                if obj.id in whitelist:
                    whitelist.remove(obj.id)
        msg = _("`{list_type}` removed from the whitelist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @invite_immunity.command(name="info")
    async def allowlist_context_info(self, ctx: commands.Context):
        """
        Show what channels, users, and roles are immune to inviteblocklist
        """
        msg = _("Invite immunity list for {guild}:\n").format(guild=ctx.guild.name)
        whitelist = await self.config.guild(ctx.guild).immunity_list()
        can_embed = ctx.channel.permissions_for(ctx.me).embed_links
        for obj_id in whitelist:
            obj = await ChannelUserRole().convert(ctx, str(obj_id))
            if isinstance(obj, discord.TextChannel):
                msg += f"{obj.mention}\n"
                continue
            if can_embed:
                msg += f"{obj.mention}\n"
                continue
            else:
                msg += f"{obj.name}\n"
        for page in pagify(msg):
            await ctx.maybe_send_embed(page)
            
    ##########################################################################################
    #                                  Staff Settings                                        #
    ##########################################################################################
    
    @staffrole.command(name="add")
    async def set_staffrole(self, ctx, role_or_user: Union[discord.Role, discord.Member]):
        """Set the staff role to mention when an invite link is deleted"""
        await self.config.guild(ctx.guild).staff_role.set(role_or_user.id)
        await ctx.send(f"Staff role/user set to {role_or_user.mention}")

    @staffrole.command(name="remove", aliases=["del", "rem"])
    async def remove_staffrole(self, ctx):
        """Remove the staff role to mention when an invite link is deleted"""
        await self.config.guild(ctx.guild).staff_role.set(None)
        await ctx.send("Staff role for invite links has been removed.")
