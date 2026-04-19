import asyncio
import math
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import discord
from redbot.core import commands


RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]


class BaccaratState(str, Enum):
    BETTING = "BETTING"
    DEALING = "DEALING"
    ROUND_END = "ROUND_END"
    CLOSED = "CLOSED"


class BaccaratBetType(str, Enum):
    PLAYER = "PLAYER"
    BANKER = "BANKER"
    TIE = "TIE"
    PLAYER_PAIR = "PLAYER_PAIR"
    BANKER_PAIR = "BANKER_PAIR"
    ANY_PAIR = "ANY_PAIR"
    PERFECT_PAIR = "PERFECT_PAIR"


class BaccaratWinner(str, Enum):
    PLAYER = "PLAYER"
    BANKER = "BANKER"
    TIE = "TIE"


BET_TYPE_LABELS: Dict[BaccaratBetType, str] = {
    BaccaratBetType.PLAYER: "閒",
    BaccaratBetType.BANKER: "莊",
    BaccaratBetType.TIE: "和",
    BaccaratBetType.PLAYER_PAIR: "閒對",
    BaccaratBetType.BANKER_PAIR: "莊對",
    BaccaratBetType.ANY_PAIR: "任一對",
    BaccaratBetType.PERFECT_PAIR: "完美對",
}

BET_TYPE_EMOJIS: Dict[BaccaratBetType, str] = {
    BaccaratBetType.PLAYER: "👤",
    BaccaratBetType.BANKER: "🏦",
    BaccaratBetType.TIE: "⚖️",
    BaccaratBetType.PLAYER_PAIR: "🂡",
    BaccaratBetType.BANKER_PAIR: "🂢",
    BaccaratBetType.ANY_PAIR: "🎯",
    BaccaratBetType.PERFECT_PAIR: "💎",
}

SIDE_BET_PAYOUTS: Dict[BaccaratBetType, int] = {
    BaccaratBetType.PLAYER_PAIR: 11,
    BaccaratBetType.BANKER_PAIR: 11,
    BaccaratBetType.ANY_PAIR: 5,
    BaccaratBetType.PERFECT_PAIR: 25,
}


@dataclass
class BaccaratBet:
    user_id: int
    member: discord.abc.User
    display_name: str
    bet_type: BaccaratBetType
    amount: int
    placed_at: float


class BaccaratRoom:
    MAX_PLAYERS = 20
    BETTING_TIMEOUT = 60
    ROUND_END_TIMEOUT = 60
    BET_GRANULARITY = 20

    def __init__(self, ctx: commands.Context, cog, min_bet: int):
        self.ctx = ctx
        self.cog = cog
        self.channel = ctx.channel
        self.guild = ctx.guild
        self.host = ctx.author
        self.host_id = ctx.author.id
        self.channel_id = ctx.channel.id
        self.min_bet = min_bet

        self.state = BaccaratState.BETTING
        self.round_no = 1
        self.created_at = time.time()
        self.betting_deadline = self.created_at + self.BETTING_TIMEOUT

        self.shoe: List[Tuple[str, str]] = []
        self.bets: Dict[int, BaccaratBet] = {}
        self.locked_user_ids = {self.host_id}

        self.message: Optional[discord.Message] = None
        self.view: Optional[BaccaratRoomView] = None
        self.closed = False
        self._lock = asyncio.Lock()

        self.last_player_hand: List[Tuple[str, str]] = []
        self.last_banker_hand: List[Tuple[str, str]] = []
        self.last_winner: Optional[BaccaratWinner] = None
        self.last_flags: Dict[str, bool] = {}

    async def start(self):
        self.cog.active_baccarat_rooms[self.channel_id] = self
        self.cog.active_baccarat_user_rooms[self.host_id] = self.channel_id

        self._build_shoe()
        self.view = BaccaratRoomView(self, mode=BaccaratState.BETTING)
        embed = self._build_betting_embed()
        self.message = await self.ctx.reply(embed=embed, view=self.view, mention_author=False)

    def _build_shoe(self):
        self.shoe = [
            (rank, suit)
            for _ in range(8)
            for suit in SUITS
            for rank in RANKS
        ]
        random.shuffle(self.shoe)

    def _draw(self) -> Tuple[str, str]:
        if len(self.shoe) < 6:
            self._build_shoe()
        return self.shoe.pop()

    @staticmethod
    def _card_str(card: Tuple[str, str]) -> str:
        rank, suit = card
        return f"{rank}{suit}"

    @staticmethod
    def _rank_value(rank: str) -> int:
        if rank == "A":
            return 1
        if rank in {"10", "J", "Q", "K"}:
            return 0
        return int(rank)

    def _hand_total(self, hand: List[Tuple[str, str]]) -> int:
        return sum(self._rank_value(rank) for rank, _ in hand) % 10

    @staticmethod
    def _is_pair(hand: List[Tuple[str, str]]) -> bool:
        return len(hand) >= 2 and hand[0][0] == hand[1][0]

    @staticmethod
    def _is_perfect_pair(hand: List[Tuple[str, str]]) -> bool:
        return len(hand) >= 2 and hand[0][0] == hand[1][0] and hand[0][1] == hand[1][1]

    async def place_bet(
        self,
        member: discord.abc.User,
        bet_type: BaccaratBetType,
        amount: int,
    ) -> Tuple[bool, str]:
        async with self._lock:
            if self.closed or self.state != BaccaratState.BETTING:
                return False, "目前不是下注階段。"
            if amount < self.min_bet:
                return False, f"最低下注為 {self.min_bet:,} 狗幣。"
            if amount % self.BET_GRANULARITY != 0:
                return False, f"下注金額必須為 {self.BET_GRANULARITY:,} 的倍數，才能正確計算莊家 5% 佣金。"

            existing = self.bets.get(member.id)
            if existing is None and len(self.bets) >= self.MAX_PLAYERS:
                return False, "本桌已滿（最多 20 名玩家）。"

            joined_channel_id = self.cog.active_baccarat_user_rooms.get(member.id)
            if joined_channel_id is not None and joined_channel_id != self.channel_id:
                return False, "你已在其他百家樂房間中，無法同時下注。"

            if joined_channel_id is None and self.cog.is_playing(member.id):
                return False, "你正在進行其他遊戲，請先完成後再下注。"

            current_balance = await self.cog.get_balance(member)
            available = current_balance + (existing.amount if existing else 0)
            if available < amount:
                return False, f"餘額不足，需 {amount:,} 狗幣，最多可下 {available:,} 狗幣。"

            if existing:
                await self.cog.update_balance(member, existing.amount)

            await self.cog.update_balance(member, -amount)
            self.bets[member.id] = BaccaratBet(
                user_id=member.id,
                member=member,
                display_name=member.display_name,
                bet_type=bet_type,
                amount=amount,
                placed_at=time.time(),
            )

            self.locked_user_ids.add(member.id)
            self.cog.active_baccarat_user_rooms[member.id] = self.channel_id
            await self._refresh_betting_message()
            return True, f"已下注 {BET_TYPE_LABELS[bet_type]} {amount:,} 狗幣。"

    async def cancel_bet(self, member: discord.abc.User) -> Tuple[bool, str]:
        async with self._lock:
            if self.closed or self.state != BaccaratState.BETTING:
                return False, "目前不是可取消下注的階段。"
            bet = self.bets.pop(member.id, None)
            if not bet:
                return False, "你目前沒有下注。"

            await self.cog.update_balance(member, bet.amount)
            if member.id != self.host_id:
                self.locked_user_ids.discard(member.id)
                self.cog.active_baccarat_user_rooms.pop(member.id, None)
            await self._refresh_betting_message()
            return True, f"已取消下注，退回 {bet.amount:,} 狗幣。"

    async def start_dealing(self, initiated_by: Optional[discord.Interaction] = None):
        async with self._lock:
            if self.closed:
                return
            if self.state != BaccaratState.BETTING:
                if initiated_by and not initiated_by.response.is_done():
                    await initiated_by.response.send_message("目前不在可開牌狀態。", ephemeral=True)
                return
            if not self.bets:
                if initiated_by and not initiated_by.response.is_done():
                    await initiated_by.response.send_message("尚未有任何下注，無法開始。", ephemeral=True)
                return

            self.state = BaccaratState.DEALING
            if initiated_by and not initiated_by.response.is_done():
                await initiated_by.response.defer()

            if self.view:
                self.view.stop()
            if self.message:
                await self.message.edit(embed=self._build_dealing_embed(), view=None)

        await self._resolve_round()

    async def _resolve_round(self):
        async with self._lock:
            if self.closed or self.state != BaccaratState.DEALING:
                return

            player_hand, banker_hand, winner, flags = self._play_baccarat()
            self.last_player_hand = player_hand
            self.last_banker_hand = banker_hand
            self.last_winner = winner
            self.last_flags = flags

            result_lines = []
            for bet in self.bets.values():
                return_amount, net_profit = self._settle_single_bet(bet, winner, flags)
                if return_amount > 0:
                    await self.cog.update_balance(bet.member, return_amount)

                await self.cog.stats_db.update_stats(
                    bet.user_id,
                    "baccarat",
                    bet.amount,
                    net_profit,
                )

                current_balance = int(await self.cog.get_balance(bet.member))
                result_lines.append(
                    f"• {bet.display_name}｜{BET_TYPE_LABELS[bet.bet_type]} {bet.amount:,}｜"
                    f"盈虧 {net_profit:+,}｜餘額 {current_balance:,}"
                )

            self.bets.clear()
            self.state = BaccaratState.ROUND_END
            if self.view:
                self.view.stop()
            self.view = BaccaratRoomView(self, mode=BaccaratState.ROUND_END)

            if self.message:
                await self.message.edit(
                    embed=self._build_round_result_embed(player_hand, banker_hand, winner, flags, result_lines),
                    view=self.view,
                )

    def _play_baccarat(
        self,
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], BaccaratWinner, Dict[str, bool]]:
        player_hand = [self._draw(), self._draw()]
        banker_hand = [self._draw(), self._draw()]
        player_total = self._hand_total(player_hand)
        banker_total = self._hand_total(banker_hand)

        player_natural = player_total in {8, 9}
        banker_natural = banker_total in {8, 9}
        player_third_card: Optional[Tuple[str, str]] = None

        if not (player_natural or banker_natural):
            if player_total <= 5:
                player_third_card = self._draw()
                player_hand.append(player_third_card)

            banker_total = self._hand_total(banker_hand)
            if player_third_card is None:
                if banker_total <= 5:
                    banker_hand.append(self._draw())
            else:
                third_val = self._rank_value(player_third_card[0])
                if banker_total <= 2:
                    banker_hand.append(self._draw())
                elif banker_total == 3 and third_val != 8:
                    banker_hand.append(self._draw())
                elif banker_total == 4 and 2 <= third_val <= 7:
                    banker_hand.append(self._draw())
                elif banker_total == 5 and 4 <= third_val <= 7:
                    banker_hand.append(self._draw())
                elif banker_total == 6 and 6 <= third_val <= 7:
                    banker_hand.append(self._draw())

        player_total = self._hand_total(player_hand)
        banker_total = self._hand_total(banker_hand)

        if player_total > banker_total:
            winner = BaccaratWinner.PLAYER
        elif banker_total > player_total:
            winner = BaccaratWinner.BANKER
        else:
            winner = BaccaratWinner.TIE

        player_pair = self._is_pair(player_hand)
        banker_pair = self._is_pair(banker_hand)
        flags = {
            "player_pair": player_pair,
            "banker_pair": banker_pair,
            "any_pair": player_pair or banker_pair,
            "perfect_pair": self._is_perfect_pair(player_hand) or self._is_perfect_pair(banker_hand),
        }
        return player_hand, banker_hand, winner, flags

    def _settle_single_bet(
        self,
        bet: BaccaratBet,
        winner: BaccaratWinner,
        flags: Dict[str, bool],
    ) -> Tuple[int, int]:
        amount = bet.amount
        btype = bet.bet_type

        if btype == BaccaratBetType.PLAYER:
            if winner == BaccaratWinner.PLAYER:
                profit = amount
            elif winner == BaccaratWinner.TIE:
                profit = 0
            else:
                profit = -amount
        elif btype == BaccaratBetType.BANKER:
            if winner == BaccaratWinner.BANKER:
                profit = int(math.ceil(amount * 0.95))
            elif winner == BaccaratWinner.TIE:
                profit = 0
            else:
                profit = -amount
        elif btype == BaccaratBetType.TIE:
            profit = amount * 8 if winner == BaccaratWinner.TIE else -amount
        elif btype == BaccaratBetType.PLAYER_PAIR:
            profit = amount * SIDE_BET_PAYOUTS[btype] if flags["player_pair"] else -amount
        elif btype == BaccaratBetType.BANKER_PAIR:
            profit = amount * SIDE_BET_PAYOUTS[btype] if flags["banker_pair"] else -amount
        elif btype == BaccaratBetType.ANY_PAIR:
            profit = amount * SIDE_BET_PAYOUTS[btype] if flags["any_pair"] else -amount
        elif btype == BaccaratBetType.PERFECT_PAIR:
            profit = amount * SIDE_BET_PAYOUTS[btype] if flags["perfect_pair"] else -amount
        else:
            profit = -amount

        return_amount = amount + profit if profit >= 0 else 0
        return return_amount, profit

    async def on_betting_timeout(self):
        async with self._lock:
            if self.closed or self.state != BaccaratState.BETTING:
                return
            if not self.bets:
                await self._close_room_locked("下注時間到，且無有效下注，房間已關閉。", refund=False)
                return
        await self.start_dealing()

    async def on_round_end_timeout(self):
        async with self._lock:
            if self.closed or self.state != BaccaratState.ROUND_END:
                return
            await self._close_room_locked("房主逾時未操作，房間已關閉。", refund=False)

    async def next_round(self) -> Tuple[bool, str]:
        async with self._lock:
            if self.closed:
                return False, "房間已關閉。"
            if self.state != BaccaratState.ROUND_END:
                return False, "目前尚未結算，無法進入下一局。"

            for uid in list(self.locked_user_ids):
                if uid != self.host_id:
                    self.cog.active_baccarat_user_rooms.pop(uid, None)
                    self.locked_user_ids.discard(uid)

            self.bets.clear()
            self.round_no += 1
            self.state = BaccaratState.BETTING
            self.betting_deadline = time.time() + self.BETTING_TIMEOUT

            if self.view:
                self.view.stop()
            self.view = BaccaratRoomView(self, mode=BaccaratState.BETTING)
            if self.message:
                await self.message.edit(embed=self._build_betting_embed(), view=self.view)
            return True, "已進入下一局，開放下注 60 秒。"

    async def close_room(self, reason: str):
        async with self._lock:
            await self._close_room_locked(reason=reason, refund=True)

    async def _delete_message_later(self, message: discord.Message, delay_seconds: int):
        await asyncio.sleep(delay_seconds)
        try:
            await message.delete()
        except discord.HTTPException:
            pass

    async def _close_room_locked(self, reason: str, refund: bool):
        if self.closed:
            return

        self.closed = True
        self.state = BaccaratState.CLOSED

        if self.view:
            self.view.stop()

        if refund and self.bets:
            for bet in self.bets.values():
                await self.cog.update_balance(bet.member, bet.amount)

        self.bets.clear()

        for uid in list(self.locked_user_ids):
            self.cog.active_baccarat_user_rooms.pop(uid, None)
        self.locked_user_ids.clear()

        self.cog.active_baccarat_rooms.pop(self.channel_id, None)

        if self.message:
            close_notice = f"{reason}\n\n此訊息將在 10 秒後刪除。"
            close_embed = discord.Embed(
                title="🛑 百家樂房間已關閉",
                description=close_notice,
                color=discord.Color.dark_red(),
            )
            try:
                close_message = self.message
                await close_message.edit(embed=close_embed, view=None)
                self.cog.bot.loop.create_task(self._delete_message_later(close_message, 10))
            except discord.HTTPException:
                pass

    async def _refresh_betting_message(self):
        if not self.message or self.state != BaccaratState.BETTING:
            return
        try:
            await self.message.edit(embed=self._build_betting_embed(), view=self.view)
        except discord.HTTPException:
            pass

    @staticmethod
    def _join_lines_for_embed(lines: List[str], max_length: int = 1024) -> str:
        if not lines:
            return "無資料。"

        rendered: List[str] = []
        for line in lines:
            candidate = "\n".join(rendered + [line]) if rendered else line
            if len(candidate) > max_length:
                break
            rendered.append(line)

        remaining = len(lines) - len(rendered)
        if remaining <= 0:
            return "\n".join(rendered)

        suffix = f"...（尚有 {remaining} 筆）"
        candidate = "\n".join(rendered + [suffix]) if rendered else suffix
        while len(candidate) > max_length and rendered:
            rendered.pop()
            candidate = "\n".join(rendered + [suffix]) if rendered else suffix
        return candidate[:max_length]

    def _build_betting_embed(self) -> discord.Embed:
        remaining = max(0, int(self.betting_deadline - time.time()))
        embed = discord.Embed(
            title="🃏 百家樂房間",
            description=(
                f"房主：{self.host.mention}\n"
                f"回合：第 {self.round_no} 局\n"
                f"最低下注：{self.min_bet:,} 狗幣\n"
                f"狀態：下注中（{remaining} 秒）"
            ),
            color=discord.Color.blue(),
        )
        if not self.bets:
            embed.add_field(name="目前下注", value="尚無玩家下注。", inline=False)
        else:
            lines = []
            for bet in sorted(self.bets.values(), key=lambda b: b.placed_at):
                lines.append(
                    f"{BET_TYPE_EMOJIS[bet.bet_type]} {bet.display_name}｜{BET_TYPE_LABELS[bet.bet_type]}｜{bet.amount:,}"
                )
            embed.add_field(
                name=f"目前下注（{len(self.bets)}/{self.MAX_PLAYERS}）",
                value=self._join_lines_for_embed(lines),
                inline=False,
            )
        embed.set_footer(text="玩家可重複下注覆蓋舊注；房主可提前開牌。")
        return embed

    def _build_dealing_embed(self) -> discord.Embed:
        return discord.Embed(
            title="🎴 百家樂開牌中",
            description=f"第 {self.round_no} 局結算中，請稍候...",
            color=discord.Color.blurple(),
        )

    def _build_round_result_embed(
        self,
        player_hand: List[Tuple[str, str]],
        banker_hand: List[Tuple[str, str]],
        winner: BaccaratWinner,
        flags: Dict[str, bool],
        result_lines: List[str],
    ) -> discord.Embed:
        winner_label = {
            BaccaratWinner.PLAYER: "閒",
            BaccaratWinner.BANKER: "莊",
            BaccaratWinner.TIE: "和",
        }[winner]
        player_cards = " ".join(self._card_str(c) for c in player_hand)
        banker_cards = " ".join(self._card_str(c) for c in banker_hand)
        player_total = self._hand_total(player_hand)
        banker_total = self._hand_total(banker_hand)

        flags_desc = (
            f"閒對：{'是' if flags['player_pair'] else '否'}｜"
            f"莊對：{'是' if flags['banker_pair'] else '否'}｜"
            f"任一對：{'是' if flags['any_pair'] else '否'}｜"
            f"完美對：{'是' if flags['perfect_pair'] else '否'}"
        )

        embed = discord.Embed(
            title=f"📣 百家樂第 {self.round_no} 局結果",
            description=(
                f"閒牌：{player_cards}（{player_total}）\n"
                f"莊牌：{banker_cards}（{banker_total}）\n"
                f"勝方：**{winner_label}**\n"
                f"{flags_desc}"
            ),
            color=discord.Color.green(),
        )

        if result_lines:
            embed.add_field(name="玩家結算", value=self._join_lines_for_embed(result_lines), inline=False)
        embed.set_footer(text="房主可選擇下一局或結束房間（60 秒內）。")
        return embed


class BaccaratBetModal(discord.ui.Modal):
    def __init__(self, room: BaccaratRoom, bet_type: BaccaratBetType):
        super().__init__(title=f"下注：{BET_TYPE_LABELS[bet_type]}", timeout=90)
        self.room = room
        self.bet_type = bet_type
        self.amount_input = discord.ui.TextInput(
            label="下注金額",
            placeholder=f"請輸入整數，最低 {room.min_bet}，且為 {room.BET_GRANULARITY} 的倍數",
            required=True,
            style=discord.TextStyle.short,
            max_length=12,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.amount_input.value.strip()
        try:
            amount = int(raw)
        except ValueError:
            await interaction.response.send_message("請輸入有效整數。", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("下注金額必須大於 0。", ephemeral=True)
            return

        success, msg = await self.room.place_bet(interaction.user, self.bet_type, amount)
        await interaction.response.send_message(msg, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if not interaction.response.is_done():
            await interaction.response.send_message("下注處理失敗，請稍後再試。", ephemeral=True)


class BaccaratRoomView(discord.ui.View):
    def __init__(self, room: BaccaratRoom, mode: BaccaratState):
        timeout = room.BETTING_TIMEOUT if mode == BaccaratState.BETTING else room.ROUND_END_TIMEOUT
        super().__init__(timeout=timeout)
        self.room = room
        self.mode = mode

        if mode == BaccaratState.BETTING:
            self.remove_item(self.next_round)
        elif mode == BaccaratState.ROUND_END:
            self.remove_item(self.bet_player)
            self.remove_item(self.bet_banker)
            self.remove_item(self.bet_tie)
            self.remove_item(self.bet_player_pair)
            self.remove_item(self.bet_banker_pair)
            self.remove_item(self.bet_any_pair)
            self.remove_item(self.bet_perfect_pair)
            self.remove_item(self.cancel_bet)
            self.remove_item(self.start_dealing)

    async def _open_bet_modal(self, interaction: discord.Interaction, bet_type: BaccaratBetType):
        if self.room.closed:
            await interaction.response.send_message("房間已關閉。", ephemeral=True)
            return
        if self.room.state != BaccaratState.BETTING:
            await interaction.response.send_message("目前不是下注階段。", ephemeral=True)
            return
        await interaction.response.send_modal(BaccaratBetModal(self.room, bet_type))

    def _is_host(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.room.host_id

    @discord.ui.button(label="閒", style=discord.ButtonStyle.blurple, row=0)
    async def bet_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.PLAYER)

    @discord.ui.button(label="莊", style=discord.ButtonStyle.red, row=0)
    async def bet_banker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.BANKER)

    @discord.ui.button(label="和", style=discord.ButtonStyle.grey, row=0)
    async def bet_tie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.TIE)

    @discord.ui.button(label="閒對", style=discord.ButtonStyle.green, row=1)
    async def bet_player_pair(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.PLAYER_PAIR)

    @discord.ui.button(label="莊對", style=discord.ButtonStyle.green, row=1)
    async def bet_banker_pair(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.BANKER_PAIR)

    @discord.ui.button(label="任一對", style=discord.ButtonStyle.green, row=1)
    async def bet_any_pair(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.ANY_PAIR)

    @discord.ui.button(label="完美對", style=discord.ButtonStyle.green, row=1)
    async def bet_perfect_pair(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_bet_modal(interaction, BaccaratBetType.PERFECT_PAIR)

    @discord.ui.button(label="取消下注", style=discord.ButtonStyle.grey, row=2)
    async def cancel_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.room.closed:
            await interaction.response.send_message("房間已關閉。", ephemeral=True)
            return
        success, msg = await self.room.cancel_bet(interaction.user)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="開始開牌", style=discord.ButtonStyle.blurple, row=2)
    async def start_dealing(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.room.closed:
            await interaction.response.send_message("房間已關閉。", ephemeral=True)
            return
        if not self._is_host(interaction):
            await interaction.response.send_message("只有房主可以提前開牌。", ephemeral=True)
            return
        await self.room.start_dealing(initiated_by=interaction)

    @discord.ui.button(label="下一局", style=discord.ButtonStyle.green, row=3)
    async def next_round(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.room.closed:
            await interaction.response.send_message("房間已關閉。", ephemeral=True)
            return
        if self.room.state != BaccaratState.ROUND_END:
            await interaction.response.send_message("目前尚未到下一局階段。", ephemeral=True)
            return
        if not self._is_host(interaction):
            await interaction.response.send_message("只有房主可以開始下一局。", ephemeral=True)
            return
        success, msg = await self.room.next_round()
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="結束房間", style=discord.ButtonStyle.red, row=3)
    async def close_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.room.closed:
            await interaction.response.send_message("房間已關閉。", ephemeral=True)
            return
        if not self._is_host(interaction):
            await interaction.response.send_message("只有房主可以結束房間。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=False)
        await self.room.close_room("房主已手動結束房間。")
        await interaction.followup.send("房間已關閉。", ephemeral=True)

    async def on_timeout(self):
        if self.mode == BaccaratState.BETTING:
            await self.room.on_betting_timeout()
        elif self.mode == BaccaratState.ROUND_END:
            await self.room.on_round_end_timeout()
