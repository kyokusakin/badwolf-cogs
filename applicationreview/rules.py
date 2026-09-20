import calendar
from datetime import datetime


APPLICATION_PREFIX = "申請："
REASON_PREFIX = "理由："


def is_application_message(content: str) -> bool:
    lines = content.splitlines()
    return (
        len(lines) == 2
        and lines[0].startswith(APPLICATION_PREFIX)
        and bool(lines[0][len(APPLICATION_PREFIX) :].strip())
        and lines[1].startswith(REASON_PREFIX)
        and bool(lines[1][len(REASON_PREFIX) :].strip())
    )


def can_reject(administrator: bool, manage_channels: bool) -> bool:
    return administrator or manage_channels


def human_reaction_count(total: int, bot_reacted: bool) -> int:
    return max(0, total - int(bot_reacted))


def is_approved(approvals: int, oppositions: int) -> bool:
    return approvals > oppositions and approvals > 15


def add_calendar_month(value: datetime) -> datetime:
    year = value.year + value.month // 12
    month = value.month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
