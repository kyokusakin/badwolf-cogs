import discord
import logging
import asyncio

from io import BytesIO
from typing import Optional, TYPE_CHECKING, List, Dict, Tuple
from asyncio import TimeoutError as AsyncTimeoutError
from abc import ABC
from datetime import datetime, timedelta

from redbot.core import commands, Config, checks
from redbot.core.commands.converter import TimedeltaConverter
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils import predicates, menus, mod
from redbot.core.utils.chat_formatting import pagify, text_to_file

from warnsystem.components import WarningsSelector

from . import errors
from .api import API, UnavailableMember
from .automod import AutomodMixin
from .cache import MemoryCache
from .converters import AdvancedMemberSelect
from .settings import SettingsMixin

if TYPE_CHECKING:
    from redbot.core.bot import Red

log = logging.getLogger('red.laggron.warnsystem')
_ = Translator('WarnSystem', __file__)

EMBED_MODLOG = lambda x: _('A member got a level {} warning.').format(x)
EMBED_USER = lambda x: _('The moderation team set you a level {} warning.').format(x)

class CompositeMetaClass(type(commands.Cog), type(ABC)):
    '''Coexist discord.py metaclass'''
    pass

@cog_i18n(_)
class WarnSystem(SettingsMixin, AutomodMixin, commands.Cog, metaclass=CompositeMetaClass):
    '''WarnSystem Cog with real-time admin-only voting, thresholds by level, and mod bypass.'''
    __version__ = '1.5.10'
    __author__ = ['retke (El Laggron)']

    default_global = {'data_version': '0.0'}
    default_guild = {
        'delete_message': False,
        'show_mod': False,
        'mute_role': None,
        'update_mute': False,
        'remove_roles': False,
        'respect_hierarchy': False,
        'reinvite': True,
        'log_manual': False,
        'channels': {'main': None, '1': None, '2': None, '3': None, '4': None, '5': None},
        'bandays': {'softban': 7, 'ban': 0},
        'embed_description_modlog': {str(i): EMBED_MODLOG(i) for i in range(1, 6)},
        'embed_description_user': {str(i): EMBED_USER(i) for i in range(1, 6)},
        'substitutions': {},
        'thumbnails': {str(i): url for i, url in zip(range(1, 6), [
            'https://i.imgur.com/Bl62rGd.png', 'https://i.imgur.com/cVtzp1M.png',
            'https://i.imgur.com/uhrYzyt.png', 'https://i.imgur.com/uhrYzyt.png',
            'https://i.imgur.com/DfBvmic.png'
        ])},
        'colors': {str(i): color for i, color in zip(range(1, 6), [
            0xF4AA42, 0xD1ED35, 0xED9735, 0xED6F35, 0xFF4C4C
        ])},
        'url': None,
        'temporary_warns': {},
        'automod': {
            'enabled': False,
            'antispam': {'enabled': False, 'max_messages': 5, 'delay': 2, 'delay_before_action': 60,
                         'warn': {'level': 1, 'reason': 'Sending messages too fast!', 'time': None}, 'whitelist': []},
            'regex_edited_messages': False,
            'regex': {},
            'warnings': []
        },
        'vote_channel': None,
        'result_channel': None,
        'forbidden_roles': [],
    }
    default_custom_member = {'x': []}

    def __init__(self, bot: 'Red'):
        self.bot = bot
        self.data = Config.get_conf(self, 260, force_registration=True)
        self.data.register_global(**self.default_global)
        self.data.register_guild(**self.default_guild)
        try:
            self.data.init_custom('MODLOGS', 2)
        except AttributeError:
            pass
        self.data.register_custom('MODLOGS', **self.default_custom_member)
        self.cache = MemoryCache(self.bot, self.data)
        self.api = API(self.bot, self.data, self.cache)
        self.active_votes: Dict[int, Dict] = {}

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.message_id in self.active_votes:
            await self._update_vote_embed(payload.guild_id, payload.channel_id, payload.message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.message_id in self.active_votes:
            await self._update_vote_embed(payload.guild_id, payload.channel_id, payload.message_id)

    async def _get_admins(self, guild: discord.Guild) -> List[discord.Member]:
        # 使用 Redbot 內建函式取得 Admin 角色
        admin_roles = await self.bot.get_admin_roles(guild)
        admin_ids = {r.id for r in admin_roles}
        return [m for m in guild.members if any(r.id in admin_ids for r in m.roles)]

    def _get_status_label(self, status: discord.Status) -> str:
        return {
            discord.Status.online: '未投票',
            discord.Status.idle: '未投票',
            discord.Status.dnd: '未投票',
            discord.Status.offline: '離席'
        }.get(status, '離席')

    async def _threshold_passed(self, level: int, approves: int, total_online: int) -> bool:
        if level in (3, 4):
            return total_online > 0 and approves / total_online >= 0.5
        if level == 5:
            return total_online > 0 and approves / total_online >= 0.75
        return False

    async def _collect_votes(self, vote_msg: discord.Message) -> Tuple[List[str], List[str]]:
        approves, rejects = [], []
        for react in vote_msg.reactions:
            if str(react.emoji) in ('✅', '❌'):
                async for user in react.users():
                    if user.bot:
                        continue
                    name = user.display_name
                    if str(react.emoji) == '✅' and name not in approves:
                        approves.append(name)
                    elif str(react.emoji) == '❌' and name not in rejects:
                        rejects.append(name)
        return approves, rejects

    async def _update_vote_embed(self, guild_id: int, channel_id: int, msg_id: int):
        info = self.active_votes.get(msg_id)
        if not info or datetime.utcnow() >= info['end_time']:
            return

        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id)
        vote_msg = await channel.fetch_message(msg_id)

        admins = await self._get_admins(guild)
        approves, rejects = await self._collect_votes(vote_msg)

        mod_roles = await self.bot.get_mod_roles(guild)
        mod_ids = {r.id for r in mod_roles}

        mods = [m for m in admins if any(r.id in mod_ids for r in m.roles)]
        pure_admins = [m for m in admins if m not in mods]

        lines = []

        # 顯示 Mod 分區
        if mods:
            lines.append("==MOD==")
            for m in sorted(mods, key=lambda m: m.display_name.lower()):
                if m.display_name in approves:
                    mark = '同意'
                elif m.display_name in rejects:
                    mark = '反對'
                else:
                    mark = self._get_status_label(m.status)
                lines.append(f"{m.display_name} {mark}")

        # 顯示 Admin 分區
        if pure_admins:
            lines.append("==管理員==")
            for m in sorted(pure_admins, key=lambda m: m.display_name.lower()):
                if m.display_name in approves:
                    mark = '同意'
                elif m.display_name in rejects:
                    mark = '反對'
                else:
                    mark = self._get_status_label(m.status)
                lines.append(f"{m.display_name} {mark}")

        total_online = sum(1 for m in admins if m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd))

        embed = discord.Embed(
            title='警告投票',
            description=f"{info['initiator'].mention} 發起對 {info['target'].mention} 的 {info['level']} 級警告投票",
            color=discord.Color.orange()
        )
        if info.get('reason'):
            embed.add_field(name='原因', value=info['reason'], inline=False)
        embed.add_field(name='投票進度', value='```\n' + '\n'.join(lines) + '\n```', inline=False)
        embed.set_footer(text='請於 24 小時內投票，離線者不計入。')
        await vote_msg.edit(embed=embed)

        # 如果有 mod 投票通過則直接結束
        for name in approves:
            member = discord.utils.get(guild.members, display_name=name)
            if member and any(r.id in mod_ids for r in member.roles):
                await self._end_vote(msg_id)
                return

        if await self._threshold_passed(info['level'], len(approves), total_online):
            await self._end_vote(msg_id)


    async def _end_vote(self, msg_id: int):
        info = self.active_votes.pop(msg_id, None)
        if not info:
            return
        guild = info['channel'].guild
        vote_channel = info['channel']
        result_ch_id = await self.data.guild(guild).result_channel()
        result_channel = guild.get_channel(result_ch_id) if result_ch_id else None

        vote_msg = await vote_channel.fetch_message(msg_id)
        approves, rejects = await self._collect_votes(vote_msg)

        mod_roles = await self.bot.get_mod_roles(guild)
        mod_ids = {r.id for r in mod_roles}
        is_mod = any(r.id in mod_ids for r in info['initiator'].roles)
        total_online = sum(1 for m in await self._get_admins(guild) if m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd))
        passed = is_mod or await self._threshold_passed(info['level'], len(approves), total_online)

        record = [f"{n} 同意" for n in approves] + [f"{n} 反對" for n in rejects] + [
            f"{m.display_name}: {self._get_status_label(m.status)}" for m in await self._get_admins(guild)
            if m.display_name not in approves + rejects
        ]
        embed = discord.Embed(
            title='投票結束',
            description=f"{info['initiator'].mention} 發起對 {info['target'].mention} 的 {info['level']} 級警告投票",
            color=discord.Color.greyple()
        )
        if info.get('reason'):
            embed.add_field(name='原因', value=info['reason'], inline=False)
        embed.add_field(name='最終投票記錄', value='```\n' + '\n'.join(record) + '\n```', inline=False)
        embed.add_field(name='結果', value='通過' if passed else '未通過', inline=False)
        embed.set_footer(text='投票已結束')

        targets = [vote_channel]
        if result_channel and result_channel.id != vote_channel.id:
            targets.append(result_channel)
        for ch in targets:
            await ch.send(embed=embed)

        if passed:
            member = await self.bot.get_or_fetch_member(guild, info['member'].id)
            try:
                await self.api.warn(
                    guild=guild,
                    members=[member],
                    author=info['initiator'],
                    level=info['level'],
                    reason=info.get('reason'),
                    time=info.get('time'),
                    ban_days=info.get('ban_days'),
                )
                msg = f"{member.mention} 的 {info['level']} 級警告已執行。"
            except Exception as e:
                msg = str(e)
        else:
            msg = f"{info['target'].mention} 的 {info['level']} 級警告投票未通過，已取消警告。"
        for ch in targets:
            await ch.send(msg)

    async def _vote_timeout(self, msg_id: int):
        info = self.active_votes.get(msg_id)
        if not info:
            return
        await asyncio.sleep((info['end_time'] - datetime.utcnow()).total_seconds())
        if msg_id in self.active_votes:
            await self._end_vote(msg_id)

    @commands.guild_only()
    @checks.admin()
    @commands.group()
    async def warnset(self, ctx):
        'WarnSystem 設定相關'
        pass

    @warnset.command(name='votechannel')
    async def set_vote_channel(self, ctx, channel: discord.TextChannel):
        await self.data.guild(ctx.guild).vote_channel.set(channel.id)
        await ctx.send(f'已設定投票頻道為 {channel.mention}')

    @warnset.command(name='resultchannel')
    async def set_result_channel(self, ctx, channel: discord.TextChannel):
        await self.data.guild(ctx.guild).result_channel.set(channel.id)
        await ctx.send(f'已設定結果頻道為 {channel.mention}')

    @commands.guild_only()
    @checks.mod()
    async def call_warn(
        self,
        ctx: commands.Context,
        level: int,
        member: discord.Member,
        reason: Optional[str] = None,
        time: Optional[timedelta] = None,
        ban_days: Optional[int] = None,
    ):
        reason = await self.api.format_reason(ctx.guild, reason)
        if level >= 3:
            guild_conf = await self.data.guild(ctx.guild).all()
            forbidden = guild_conf.get('forbidden_roles', []) or []
            if any(r.id in forbidden for r in member.roles):
                await ctx.send(f'{member.mention} 擁有禁止3級以上警告的身分組，無法發起此級別警告。')
                return
            vote_id = guild_conf.get('vote_channel')
            if not vote_id:
                await ctx.send('尚未設定投票頻道。')
                return
            vote_ch = ctx.guild.get_channel(vote_id)
            embed = discord.Embed(
                title='警告投票',
                description=f"{ctx.author.mention} 發起對 {member.mention} 的 {level} 級警告投票",
                color=discord.Color.orange()
            )
            if reason:
                embed.add_field(name='原因', value=reason, inline=False)
            embed.add_field(name='投票進度', value='```無投票記錄```', inline=False)
            embed.set_footer(text='24 小時內，✅/❌ 投票，Admin 專屬。')
            msg = await vote_ch.send(embed=embed)
            await msg.add_reaction('✅')
            await msg.add_reaction('❌')
            self.active_votes[msg.id] = {
                'initiator': ctx.author,
                'target': member,
                'level': level,
                'reason': reason,
                'time': time,
                'ban_days': ban_days,
                'channel': vote_ch,
                'member': member,
                'end_time': datetime.utcnow() + timedelta(hours=24)
            }
            asyncio.create_task(self._vote_timeout(msg.id))
            return
        try:
            fail = await self.api.warn(
                guild=ctx.guild,
                members=[member],
                author=ctx.author,
                level=level,
                reason=reason,
                time=time,
                ban_days=ban_days,
            )
            if fail:
                raise fail[0]
        except errors.MissingPermissions as e:
            await ctx.send(e)
            return
        except errors.MemberTooHigh as e:
            await ctx.send(e)
            return
        except errors.LostPermissions as e:
            await ctx.send(e)
            return
        except errors.SuicidePrevention as e:
            await ctx.send(e)
            return
        except errors.MissingMuteRole:
            await ctx.send(_('You need to set up the mute role before doing this.'))
            return
        except errors.NotFound:
            await ctx.send(_('Please set up a modlog channel before warning a member.'))
            return
        except errors.NotAllowedByHierarchy:
            is_admin = mod.is_admin_or_superior(self.bot, member)
            msg = _('You are not allowed to do this, {member} is higher than you in the role hierarchy.').format(member=str(member))
            if is_admin:
                msg += _(' You can disable this check by using the `[p]warnset hierarchy` command.')
            await ctx.send(msg)
            return
        except discord.errors.NotFound:
            await ctx.send(_('Hackban failed: No user found.'))
            return
        if ctx.channel.permissions_for(ctx.guild.me).add_reactions:
            try:
                await ctx.message.add_reaction('✅')
            except discord.errors.NotFound:
                pass
        else:
            await ctx.send(_('Done.'))

    async def call_masswarn(
        self,
        ctx: commands.Context,
        level: int,
        members: list[discord.Member],
        unavailable_members: list[UnavailableMember],
        log_modlog: bool,
        log_dm: bool,
        take_action: bool,
        reason: Optional[str] = None,
        time: Optional[timedelta] = None,
        confirm: bool = False,
    ):
        guild = ctx.guild
        message = None
        i = 0
        total_members = len(members)
        total_unavailable_members = len(unavailable_members)
        tick1 = "✅" if log_modlog else "❌"
        tick2 = "✅" if log_dm else "❌"
        tick3 = f"{'✅' if take_action else '❌'} Take action\n" if level != 1 else ""
        tick4 = f"{'✅' if time else '❌'} Time: " if (level == 2 or level == 5) else ""
        tick5 = "✅" if reason else "❌"
        time_str = (self.api._format_timedelta(time) + "\n") if time else ""

        async def update_count(count):
            nonlocal i
            i = count

        async def update_message():
            while True:
                nonlocal message
                content = _(
                    "Processing mass warning...\n"
                    "{i}/{total} {members} warned ({percent}%)\n\n"
                    "{tick1} Log to the modlog\n"
                    "{tick2} Send a DM to all members\n"
                    "{tick3}"
                    "{tick4} {time}\n"
                    "{tick5} Reason: {reason}"
                ).format(
                    i=i,
                    total=total_members + total_unavailable_members,
                    members=_("members") if i != 1 else _("member"),
                    percent=round((i / total_members) * 100, 2),
                    tick1=tick1,
                    tick2=tick2,
                    tick3=tick3,
                    tick4=tick4,
                    time=time_str,
                    tick5=tick5,
                    reason=reason or "Not set",
                )
                if message:
                    await message.edit(content=content)
                else:
                    message = await ctx.send(content)
                await asyncio.sleep(5)

        if unavailable_members and level < 5:
            await ctx.send(_("You can only use `--hackban-select` with a level 5 warn."))
            return
        reason = await self.api.format_reason(ctx.guild, reason)
        if (log_modlog or log_dm) and reason and len(reason) > 2000:  # embed limits
            await ctx.send(
                _(
                    "The reason is too long for an embed.\n\n"
                    "*Tip: You can use Github Gist to write a long text formatted in Markdown, "
                    "create a new file with the extension `.md` at the end and write as if you "
                    "were on Discord.\n<https://gist.github.com/>*"
                    # I was paid $99999999 for this, you're welcome
                )
            )
            return
        file = text_to_file(
            "\n".join([f"{str(x)} ({x.id})" for x in members + unavailable_members])
        )
        targets = []
        if members:
            targets.append(
                _("{total} {members} ({percent}% of the server)").format(
                    total=total_members,
                    members=_("members") if total_members > 1 else _("member"),
                    percent=round((total_members / len(guild.members) * 100), 2),
                )
            )
        if unavailable_members:
            targets.append(
                _("{total} {users} not in the server.").format(
                    total=total_unavailable_members,
                    users=_("users") if total_unavailable_members > 1 else _("user"),
                )
            )
        if not confirm:
            msg = await ctx.send(
                _(
                    "You're about to set a level {level} warning on {target}.\n\n"
                    "{tick1} Log to the modlog\n"
                    "{tick2} Send a DM to all members\n"
                    "{tick3}"
                    "{tick4} {time}\n"
                    "{tick5} Reason: {reason}\n\n{warning}"
                    "Continue?"
                ).format(
                    level=level,
                    target=_(" and ").join(targets),
                    tick1=tick1,
                    tick2=tick2,
                    tick3=tick3,
                    tick4=tick4,
                    time=time_str,
                    tick5=tick5,
                    reason=reason or _("Not set"),
                    warning=_(
                        ":warning: You're about to warn a lot of members! Avoid doing this to "
                        "prevent being rate limited by Discord, especially if you enabled DMs.\n\n"
                    )
                    if len(members) > 50 and level > 1
                    else "",
                ),
                file=file,
            )
            menus.start_adding_reactions(msg, predicates.ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = predicates.ReactionPredicate.yes_or_no(msg, ctx.author)
            try:
                await self.bot.wait_for("reaction_add", check=pred, timeout=120)
            except AsyncTimeoutError:
                if ctx.guild.me.guild_permissions.manage_messages:
                    await msg.clear_reactions()
                else:
                    for reaction in msg.reactions():
                        await msg.remove_reaction(reaction, ctx.guild.me)
                return
            if not pred.result:
                await ctx.send(_("Mass warn cancelled."))
                return
            task = self.bot.loop.create_task(update_message())
        try:
            fails = await self.api.warn(
                guild=guild,
                members=members + unavailable_members,
                author=ctx.author,
                level=level,
                reason=reason,
                time=time,
                log_modlog=log_modlog,
                log_dm=log_dm,
                take_action=take_action,
                progress_tracker=update_count if not confirm else None,
            )
        except errors.MissingPermissions as e:
            await ctx.send(e)
        except errors.LostPermissions as e:
            await ctx.send(e)
        except errors.MissingMuteRole:
            if not confirm:
                await ctx.send(
                    _(
                        "You need to set up the mute role before doing this.\n"
                        "Use the `[p]warnset mute` command for this."
                    )
                )
        except errors.NotFound:
            if not confirm:
                await ctx.send(
                    _(
                        "Please set up a modlog channel before warning a member.\n\n"
                        "**With WarnSystem**\n"
                        "*Use the `[p]warnset channel` command.*\n\n"
                        "**With Red Modlog**\n"
                        "*Load the `modlogs` cog and use the `[p]modlogset modlog` command.*"
                    )
                )
        else:
            if not confirm:
                if fails:
                    await ctx.send(
                        _("Done! {failed} {members} out of {total} couldn't be warned.").format(
                            failed=len(fails),
                            members=_("members") if len(fails) > 1 else _("member"),
                            total=total_members,
                        )
                    )
                else:
                    await ctx.send(
                        _("Done! {total} {members} successfully warned.").format(
                            total=total_members,
                            members=_("members") if total_members > 1 else _("member"),
                        )
                    )
            else:
                try:
                    await ctx.message.add_reaction("✅")
                except discord.errors.HTTPException:
                    pass
        finally:
            if not confirm:
                task.cancel()
            if message:
                await message.delete()

    # all warning commands
    @commands.group(invoke_without_command=True, name="warn")
    @checks.mod_or_permissions(administrator=True)
    @commands.guild_only()
    async def _warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """
        Take actions against a user and log it.
        The warned user will receive a DM.

        If not given, the warn level will be 1.
        """
        await self.call_warn(ctx, 1, member, reason)

    @_warn.command(name="1", aliases=["simple"])
    @checks.mod_or_permissions(administrator=True)
    async def warn_1(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """
        Set a simple warning on a user.

        Note: You can either call `[p]warn 1` or `[p]warn`.
        """
        await self.call_warn(ctx, 1, member, reason)

    @_warn.command(name="2", aliases=["mute"])
    @checks.mod_or_permissions(administrator=True)
    async def warn_2(
        self,
        ctx: commands.Context,
        member: discord.Member,
        time: Optional[TimedeltaConverter],
        *,
        reason: Optional[str] = None,
    ):
        """
        Mute the user in all channels, including voice channels.

        This mute will use a role that will automatically be created, if it was not already done.
        Feel free to edit the role's permissions and move it in the roles hierarchy.

        You can set a timed mute by providing a valid time before the reason.

        Examples:
        - `[p]warn 2 @user 30m`: 30 minutes mute
        - `[p]warn 2 @user 5h Spam`: 5 hours mute for the reason "Spam"
        - `[p]warn 2 @user Advertising`: Infinite mute for the reason "Advertising"
        """
        await self.call_warn(ctx, 2, member, reason, time)

    @_warn.command(name="3", aliases=["kick"])
    @checks.mod_or_permissions(administrator=True)
    async def warn_3(
        self, ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None
    ):
        """
        Kick the member from the server.
        """
        await self.call_warn(ctx, 3, member, reason)

    @_warn.command(name="4", aliases=["softban"])
    @checks.mod_or_permissions(administrator=True)
    async def warn_4(
        self, ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None
    ):
        """
        Softban the member from the server.

        This means that the user will be banned and immediately unbanned, so it will purge their\
        messages in all channels.

        It will delete 7 days of messages by default, but you can edit this with the\
        `[p]warnset bandays` command.
        """
        await self.call_warn(ctx, 4, member, reason)

    @_warn.command(name="5", aliases=["ban"], usage="<member> [time] <reason>")
    @checks.mod_or_permissions(administrator=True)
    async def warn_5(
        self,
        ctx: commands.Context,
        member: UnavailableMember,
        time: Optional[TimedeltaConverter],
        *,
        reason: Optional[str] = None,
    ):
        """
        Ban the member from the server.

        This ban can be a normal ban, a temporary ban or a hack ban (bans a user not in the\
        server).
        It won't delete messages by default, but you can edit this with the `[p]warnset bandays`\
        command.

        If you want to perform a temporary ban, provide the time before the reason. A hack ban\
        needs a user ID, you can get it with the Developer mode (enable it in the Appearance tab\
        of the user settings, then right click on the user and select "Copy ID").

        Examples:
        - `[p]warn 5 @user`: Ban for no reason :c
        - `[p]warn 5 @user 7d Insults`: 7 days ban for the reason "Insults"
        - `[p]warn 5 012345678987654321 Advertising and leave`: Ban the user with the ID provided\
        while they're not in the server for the reason "Advertising and leave" (if the user shares\
        another server with the bot, a DM will be sent).
        """
        await self.call_warn(ctx, 5, member, reason, time)

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @checks.mod_or_permissions(administrator=True)
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def masswarn(self, ctx: commands.Context, *selection: str):
        """
        Perform a warn on multiple members at once.

        To select members, you have to use UNIX-like flags to add conditions\
        which will be checked for each member.

        Example: `[p]masswarn 3 --take-action --send-dm --has-role "Danger"\
        --joined-after "May 2019" --reason "Cleaning dangerous members"`

        To get the full list of flags and how to use them, please read the\
        wiki: https://laggrons-dumb-cogs.readthedocs.io/
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            1,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            None,
            selection.confirm,
        )

    @masswarn.command(name="1", aliases=["simple"])
    @checks.mod_or_permissions(administrator=True)
    async def masswarn_1(self, ctx: commands.Context, *selection: str):
        """
        Perform a simple mass warning.
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            1,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            None,
            selection.confirm,
        )

    @masswarn.command(name="2", aliases=["mute"])
    @checks.mod_or_permissions(administrator=True)
    async def masswarn_2(self, ctx: commands.Context, *selection: str):
        """
        Perform a mass mute.

        You can provide a duration with the `--time` flag, the format is the same as the simple\
        level 2 warning.
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            2,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            selection.time,
            selection.confirm,
        )

    @masswarn.command(name="3", aliases=["kick"])
    @checks.mod_or_permissions(administrator=True)
    async def masswarn_3(self, ctx: commands.Context, *selection: str):
        """
        Perform a mass kick.
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            3,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            None,
            selection.confirm,
        )

    @masswarn.command(name="4", aliases=["softban"])
    @checks.mod_or_permissions(administrator=True)
    async def masswarn_4(self, ctx: commands.Context, *selection: str):
        """
        Perform a mass softban.
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            4,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            None,
            selection.confirm,
        )

    @masswarn.command(name="5", aliases=["ban"])
    @checks.mod_or_permissions(administrator=True)
    async def masswarn_5(self, ctx: commands.Context, *selection: str):
        """
        Perform a mass ban.

        You can provide a duration with the `--time` flag, the format is the same as the simple\
        level 5 warning.
        """
        if not selection:
            await ctx.send_help()
            return
        try:
            selection = await AdvancedMemberSelect().convert(ctx, selection)
        except commands.BadArgument as e:
            await ctx.send(e)
            return
        await self.call_masswarn(
            ctx,
            5,
            selection.members,
            selection.unavailable_members,
            selection.send_modlog,
            selection.send_dm,
            selection.take_action,
            selection.reason,
            selection.time,
            selection.confirm,
        )

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.member)
    async def warnings(
        self, ctx: commands.Context, user: Optional[UnavailableMember] = None, index: int = 0
    ):
        """
        Shows all warnings of a member.

        This command can be used by everyone, but only moderators can see other's warnings.
        Moderators can also edit or delete warnings by using the reactions.
        """
        if not user:
            await ctx.send_help()
            return
        if (
            not (
                await mod.is_mod_or_superior(self.bot, ctx.author)
                or ctx.author.guild_permissions.kick_members
            )
            and user != ctx.author
        ):
            await ctx.send(_("You are not allowed to see other's warnings!"))
            return
        cases = await self.api.get_all_cases(ctx.guild, user)
        if not cases:
            await ctx.send(_("That member was never warned."))
            return
        if 0 < index < len(cases):
            await ctx.send(_("That case doesn't exist."))
            return

        total = lambda level: len([x for x in cases if x["level"] == level])
        warning_str = lambda level, plural: {
            1: (_("Warning"), _("Warnings")),
            2: (_("Mute"), _("Mutes")),
            3: (_("Kick"), _("Kicks")),
            4: (_("Softban"), _("Softbans")),
            5: (_("Ban"), _("Bans")),
        }.get(level, _("unknown"))[1 if plural else 0]

        msg = []
        for i in range(6):
            total_warns = total(i)
            if total_warns > 0:
                msg.append(f"{warning_str(i, total_warns > 1)}: {total_warns}")
        warn_field = "\n".join(msg) if len(msg) > 1 else msg[0]
        embed = discord.Embed(description=_("User modlog summary."))
        embed.set_author(name=f"{user} | {user.id}", icon_url=user.display_avatar.url)
        embed.add_field(
            name=_("Total number of warnings: ") + str(len(cases)), value=warn_field, inline=False
        )
        embed.colour = user.top_role.colour

        paginator = WarningsSelector(ctx, user, cases)
        await paginator.start(embed=embed)

    @commands.command()
    @checks.mod_or_permissions(kick_members=True)
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def warnlist(self, ctx: commands.Context, short: bool = False):
        """
        List the latest warnings issued on the server.
        """
        guild = ctx.guild
        full_text = ""
        warns = await self.api.get_all_cases(guild)
        if not warns:
            await ctx.send(_("No warnings have been issued in this server yet."))
            return
        for i, warn in enumerate(warns, start=1):
            text = _(
                "--- Case {number} ---\n"
                "Member:    {member} (ID: {member.id})\n"
                "Level:     {level}\n"
                "Reason:    {reason}\n"
                "Author:    {author} (ID: {author.id})\n"
                "Date:      {time}\n"
            ).format(number=i, **warn)
            if warn["duration"]:
                duration = self.api._get_timedelta(warn["duration"])
                text += _("Duration:  {duration}\nUntil:     {until}\n").format(
                    duration=self.api._format_timedelta(duration),
                    until=self.api._format_datetime(warn["time"] + duration),
                )
            text += "\n\n"
            full_text = text + full_text
        pages = [
            x for x in pagify(full_text, delims=["\n\n", "\n"], priority=True, page_length=1900)
        ]
        total_pages = len(pages)
        total_warns = len(warns)
        pages = [
            f"```yml\n{x}```\n"
            + _("{total} warnings. Page {i}/{pages}").format(
                total=total_warns, i=i, pages=total_pages
            )
            for i, x in enumerate(pages, start=1)
        ]
        await menus.menu(ctx=ctx, pages=pages, controls=menus.DEFAULT_CONTROLS, timeout=60)

    @commands.command()
    @checks.mod_or_permissions(manage_roles=True)
    async def wsunmute(self, ctx: commands.Context, member: discord.Member):
        """
        Unmute a member muted with WarnSystem.

        If the member's roles were removed, they will be granted back.

        *wsunmute = WarnSystem unmute. Feel free to add an alias.*
        """
        guild = ctx.guild
        mute_role = guild.get_role(await self.cache.get_mute_role(guild))
        if not mute_role:
            await ctx.send(_("The mute role is not set or lost."))
            return
        if mute_role not in member.roles:
            await ctx.send(_("That member isn't muted."))
            return
        case = await self.cache.get_temp_action(guild, member)
        if case and case["level"] == 2:
            roles = case["roles"]
            await self.cache.remove_temp_action(guild, member)
        else:
            cases = await self.api.get_all_cases(guild, member)
            roles = []
            for data in cases[::-1]:
                if data["level"] == 2:
                    try:
                        roles = data["roles"]
                    except KeyError:
                        continue
                    break
        await member.remove_roles(
            mute_role,
            reason=_("[WarnSystem] Member unmuted by {author} (ID: {author.id})").format(
                author=ctx.author
            ),
        )
        roles = list(filter(None, [guild.get_role(x) for x in roles]))
        if not roles:
            await ctx.send(_("Member unmuted."))
            return
        await ctx.send(
            _("Member unmuted. {len_roles} roles to reassign...").format(len_roles=len(roles))
        )
        async with ctx.typing():
            fails = []
            for role in roles:
                try:
                    await member.add_roles(role)
                except discord.errors.HTTPException as e:
                    log.error(
                        f"Failed to reapply role {role} ({role.id}) on guild {guild} "
                        f"({guild.id}) after unmute.",
                        exc_info=e,
                    )
                    fails.append(role)
        text = _("Done.")
        if fails:
            text.append(_("\n\nFailed to add {fails}/{len_roles} roles back:\n"))
            for role in fails:
                text.append(f"- {role.name}\n")
        for page in pagify(text):
            await ctx.send(page)

    @commands.command()
    @commands.bot_has_permissions(ban_members=True)
    @checks.mod_or_permissions(ban_members=True)
    async def wsunban(self, ctx: commands.Context, member_id: int):
        """
        Unban a member banned with WarnSystem.

        *wsunban = WarnSystem unban. Feel free to add an alias.*
        """
        guild = ctx.guild
        try:
            ban_entry = await guild.fetch_ban(discord.Object(member_id))
        except discord.NotFound:
            await ctx.send(_("That user is not banned."))
            return
        member = ban_entry.user
        try:
            await guild.unban(member)
        except discord.errors.HTTPException as e:
            await ctx.send(_("Failed to unban the given member. Check your logs for details."))
            log.error(f"Can't unban user {member.id} from guild {guild} ({guild.id})", exc_info=e)
            return
        case = await self.cache.get_temp_action(guild, member)
        if case and case["level"] == 5:
            await self.cache.remove_temp_action(guild, member)
        await ctx.send(_("User unbanned."))

    @commands.command(hidden=True)
    async def warnsysteminfo(self, ctx: commands.Context):
        """
        Get informations about the cog.
        """
        await ctx.send(
            _(
                "Laggron's Dumb Cogs V3 - warnsystem\n\n"
                "Version: {0.__version__}\n"
                "Author: {0.__author__[0]}\n\n"
                "Github repository: https://github.com/retke/Laggrons-Dumb-Cogs/tree/v3\n"
                "Discord server: https://discord.gg/GET4DVk\n"
                "Documentation: http://laggrons-dumb-cogs.readthedocs.io/\n"
                "Help translating the cog: https://crowdin.com/project/laggrons-dumb-cogs/\n\n"
                "Support my work on Patreon: https://www.patreon.com/retke"
            ).format(self)
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        # if a member gets unbanned, we check if they were temp banned with warnsystem
        # if it was, we remove the case so it won't unban them a second time
        warns = await self.cache.get_temp_action(guild)
        to_remove = []  # there can be multiple temp bans, let's not question the moderators
        for member, data in warns.items():
            if data["level"] == 2 or int(member) != user.id:
                continue
            to_remove.append(UnavailableMember(self.bot, guild._state, member))
        if to_remove:
            await self.cache.bulk_remove_temp_action(guild, to_remove)
            log.info(
                f"[Guild {guild.id}] The temporary ban of user {user} (ID: {user.id}) "
                "was cancelled due to their manual unban."
            )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild
        mute_role = guild.get_role(await self.cache.get_mute_role(guild))
        if not mute_role:
            return
        if not (mute_role in before.roles and mute_role not in after.roles):
            return
        if after.id in self.cache.temp_actions:
            await self.cache.remove_temp_action(guild, after)
            log.info(
                f"[Guild {guild.id}] The temporary mute of member {after} (ID: {after.id}) "
                "was ended due to a manual unmute (role removed)."
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        if isinstance(channel, discord.VoiceChannel):
            return
        if not await self.data.guild(guild).update_mute():
            return
        role = guild.get_role(await self.cache.get_mute_role(guild))
        if not role:
            return
        try:
            await channel.set_permissions(
                role,
                send_messages=False,
                add_reactions=False,
                reason=_(
                    "Updating channel settings so the mute role will work here. "
                    "Disable the auto-update with [p]warnset autoupdate"
                ),
            )
        except discord.errors.Forbidden:
            log.warn(
                f"[Guild {guild.id}] Couldn't update permissions of new channel {channel.name} "
                f"(ID: {channel.id}) due to a permission error."
            )
        except discord.errors.HTTPException as e:
            log.error(
                f"[Guild {guild.id}] Couldn't update permissions of new channel {channel.name} "
                f"(ID: {channel.id}) due to an unknown error.",
                exc_info=e,
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, member: discord.Member):
        await self.on_manual_action(guild, member, 5)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.on_manual_action(member.guild, member, 3)

    async def on_manual_action(self, guild: discord.Guild, member: discord.Member, level: int):
        # most of this code is from Cog-Creators, modlog cog
        # https://github.com/Cog-Creators/Red-DiscordBot/blob/bc21f779762ec9f460aecae525fdcd634f6c2d85/redbot/core/modlog.py#L68
        if not guild.me.guild_permissions.view_audit_log:
            return
        if not await self.data.guild(guild).log_manual():
            return
        # check for that before doing anything else, means WarnSystem isn't setup
        try:
            await self.api.get_modlog_channel(guild, level)
        except errors.NotFound:
            return
        when = datetime.now(timezone.utc)
        before = when + timedelta(minutes=1)
        after = when - timedelta(minutes=1)
        await asyncio.sleep(10)  # prevent small delays from causing a 5 minute delay on entry
        attempts = 0
        action = {
            3: discord.AuditLogAction.kick,
            5: discord.AuditLogAction.ban,
        }[level]
        # wait up to 15 min to find a matching case
        while attempts < 3:
            attempts += 1
            try:
                async for entry in guild.audit_logs(action=action, before=before, after=after):
                    if entry.target.id == member.id and after < entry.created_at < before:
                        break
                else:
                    break
            except discord.Forbidden:
                break
            except discord.HTTPException:
                pass
            else:
                if entry:
                    if entry.user.id != guild.me.id:
                        # Don't create modlog entires for the bot's own bans, cogs do this.
                        mod, reason, date = entry.user, entry.reason, entry.created_at
                        if isinstance(member, discord.User):
                            member = UnavailableMember(self.bot, guild._state, member.id)
                        try:
                            await self.api.warn(
                                guild,
                                [member],
                                mod,
                                level,
                                reason,
                                date=date,
                                log_dm=True if level <= 2 else False,
                                take_action=False,
                            )
                        except Exception as e:
                            log.error(
                                f"[Guild {guild.id}] Failed to create a case "
                                "based on manual action. "
                                f"Member: {member} ({member.id}). Author: {mod} ({mod.id}). "
                                f"Reason: {reason}",
                                exc_info=e,
                            )
                    return
            await asyncio.sleep(300)

    async def _red_get_data_for_user(self, *, user_id: int):
        readme = (
            "--- WarnSystem user data ---\n\n\n"
            "This cog is a tool for moderators and administrators for taking actions against "
            "members of their server and log it. You can read more about this cog here:\n"
            "https://github.com/retke/Laggrons-Dumb-Cogs/tree/v3/warnsystem#warnsystem\n\n"
            "As soon as a member is warned, the cog will store the following data:\n"
            "- User ID\n"
            "- Warn level (from 1 to 5: warn, mute, kick, softban, ban)\n"
            "- Warn reason\n"
            "- Warn author (responsible moderator. can be the bot in case of automated warns)\n"
            "- Date and time of the warn\n"
            "- Duration of the warn (only in case of a temporary mute/ban)\n"
            "- List of the roles the member had when they were muted "
            "(only for mutes since version 1.2)\n\n"
            "A list of files is provided, one for each server. The ID of the server is the name "
            "of the file. Servers without registered warnings are not included.\n\n"
            "Additonal notes:\n"
            "- The timezone for date and time is UTC.\n"
            "- For durations, the raw number of seconds is included.\n"
            "- The end date of a temp warn is obtained by adding the duration to the date.\n"
            "- The responsible moderator of a warn is not included, as this is private data.\n\n\n"
            "Author of WarnSystem: retke (El Laggron)\n"
            "Repo: https://github.com/retke/Laggrons-Dumb-Cogs\n"
            "Contact info is in the README of that repo.\n"
        )
        file = BytesIO()
        file.write(readme.encode("utf-8"))
        files = {"README": file}
        all_modlogs = await self.data.custom("MODLOGS").all()
        for guild_id, modlogs in all_modlogs.items():
            if str(user_id) not in modlogs:
                files[guild_id] = BytesIO()
            guild = self.bot.get_guild(int(guild_id))
            text = "Modlogs registered for server {guild}\n".format(
                guild=guild.name if guild else f"{guild_id} (not found)"
            )
            for i, modlog in enumerate(modlogs[str(user_id)]["x"]):
                text += (
                    "\n\n\n--- Case {number} ---\nLevel:     {level}\nReason:    {reason}\n"
                ).format(number=i + 1, **modlog)
                text += "Date:      {date}\n".format(
                    date=self.api._format_datetime(self.api._get_datetime(modlog["time"]))
                )
                if modlog["duration"]:
                    duration = self.api._get_timedelta(modlog["duration"])
                    text += "Duration:  {duration} (raw: {raw}s)\n".format(
                        duration=self.api._format_timedelta(duration),
                        raw=modlog["duration"],
                    )
                if modlog["roles"]:
                    text += "Roles:     {roles}\n".format(roles=", ".join(modlog["roles"]))
            file = BytesIO()
            file.write(text.encode("utf-8"))
            files[guild_id] = file
        return files

    async def red_get_data_for_user(self, *, user_id: int):
        try:
            data = await self._red_get_data_for_user(user_id=user_id)
        except Exception as e:
            log.error(
                f"User {user_id} has requested end user data but an exception occured!", exc_info=e
            )
            raise
        else:
            log.info(
                f"User {user_id} has requested end user data, which was successfully provided."
            )
            return data

    async def _red_delete_data_for_user(self, *, requester: str, user_id: int):
        allowed_requesters = ("discord_deleted_user",)
        if requester not in allowed_requesters:
            return False
        async with self.data.custom("MODLOGS").all() as all_modlogs:
            for guild_id, modlogs in all_modlogs.items():
                try:
                    del all_modlogs[guild_id][str(user_id)]
                except KeyError:
                    pass
        return True

    async def red_delete_data_for_user(self, *, requester: str, user_id: int):
        try:
            result = await self._red_delete_data_for_user(requester=requester, user_id=user_id)
        except Exception as e:
            log.error(
                f"User {user_id} has requested end user data deletion but an exception occured!",
                exc_info=e,
            )
            raise
        else:
            if result is True:
                log.info(
                    f"User {user_id} has requested end user data "
                    "deletion, which was successfully done."
                )

    def cog_unload(self):
        log.debug("Unloading cog...")

        # stop checking for unmute and unban
        self.task.cancel()
        self.api.disable_automod()
        self.api.re_pool.close()
