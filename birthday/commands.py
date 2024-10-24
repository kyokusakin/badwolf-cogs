from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import TYPE_CHECKING, Literal, Union

import discord
from redbot.core import Config, commands
from redbot.core.commands import CheckFailure
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import box, pagify, warning
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate
from rich.table import Table  # type:ignore

from .abc import MixinMeta
from .components.setup import SetupView
from .consts import MAX_BDAY_MSG_LEN, MIN_BDAY_YEAR
from .converters import BirthdayConverter, TimeConverter
from .utils import channel_perm_check, format_bday_message, role_perm_check
from .vexutils import get_vex_logger, no_colour_rich_markup
from .vexutils.button_pred import wait_for_yes_no

log = get_vex_logger(__name__)


class BirthdayCommands(MixinMeta):
    async def setup_check(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise CheckFailure("This command can only be used in a server.")
            # this should have been caught by guild only check, but this keeps type checker happy
            # and idk what order decos run in so

        if not await self.check_if_setup(ctx.guild):
            await ctx.send(
                "此命令在未設置該功能模組之前無法使用。"
                f"請讓管理員使用 `{ctx.clean_prefix}bdset interactive` 開始設置。"
            )
            raise CheckFailure("cog needs setup")

    @commands.guild_only()  # type:ignore
    @commands.before_invoke(setup_check)  # type:ignore
    @commands.hybrid_group(aliases=["bday"])
    async def birthday(self, ctx: commands.Context):
        """Set and manage your birthday."""

    @birthday.command(aliases=["add"])
    async def set(self, ctx: commands.Context, *, birthday: BirthdayConverter):
        """
        設定您的生日。

        您可以選擇性地添加年份，如果您願意分享的話。

        如果您使用的日期格式是 YYYY/MM/DD 或 YYYY-MM-DD，則預設為 YYYY-MM-DD。

        **範例：**
        - `[p]bday set 9 24 `
        - `[p]bday set 2002 09 24`
        - `[p]bday set 2002/9/24`
        - `[p]bday set 2002-9-24`
        - `[p]bday set 9-24`
        """
        # guild only check in group
        if TYPE_CHECKING:
            assert isinstance(ctx.author, discord.Member)

        # year as 1 means year not specified

        if birthday.year != 1 and birthday.year < MIN_BDAY_YEAR:
            await ctx.send(f"抱歉，我無法將您的生日設定為在 {MIN_BDAY_YEAR} 之前。")
            return

        if birthday > datetime.utcnow():
            await ctx.send("您不可以設定未來的出生日期！")
            return

        async with self.config.member(ctx.author).birthday() as bday:
            bday["year"] = birthday.year if birthday.year != 1 else None
            bday["month"] = birthday.month
            bday["day"] = birthday.day

        if birthday.year == 1:
            str_bday = birthday.strftime("%m/%d")
        else:
            str_bday = birthday.strftime("%Y/%m/%d")

        await ctx.send(f"您的生日已設定為 {str_bday}。")

    @birthday.command(aliases=["delete", "del"])
    async def remove(self, ctx: commands.Context):
        """Remove your birthday."""
        # guild only check in group
        if TYPE_CHECKING:
            assert isinstance(ctx.author, discord.Member)
            assert ctx.guild is not None

        m = await ctx.send("你確定?")
        start_adding_reactions(m, ReactionPredicate.YES_OR_NO_EMOJIS)
        check = ReactionPredicate.yes_or_no(m, ctx.author)  # type:ignore

        try:
            await self.bot.wait_for("reaction_add", check=check, timeout=60)
        except asyncio.TimeoutError:
            for reaction in ReactionPredicate.YES_OR_NO_EMOJIS:
                await m.remove_reaction(reaction, ctx.guild.me)
            return

        if check.result is False:
            await ctx.send("已取消。")
            return

        await self.config.member(ctx.author).birthday.set({})
        await ctx.send("您的生日已被刪除。")

    @birthday.command()
    async def upcoming(self, ctx: commands.Context, days: int = 7):
        """
        查看即將到來的生日，預設為 7 天。

        **範例：**
        - `[p]birthday upcoming` - 預設為 7 天
        - `[p]birthday upcoming 14` - 14 天
        """
        # guild only check in group
        if TYPE_CHECKING:
            assert isinstance(ctx.author, discord.Member)
            assert ctx.guild is not None

        if days < 1 or days > 365:
            await ctx.send("您必須輸入一個大於 0 且小於 365 的天數。")
            return

        today_dt = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        all_birthdays: dict[int, dict[str, dict]] = await self.config.all_members(ctx.guild)

        log.trace("raw data for all bdays: %s", all_birthdays)

        parsed_bdays: dict[int, list[str]] = defaultdict(list)
        number_day_mapping: dict[int, str] = {}

        async for member_id, member_data in AsyncIter(all_birthdays.items(), steps=50):
            if not member_data["birthday"]:  # birthday removed but user remains in config
                continue
            member = ctx.guild.get_member(member_id)
            if not isinstance(member, discord.Member):
                continue

            birthday_dt = datetime(
                year=member_data["birthday"]["year"] or 1,
                month=member_data["birthday"]["month"],
                day=member_data["birthday"]["day"],
            )

            if today_dt.month == birthday_dt.month and today_dt.day == birthday_dt.day:
                parsed_bdays[0].append(
                    member.mention
                    + (
                        ""
                        if birthday_dt.year == 1
                        else f"將滿{today_dt.year - birthday_dt.year}"
                    )
                )
                number_day_mapping[0] = "今天"
                continue

            this_year_bday = birthday_dt.replace(year=today_dt.year)
            next_year_bday = birthday_dt.replace(year=today_dt.year + 1)
            next_birthday_dt = this_year_bday if this_year_bday > today_dt else next_year_bday

            diff = next_birthday_dt - today_dt
            if diff.days > days:
                continue

            next_bday_year = (
                today_dt.year if today_dt.year == next_birthday_dt.year else today_dt.year + 1
            )

            parsed_bdays[diff.days].append(
                member.mention
                + (
                    ""
                    if birthday_dt.year == 1
                    else (f" 將滿 {next_bday_year - birthday_dt.year}")
                )
            )
            number_day_mapping[diff.days] = next_birthday_dt.strftime("%m/%d")

        log.trace("bdays parsed: %s", parsed_bdays)

        if len(parsed_bdays) == 0:
            await ctx.send(f"在接下來的 {days} 天內沒有即將到來的生日。")
            return

        sorted_parsed_bdays = sorted(parsed_bdays.items(), key=lambda x: x[0])

        embed = discord.Embed(title="即將到來的生日", colour=await ctx.embed_colour())

        if len(sorted_parsed_bdays) > 25:
            embed.description = "Too many days to display. I've had to stop at 25."
            sorted_parsed_bdays = sorted_parsed_bdays[:25]

        for day, members in sorted_parsed_bdays:
            embed.add_field(name=number_day_mapping.get(day), value="\n".join(members))

        await ctx.send(embed=embed)


class BirthdayAdminCommands(MixinMeta):
    @commands.guild_only()
    @commands.is_owner()
    @commands.group(hidden=True)
    async def birthdaydebug(self, ctx: commands.Context):
        """Birthday debug commands."""

    @birthdaydebug.command(name="upcoming")
    async def debug_upcoming(self, ctx: commands.Context):
        await ctx.send_interactive(pagify(str(await self.config.all_members(ctx.guild))), "py")

    @commands.group()
    @commands.guild_only()  # type:ignore
    @commands.admin_or_permissions(manage_guild=True)
    async def bdset(self, ctx: commands.Context):
        """
        管理員的管理命令。

        想要設定自己的生日？使用 `[p]birthday set` 或 `[p]bday set`。
        """

    @commands.bot_has_permissions(manage_roles=True)
    @bdset.command()
    async def interactive(self, ctx: commands.Context):
        """Start interactive setup"""
        # guild only check in group
        if TYPE_CHECKING:
            assert isinstance(ctx.author, discord.Member)

        await ctx.send("點擊下方開始。", view=SetupView(ctx.author, self.bot, self.config))

    @bdset.command()
    async def settings(self, ctx: commands.Context):
        """View your current settings"""
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None
            assert isinstance(ctx.me, discord.Member)

        table = Table("Name", "Value", title="Settings for this server")

        async with self.config.guild(ctx.guild).all() as conf:
            log.trace("raw config: %s", conf)

            channel = ctx.guild.get_channel(conf["channel_id"])
            table.add_row("Channel", channel.name if channel else "Channel deleted")

            role = ctx.guild.get_role(conf["role_id"])
            table.add_row("Role", role.name if role else "Role deleted")

            if conf["time_utc_s"] is None:
                time = "invalid"
            else:
                time = datetime.utcfromtimestamp(conf["time_utc_s"]).strftime("%H:%M UTC")
                table.add_row("Time", time)

            table.add_row("Allow role mentions", str(conf["allow_role_mention"]))

            req_role = ctx.guild.get_role(conf["require_role"])
            if req_role:
                table.add_row(
                    "Required role",
                    req_role.name
                    + ". Only users with this role can set their birthday and have it announced.",
                )
            else:
                table.add_row(
                    "Required role",
                    "Not set. All users can set their birthday and have it announced.",
                )

            message_w_year = conf["message_w_year"] or "No message set"
            message_wo_year = conf["message_wo_year"] or "No message set"

        warnings = "\n"
        if (error := role is None) or (error := role_perm_check(ctx.me, role)):
            if isinstance(error, bool):
                error = "Role deleted."
            warnings += warning(error + " This may result in repeated notifications.\n")
        if (error := channel is None) or (error := channel_perm_check(ctx.me, channel)):
            if isinstance(error, bool):
                error = "Channel deleted."
            warnings += warning(error + " You won't get birthday notifications.\n")

        final_table = no_colour_rich_markup(table)
        message = (
            final_table
            + "\n帶年份的訊息:\n"
            + box(message_w_year)
            + "\n不帶年份的訊息:\n"
            + box(message_wo_year)
            + warnings
        )
        await ctx.send(message)

    @bdset.command()
    async def time(self, ctx: commands.Context, *, time: TimeConverter):
        """
        設定生日訊息的發送時間（UTC+8）。

        分鐘將被忽略。

        **範例：**
        - `[p]bdset time 7:00` - 設定時間為 7:00 AM (UTC+8)
        - `[p]bdset time 12AM` - 設定時間為 凌晨 12:00 (UTC+8)
        - `[p]bdset time 3PM` - 設定時間為 下午 3:00 (UTC+8)
        """
        if TYPE_CHECKING:
            assert ctx.guild is not None

        # 將時間轉換為帶有時區的 datetime
        time_utc8 = time.replace(tzinfo=timezone(timedelta(hours=8)))

        # 設定自午夜 (UTC+8) 開始的秒數
        midnight_utc8 = datetime.now(timezone(timedelta(hours=8))).replace(
            year=1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        # 計算設定時間的秒數
        time_utc8_s = int((time_utc8 - midnight_utc8).total_seconds())

        async with self.config.guild(ctx.guild).all() as conf:
            old = conf["time_utc_s"]
            conf["time_utc_s"] = time_utc8_s

            if old is None:
                conf["setup_state"] += 1

        # 用戶輸入的時間仍以 UTC+8 顯示
        m = (
            "時間已設定！我將在"
            f" {time.strftime('%H:%M')} UTC+8 發送生日訊息並更新生日角色。"
        )

        if old is not None:
            old_dt = datetime.fromtimestamp(old, tz=timezone.utc) + timedelta(hours=8)
            if time_utc8 > old_dt and time_utc8 > datetime.now(timezone(timedelta(hours=8))):
                m += (
                    "\n\n您設定的時間在我目前發送生日訊息的時間之後，"
                    "所以生日訊息將會第二次發送。"
                )
        await ctx.send(m)


    @bdset.command()
    async def msgwithoutyear(self, ctx: commands.Context, *, message: str):
        """
        設定用戶未提供年份時發送的訊息。

        如果您想提及一個角色，您需要運行 `[p]bdset rolemention true`。

        **佔位符：**
        - `{name}` - 用戶的名字
        - `{mention}` - 用戶的 @ 提及

            所有佔位符都是可選的。

        **範例：**
        - `[p]bdset msgwithoutyear 生日快樂 {mention}！`
        - `[p]bdset msgwithoutyear {mention} 的生日是今天！生日快樂 {name}。`
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None
            assert isinstance(ctx.author, discord.Member)

        if len(message) > MAX_BDAY_MSG_LEN:
            await ctx.send(
                f"該訊息太長！必須少於 {MAX_BDAY_MSG_LEN} 個字符。"
            )

        try:
            format_bday_message(message, ctx.author, 1)
        except KeyError as e:
            await ctx.send(
                f"You have a placeholder `{{{e.args[0]}}}` that is invalid. You can only include"
                " `{name}` and `{mention}` for the message without a year."
            )
            return

        async with self.config.guild(ctx.guild).all() as conf:
            if conf["message_wo_year"] is None:
                conf["setup_state"] += 1

            conf["message_wo_year"] = message

        await ctx.send("訊息已設定。以下是它的樣子：")
        await ctx.send(
            format_bday_message(message, ctx.author),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @bdset.command()
    async def msgwithyear(self, ctx: commands.Context, *, message: str):
        """
        設定用戶提供年份時發送的訊息。

        如果您想提及一個角色，您需要運行 `[p]bdset rolemention true`

        **佔位符:**
        - `{name}` - 用戶的名字
        - `{mention}` - 用戶的 @ 提及
        - `{new_age}` - 用戶的新年齡

            所有佔位符都是可選的。

        **範例:**
        - `[p]bdset msgwithyear {mention} 已經 {new_age} 歲了，生日快樂！`
        - `[p]bdset msgwithyear {name} 今天 {new_age} 歲！生日快樂 {mention}！`
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None
            assert isinstance(ctx.author, discord.Member)

        if len(message) > MAX_BDAY_MSG_LEN:
            await ctx.send(
                f"That message is too long! It needs to be under {MAX_BDAY_MSG_LEN} characters."
            )

        try:
            format_bday_message(message, ctx.author, 1)
        except KeyError as e:
            await ctx.send(
                f"您有一個無效的佔位符 `{{{e.args[0]}}}`。您只能包含"
                " `{name}`、`{mention}` 和 `{new_age}` 作為包含年份的訊息。"
            )
            return

        async with self.config.guild(ctx.guild).all() as conf:
            if conf["message_w_year"] is None:
                conf["setup_state"] += 1

            conf["message_w_year"] = message

        await ctx.send("訊息已設定。以下是如果您滿 20 歲時的樣子：")
        await ctx.send(
            format_bday_message(message, ctx.author, 20),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @bdset.command()
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        設定生日訊息將發送的頻道。

        **範例：**
        - `[p]bdset channel #birthdays` - 設定頻道為 #birthdays
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None
            assert isinstance(ctx.me, discord.Member)

        if channel.permissions_for(ctx.me).send_messages is False:
            await ctx.send(
                "I can't do that because I don't have permissions to send messages in"
                f" {channel.mention}."
            )
            return

        async with self.config.guild(ctx.guild).all() as conf:
            if conf["channel_id"] is None:
                conf["setup_state"] += 1

            conf["channel_id"] = channel.id

        await ctx.send(f"Channel set to {channel.mention}.")

    @commands.bot_has_permissions(manage_roles=True)
    @bdset.command()
    async def role(self, ctx: commands.Context, *, role: discord.Role):
        """
        設定在用戶生日時將賦予的角色。

        您可以給出確切的名稱或提及。

        **範例：**
        - `[p]bdset role @Birthday` - 設定角色為 @Birthday
        - `[p]bdset role Birthday` - 設定角色為 @Birthday，無需提及
        - `[p]bdset role 418058139913063657` - 根據 ID 設定角色
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None
            assert isinstance(ctx.me, discord.Member)

        # no need to check hierarchy for author, since command is locked to admins
        if ctx.me.top_role < role:
            await ctx.send(f"I can't use {role.name} because it is higher than my highest role.")
            return

        async with self.config.guild(ctx.guild).all() as conf:
            if conf["role_id"] is None:
                conf["setup_state"] += 1

            conf["role_id"] = role.id

        await ctx.send(f"角色已設定為{role.name}.")

    @bdset.command()
    async def forceset(
        self, ctx: commands.Context, user: discord.Member, *, birthday: BirthdayConverter
    ):
        """
        強制設定特定用戶的生日。

        您可以 @ 提及任何用戶或輸入他們的確切名稱。如果您輸入的名稱有空格，請確保用引號（`"`）包圍。

        **範例：**
        - `[p]bdset set @User 1-1-2000` - 將 `@User` 的生日設定為 2000年1月1日
        - `[p]bdset set User 1/1` - 將 `@User` 的生日設定為 2000年1月1日
        - `[p]bdset set "User with spaces" 1-1` - 將 `@User with spaces` 的生日設定為 1月1日
        - `[p]bdset set 354125157387344896 1/1/2000` - 將 `354125157387344896` 的生日設定為 2000年1月1日
        """
        if birthday.year != 1 and birthday.year < MIN_BDAY_YEAR:
            await ctx.send(f"I'm sorry, but I can't set a birthday to before {MIN_BDAY_YEAR}.")
            return

        if birthday > datetime.utcnow():
            await ctx.send("You can't be born in the future!")
            return

        async with self.config.member(user).birthday() as bday:
            bday["year"] = birthday.year if birthday.year != 1 else None
            bday["month"] = birthday.month
            bday["day"] = birthday.day

        if birthday.year == 1:
            str_bday = birthday.strftime("%m/%d")
        else:
            str_bday = birthday.strftime("%Y/%m/%d")

        await ctx.send(f"{user.name} 的生日已設定為 {str_bday}。")

    @bdset.command()
    async def forceremove(self, ctx: commands.Context, user: discord.Member):
        """Force-remove a user's birthday."""
        # guild only check in group
        if TYPE_CHECKING:
            assert isinstance(user, discord.Member)
            assert ctx.guild is not None

        m = await ctx.send(f"您確定嗎？`{user.name}` 的生日將被刪除。")
        start_adding_reactions(m, ReactionPredicate.YES_OR_NO_EMOJIS)
        check = ReactionPredicate.yes_or_no(m, ctx.author)  # type:ignore

        try:
            await self.bot.wait_for("reaction_add", check=check, timeout=60)
        except asyncio.TimeoutError:
            for reaction in ReactionPredicate.YES_OR_NO_EMOJIS:
                await m.remove_reaction(reaction, ctx.guild.me)
            return

        if check.result is False:
            await ctx.send("已取消。")
            return

        await self.config.member(user).birthday.set({})
        await ctx.send(f"{user.name} 的生日已被刪除。")

    @commands.is_owner()
    @bdset.command()
    async def zemigrate(self, ctx: commands.Context):
        """
        Import data from ZeCogs'/flare's fork of Birthdays cog
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None

        if await self.config.guild(ctx.guild).setup_state() != 0:
            m = await ctx.send(
                "You have already started setting the cog up. Are you sure? This will overwrite"
                " your old data for all guilds."
            )

            start_adding_reactions(m, ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = ReactionPredicate.yes_or_no(m, ctx.author)  # type:ignore
            try:
                await self.bot.wait_for("reaction_add", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("Timeout. Cancelling.")
                return

            if pred.result is False:
                await ctx.send("Cancelling.")
                return

        bday_conf = Config.get_conf(
            None,
            int(
                "402907344791714442305425963449545260864366380186701260757993729164269683092560089"
                "8581468610241444437790345710548026575313281401238342705437492295956906331"
            ),
            cog_name="Birthdays",
        )

        for guild_id, guild_data in (await bday_conf.all_guilds()).items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue
            new_data = {
                "channel_id": guild_data.get("channel", None),
                "role_id": guild_data.get("role", None),
                "message_w_year": "{mention} is now **{new_age} years old**. :tada:",
                "message_wo_year": "It's {mention}'s birthday today! :tada:",
                "time_utc_s": 0,  # UTC midnight
                "setup_state": 5,
            }
            await self.config.guild(guild).set_raw(value=new_data)

        bday_conf.init_custom("GUILD_DATE", 2)
        all_member_data = await bday_conf.custom("GUILD_DATE").all()  # type:ignore
        if "backup" in all_member_data:
            del all_member_data["backup"]

        for guild_id, guild_data in all_member_data.items():
            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue
            for day, users in guild_data.items():
                for user_id, year in users.items():
                    dt = datetime.fromordinal(int(day))

                    if year is None or year < MIN_BDAY_YEAR:
                        year = 1

                    try:
                        dt = dt.replace(year=year)
                    except (OverflowError, ValueError):  # flare's users are crazy
                        dt = dt.replace(year=1)

                    new_data = {
                        "year": dt.year if dt.year != 1 else None,
                        "month": dt.month,
                        "day": dt.day,
                    }
                    await self.config.member_from_ids(guild_id, user_id).birthday.set(new_data)

        await ctx.send(
            "All set. You can now configure the messages and time to send with other commands"
            " under `[p]bdset`, if you would like to change it from ZeLarp's. This is per-guild."
        )

    @bdset.command()
    async def rolemention(self, ctx: commands.Context, value: bool):
        """
        Choose whether or not to allow role mentions in birthday messages.

        By default role mentions are suppressed.

        To allow role mentions in the birthday message, run `[p]bdset rolemention true`.
        Disable them with `[p]bdset rolemention true`
        """
        await self.config.guild(ctx.guild).allow_role_mention.set(value)
        if value:
            await ctx.send("Role mentions have been enabled.")
        else:
            await ctx.send("Role mentions have been disabled.")

    @bdset.command()
    async def requiredrole(self, ctx: commands.Context, *, role: Union[discord.Role, None] = None):
        """
        Set a role that users must have to set their birthday.

        If users don't have this role then they can't set their
        birthday and they won't get a role or message on their birthday.

        If they set their birthday and then lose the role, their birthday
        will be stored but will be ignored until they regain the role.

        You can purge birthdays of users who no longer have the role
        with `[p]bdset requiredrolepurge`.

        If no role is provided, the requirement is removed.

        View the current role with `[p]bdset settings`.

        **Example:**
        - `[p]bdset requiredrole @Subscribers` - set the required role to @Subscribers
        - `[p]bdset requiredrole Subscribers` - set the required role to @Subscribers
        - `[p]bdset requiredrole` - remove the required role
        """
        if role is None:
            current_role = await self.config.guild(ctx.guild).require_role()
            if current_role:
                await self.config.guild(ctx.guild).require_role.clear()
                await ctx.send(
                    "The required role has been removed. Birthdays can be set by anyone and will "
                    "always be announced."
                )
            else:
                await ctx.send(
                    "No role is current set. Birthdays can be set by anyone and will always be "
                    "announced."
                )
                await ctx.send_help()
        else:
            await self.config.guild(ctx.guild).require_role.set(role.id)
            await ctx.send(
                f"The required role has been set to {role.name}. Users without this role no longer"
                " have their birthday announced."
            )

    @bdset.command(name="requiredrolepurge")
    async def requiredrole_purge(self, ctx: commands.Context):
        """Remove birthdays from the database for users who no longer have the required role.

        If you have a required role set, this will remove birthdays for users who no longer have it

        Uses without the role are temporarily ignored until they regain the role.

        This command allows you to presently remove their birthday data from the database.
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None

        required_role: int | Literal[False] = await self.config.guild(ctx.guild).require_role()
        if not required_role:
            await ctx.send(
                "You don't have a required role set. This command is only useful if you have a"
                " required role set."
            )
            return

        role = ctx.guild.get_role(required_role)
        if role is None:
            await ctx.send(
                "The required role has been deleted. This command is only useful if you have a"
                " required role set."
            )
            return

        all_members = await self.config.all_members(ctx.guild)
        purged = 0
        for member_id, member_data in all_members.items():
            member = ctx.guild.get_member(member_id)
            if member is None:
                continue

            if role not in member.roles:
                await self.config.member_from_ids(ctx.guild.id, member_id).birthday.clear()
                purged += 1

        await ctx.send(f"Purged {purged} users from the database.")

    @bdset.command()
    async def stop(self, ctx: commands.Context):
        """
        Stop the cog from sending birthday messages and giving roles in the server.
        """
        # group has guild check
        if TYPE_CHECKING:
            assert ctx.guild is not None

        confirm = await wait_for_yes_no(
            ctx, "Are you sure you want to stop sending updates and giving roles?"
        )
        if confirm is False:
            await ctx.send("Okay, nothing's changed.")
            return

        await self.config.guild(ctx.guild).clear()

        confirm = await wait_for_yes_no(
            ctx,
            "I've deleted your configuration. Would you also like to delete the data about when"
            " users birthdays are?",
        )
        if confirm is False:
            await ctx.send("I'll keep that.")
            return

        await self.config.clear_all_members(ctx.guild)
        await ctx.send("Deleted.")
