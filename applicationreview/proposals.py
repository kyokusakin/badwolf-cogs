from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from .proposal_rules import count_valid_votes
from .rules import add_calendar_month


log = logging.getLogger("red.badwolf.applicationreview")

STATUS_LABELS = {
    "voting": "投票中",
    "observing": "觀察期",
    "awaiting_confirmation": "待管理員確認",
    "passed": "通過",
    "failed": "未通過",
    "prohibited": "禁止",
}


def _deadline(record: dict) -> float:
    return record.get("observation_ends_at") or record["expires_at"]


def _time_label(value: float) -> str:
    return f"<t:{int(value)}:F>"


def proposal_embed(item: str, reason: str, record: dict) -> discord.Embed:
    approvals, oppositions = count_valid_votes(record["votes"])
    embed = discord.Embed(title=f"{record['kind']}提案")
    for name, value in (
        ("提案人", f"<@{record['proposer_id']}>"),
        ("申請項目", item),
        ("申請理由", reason),
        ("贊成票數", str(approvals)),
        ("反對票數", str(oppositions)),
        ("目前狀態", STATUS_LABELS[record["status"]]),
        ("建立時間", _time_label(record["created_at"])),
        ("投票截止時間", _time_label(_deadline(record))),
    ):
        embed.add_field(name=name, value=value, inline=False)
    return embed


class ProposalMixin:
    async def _create_proposal(
        self, ctx, item: str, reason: str, kind: str
    ) -> None:
        if ctx.guild is None:
            await ctx.send("只能在伺服器的申請頻道提交提案。")
            return
        guild_config = self.config.guild(ctx.guild)
        channel_id = await guild_config.channel_id()
        if channel_id is None or ctx.channel.id != channel_id:
            await ctx.send("請在管理員設定的申請頻道提交提案。")
            return
        item = item.strip()
        reason = reason.strip()
        if kind not in ("普通", "重大") or not item or not reason:
            await ctx.send("請填寫申請項目、申請理由，並選擇普通或重大。")
            return
        if len(item) > 1024 or len(reason) > 1024:
            await ctx.send("申請項目或理由超過 1024 個字元。")
            return
        role_id = await guild_config.get_raw("disqualified_role_id", default=None)
        if role_id is not None and any(
            role.id == role_id for role in ctx.author.roles
        ):
            await ctx.send("你目前沒有提案權。")
            return

        await ctx.defer()
        provisional_created_at = datetime.now(timezone.utc)
        provisional_record = self._new_proposal_record(
            ctx, kind, provisional_created_at
        )
        message = await ctx.channel.send(
            embed=proposal_embed(item, reason, provisional_record)
        )
        created_at = message.created_at.astimezone(timezone.utc)
        record = self._new_proposal_record(ctx, kind, created_at)
        try:
            await guild_config.set_raw("applications", str(message.id), value=record)
        except Exception:
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                log.exception("Could not remove untracked proposal %s", message.id)
            log.exception("Could not store proposal %s", message.id)
            await ctx.send("提案建立失敗，請稍後再試。")
            return

        try:
            await message.edit(embed=proposal_embed(item, reason, record))
            await guild_config.set_raw(
                "applications", str(message.id), "display_dirty", value=False
            )
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not update proposal %s; will retry", message.id)
        await ctx.send(f"提案已建立：{message.jump_url}")

    @staticmethod
    def _new_proposal_record(ctx, kind: str, created_at: datetime) -> dict:
        expires_at = add_calendar_month(created_at)
        return {
            "schema_version": 2,
            "channel_id": ctx.channel.id,
            "proposer_id": ctx.author.id,
            "kind": kind,
            "created_at": created_at.timestamp(),
            "expires_at": expires_at.timestamp(),
            "reached_at": None,
            "observation_ends_at": None,
            "resolved_at": None,
            "final_counts": None,
            "status": "voting",
            "votes": {},
            "display_dirty": True,
        }
