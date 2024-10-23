import datetime
from typing import TYPE_CHECKING
from dateutil.parser import ParserError, parse
from redbot.core.commands import BadArgument, Context, Converter
import pytz  # 導入 pytz

from .vexutils import get_vex_logger

log = get_vex_logger(__name__)

# 設定台北時區
UTC8 = pytz.timezone("Asia/Taipei")

if TYPE_CHECKING:
    BirthdayConverter = datetime.datetime
    TimeConverter = datetime.datetime
else:
    class BirthdayConverter(Converter):
        async def convert(self, ctx: Context, argument: str) -> datetime.datetime:
            log.trace("嘗試解析日期 %s", argument)
            try:
                default = datetime.datetime(year=1, month=1, day=1)
                out = parse(argument, default=default, ignoretz=True).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                # 將解析的日期轉換為 UTC+8
                out = UTC8.localize(out)
                log.trace("解析的日期: %s", argument)
                return out
            except ParserError:
                if ctx.interaction:
                    raise BadArgument("那不是有效的日期。例子：`1 Jan` 或 `1 Jan 2000`。")
                raise BadArgument(
                    f"那不是有效的日期。請參見 {ctx.clean_prefix}help"
                    f" {ctx.command.qualified_name} 獲取更多信息。"
                )

    class TimeConverter(Converter):
        async def convert(self, ctx: Context, argument: str) -> datetime.datetime:
            log.trace("嘗試解析時間 %s", argument)
            try:
                out = parse(argument, ignoretz=True).replace(
                    year=1, month=1, day=1, minute=0, second=0, microsecond=0
                )
                # 將解析的時間轉換為 UTC+8
                out = UTC8.localize(out)
                log.trace("解析的時間: %s", argument)
                return out
            except ParserError:
                if ctx.interaction:
                    raise BadArgument("那不是有效的時間。")
                raise BadArgument(
                    f"那不是有效的時間。請參見 {ctx.clean_prefix}help"
                    f" {ctx.command.qualified_name} 獲取更多信息。"
                )
