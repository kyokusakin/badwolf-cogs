from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone

import discord

from .proposal_rules import (
    FINAL_STATUSES,
    add_calendar_months,
    advance_proposal,
    count_valid_votes,
)
from .proposal_view import ProposalView
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
    async def _advance_proposal(
        self, guild, message_id: str, record: dict, now: float
    ) -> dict:
        updated = advance_proposal(record, now)
        if updated != record:
            updated["display_dirty"] = True
            await self.config.guild(guild).set_raw(
                "applications", message_id, value=updated
            )
        if updated.get("display_dirty"):
            if await self._sync_proposal_message(guild, message_id, updated):
                updated["display_dirty"] = False
        return updated

    async def _sweep_proposals(self, guild, records: dict, now: float) -> None:
        async with self._proposal_lock:
            guild_config = self.config.guild(guild)
            for message_id, snapshot in list(records.items()):
                if snapshot.get("schema_version") != 2:
                    continue
                record = await guild_config.get_raw(
                    "applications", message_id, default=None
                )
                if record is None:
                    continue
                try:
                    updated = await self._advance_proposal(
                        guild, message_id, record, now
                    )
                    resolved_at = updated.get("resolved_at")
                    if updated["status"] not in FINAL_STATUSES or resolved_at is None:
                        continue
                    retention_at = add_calendar_months(
                        datetime.fromtimestamp(resolved_at, timezone.utc), 3
                    ).timestamp()
                    if now < retention_at:
                        continue
                    if updated["votes"]:
                        updated = deepcopy(updated)
                        updated["votes"] = {}
                        await guild_config.set_raw(
                            "applications", message_id, value=updated
                        )
                    if not updated.get("display_dirty"):
                        await guild_config.clear_raw("applications", message_id)
                except Exception:
                    log.exception("Could not sweep proposal %s", message_id)

    async def _handle_proposal_vote(
        self, interaction: discord.Interaction, choice: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None or interaction.message is None:
            await interaction.followup.send("找不到提案。", ephemeral=True)
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            await interaction.followup.send("提案投票目前已停用。", ephemeral=True)
            return
        message_id = str(interaction.message.id)
        guild_config = self.config.guild(guild)
        now = datetime.now(timezone.utc).timestamp()
        async with self._proposal_lock:
            record = await guild_config.get_raw(
                "applications", message_id, default=None
            )
            if (
                record is None
                or record.get("schema_version") != 2
                or interaction.channel_id != record["channel_id"]
            ):
                await interaction.followup.send("找不到提案。", ephemeral=True)
                return
            try:
                record = await self._advance_proposal(guild, message_id, record, now)
            except Exception:
                log.exception("Could not advance proposal %s", message_id)
                await interaction.followup.send("提案狀態更新失敗，請稍後再試。", ephemeral=True)
                return
            if record["status"] not in ("voting", "observing"):
                await interaction.followup.send("投票已結束。", ephemeral=True)
                return
            user = interaction.user
            if str(user.id) in record["votes"]:
                await interaction.followup.send("禁止改票", ephemeral=True)
                return
            if user.bot:
                await interaction.followup.send("機器人不得投票。", ephemeral=True)
                return
            role_id = await guild_config.get_raw(
                "disqualified_role_id", default=None
            )
            if role_id is not None and any(
                role.id == role_id for role in getattr(user, "roles", ())
            ):
                await interaction.followup.send("你目前沒有投票權。", ephemeral=True)
                return
            updated = deepcopy(record)
            updated["votes"][str(user.id)] = {"choice": choice, "valid": True}
            updated = advance_proposal(updated, now)
            updated["display_dirty"] = True
            try:
                await guild_config.set_raw("applications", message_id, value=updated)
            except Exception:
                log.exception("Could not store vote for proposal %s", message_id)
                await interaction.followup.send("投票儲存失敗，請稍後再試。", ephemeral=True)
                return
            await self._sync_proposal_message(guild, message_id, updated)
            await interaction.followup.send("已記錄投票。", ephemeral=True)

    async def _sync_proposal_message(
        self, guild, message_id: str, record: dict
    ) -> bool:
        channel = guild.get_channel(record["channel_id"])
        if channel is None:
            return False
        try:
            message = await channel.fetch_message(int(message_id))
            if not message.embeds:
                return False
            embed = message.embeds[0].copy()
            counts = record.get("final_counts")
            if counts is None:
                approvals, oppositions = count_valid_votes(record["votes"])
            else:
                approvals = counts["approvals"]
                oppositions = counts["oppositions"]
            values = {
                "贊成票數": str(approvals),
                "反對票數": str(oppositions),
                "目前狀態": STATUS_LABELS[record["status"]],
                "投票截止時間": _time_label(_deadline(record)),
            }
            for index, field in enumerate(embed.fields):
                if field.name in values:
                    embed.set_field_at(
                        index,
                        name=field.name,
                        value=values[field.name],
                        inline=field.inline,
                    )
            status = record["status"]
            view = ProposalView(
                self,
                disabled=status in FINAL_STATUSES,
                voting_closed=status == "awaiting_confirmation",
                confirm_enabled=status == "awaiting_confirmation",
            )
            await message.edit(embed=embed, view=view)
            try:
                await self.config.guild(guild).set_raw(
                    "applications", message_id, "display_dirty", value=False
                )
            except Exception:
                log.exception("Could not mark proposal %s display as current", message_id)
                return False
            return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.exception("Could not update proposal %s; will retry", message_id)
            return False

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
            embed=proposal_embed(item, reason, provisional_record),
            view=ProposalView(self),
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
