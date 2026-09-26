import calendar
from copy import deepcopy
from datetime import datetime


OBSERVATION_SECONDS = 3 * 24 * 60 * 60
FINAL_STATUSES = frozenset(("passed", "failed", "prohibited"))


def add_calendar_months(value: datetime, months: int) -> datetime:
    if months < 0:
        raise ValueError("Month count must be nonnegative")
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def count_valid_votes(votes: dict) -> tuple[int, int]:
    approvals = 0
    oppositions = 0
    for vote in votes.values():
        if not vote.get("valid"):
            continue
        if vote.get("choice") == "yes":
            approvals += 1
        elif vote.get("choice") == "no":
            oppositions += 1
    return approvals, oppositions


def passes_proposal(kind: str, approvals: int, oppositions: int) -> bool:
    if kind not in ("普通", "重大"):
        raise ValueError("Unknown proposal kind")
    if approvals < 20 or 3 * oppositions >= 2 * approvals:
        return False
    if kind == "重大":
        return approvals + oppositions >= 30 and 2 * oppositions <= approvals
    return True


def advance_proposal(record: dict, now: float) -> dict:
    updated = deepcopy(record)
    approvals, oppositions = count_valid_votes(updated["votes"])
    status = updated["status"]

    if status == "voting":
        if now >= updated["expires_at"]:
            updated["status"] = "failed"
        elif approvals >= 20:
            updated["status"] = "observing"
            updated["reached_at"] = now
            updated["observation_ends_at"] = now + OBSERVATION_SECONDS
    elif status == "observing" and now >= updated["observation_ends_at"]:
        if passes_proposal(updated["kind"], approvals, oppositions):
            updated["status"] = "awaiting_confirmation"
        else:
            updated["status"] = "failed"

    if updated["status"] in FINAL_STATUSES and status not in FINAL_STATUSES:
        updated["resolved_at"] = now
        updated["final_counts"] = {
            "approvals": approvals,
            "oppositions": oppositions,
        }
    return updated
