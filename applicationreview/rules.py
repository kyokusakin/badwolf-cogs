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


def is_approved(approvals: int, oppositions: int) -> bool:
    return approvals > oppositions
