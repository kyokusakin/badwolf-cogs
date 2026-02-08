import discord
from redbot.core import commands
import random
import logging
from typing import List, Optional, Union, Dict, Any

# Setup logging
log = logging.getLogger("red.BadwolfCogs.casino.GuessGame")

# --- Payout Constants (Adjust values based on your desired rules) ---
# Standard Bets
PAYOUT_SMALL_LARGE = 1
PAYOUT_ODD_EVEN = 1

# Triples
PAYOUT_ANY_TRIPLE = 24
PAYOUT_SPECIFIC_TRIPLE = 150

# Doubles
PAYOUT_SPECIFIC_DOUBLE = 10

PAYOUT_TWO_DICE_COMBO = 6 
PAYOUT_THREE_DICE_SPECIFIC = 30
PAYOUT_STRAIGHT = 7 

class GuessGame:
    def __init__(
        self,
        ctx: Union[commands.Context, discord.Interaction],
        cog: Any,
        bet: int,
    ):
        self.ctx = ctx
        self.cog = cog
        self.bet = bet
        self.player_bet: Optional[Dict[str, Any]] = None
        self.dice_result: Optional[List[int]] = None
        self.message: Optional[discord.Message] = None
        self.view_instance: Optional[GuessView] = None
        self._finalized: bool = False

    def roll_dice(self) -> List[int]:
        """Rolls three dice and returns a sorted list."""
        return sorted([random.randint(1, 6) for _ in range(3)])

    def calculate_net_payout(self) -> int:
        """
        計算淨贏/虧損額，根據玩家下注與骰子結果。
        回傳：
            正數為贏得金額，負數為輸掉本金。
            若未下注或未擲骰，則回傳 0。
        """
        if not self.dice_result or not self.player_bet:
            log.warning(f"calculate_net_payout called with no dice ({self.dice_result}), bet ({self.player_bet}), stake ({self.bet})")
            return 0

        dice = self.dice_result
        dice_sum = sum(dice)
        counts = {i: dice.count(i) for i in range(1, 7)}
        unique_values = set(dice)
        bet_type = self.player_bet.get("type")
        number = self.player_bet.get("number")
        numbers = self.player_bet.get("numbers", [])

        is_triple = len(unique_values) == 1
        is_double = 2 in counts.values() and not is_triple
        is_specific_triple = is_triple and dice[0] == number

        win_multiplier = 0

        # --- Triple Bets ---
        if bet_type == "any_triple" and is_triple:
            win_multiplier = PAYOUT_ANY_TRIPLE
        if bet_type == "specific_triple" and is_specific_triple:
            win_multiplier = PAYOUT_SPECIFIC_TRIPLE

        # --- Standard Bets ---
        if not is_triple:
            if bet_type == "small" and 4 <= dice_sum <= 10:
                win_multiplier = PAYOUT_SMALL_LARGE
            if bet_type == "large" and 11 <= dice_sum <= 17:
                win_multiplier = PAYOUT_SMALL_LARGE
            if bet_type == "odd" and dice_sum % 2 != 0:
                win_multiplier = PAYOUT_ODD_EVEN
            if bet_type == "even" and dice_sum % 2 == 0:
                win_multiplier = PAYOUT_ODD_EVEN

        # --- Specific Double ---
        if bet_type == "specific_double" and not is_triple:
            if counts.get(number, 0) >= 2:
                win_multiplier = PAYOUT_SPECIFIC_DOUBLE

        # --- Two Dice Combo ---
        if bet_type == "two_dice_combo" and not is_triple:
            d1, d2 = numbers if len(numbers) == 2 else (None, None)
            if d1 and d2 and d1 != d2:
                if d1 in dice and d2 in dice:
                    win_multiplier = PAYOUT_TWO_DICE_COMBO
        
        # --- Specific Three Dice (Non-Triple) ---
        if bet_type == "three_dice_specific" and not is_triple:
            if sorted(dice) == sorted(numbers):
                win_multiplier = PAYOUT_THREE_DICE_SPECIFIC

        # --- Straight (e.g., 1-2-3, 4-5-6) ---
        if bet_type == "straight" and len(unique_values) == 3 and not is_triple:
            sorted_dice = sorted(dice)
            if sorted_dice[0] + 1 == sorted_dice[1] and sorted_dice[1] + 1 == sorted_dice[2]:
                win_multiplier = PAYOUT_STRAIGHT

        return self.bet * win_multiplier if win_multiplier > 0 else -self.bet

    def embed(self, title: str, desc: str, color: discord.Color = discord.Color.dark_grey()) -> discord.Embed:
        """Helper to create embeds."""
        return discord.Embed(title=title, description=desc, color=color)

    async def start(self):
        """Starts the game: checks balance, deducts bet, sends message/view."""
        balance = await self.cog.get_balance(self.ctx.author)
        if balance < self.bet:
            await self.ctx.send(f"{self.ctx.author.mention}，您的餘額不足 {self.bet}！")
            return

        try:
            await self.cog.update_balance(self.ctx.author, -self.bet)
        except Exception as e:
            log.error(f"Failed to deduct bet for {self.ctx.author.id}: {e}", exc_info=True)
            await self.ctx.send(f"下注時發生錯誤，請稍後再試。")
            return

        self._finalized = False

        embed = self.embed(
            "猜大小遊戲 (骰寶)",
            (f"{self.ctx.author.mention}，您已下注 {self.bet} 狗幣。\n"
             f"請選擇您的投注類型："),
            color=discord.Color.blue()
        )
        self.view_instance = GuessView(self) # Create and store the view
        try:
            self.message = await self.ctx.reply(embed=embed, view=self.view_instance, mention_author=False)
            self.cog.active_guesssize_games[self.ctx.author.id] = self
        except (discord.HTTPException, discord.Forbidden) as e:
            log.error(f"Failed to send game message for {self.ctx.author.id}: {e}", exc_info=True)
            await self.ctx.send("無法開始遊戲，可能是權限問題。")
            await self.cog.update_balance(self.ctx.author, self.bet)


    async def finalize(self, result_desc: str, net_payout: int):
        """
        Finalizes the game: updates balance, edits message, cleans up, and updates stats.
        net_payout: The net amount won (positive) or lost (negative).
        """
        if self._finalized:
            log.warning(f"Attempted to finalize already finished game for {self.ctx.author.id}")
            return
        self._finalized = True

        if self.view_instance:
             self.view_instance.stop()

        amount_to_return = self.bet + net_payout

        if amount_to_return > 0:
            try:
                await self.cog.update_balance(self.ctx.author, amount_to_return)
            except Exception as e:
                log.error(f"Failed to update balance on finalize for {self.ctx.author.id}: {e}", exc_info=True)
                result_desc += "\n**(餘額更新失敗)**"

        try:
            # 確保顯示的餘額是整數
            total_balance = int(await self.cog.get_balance(self.ctx.author))
        except Exception as e:
            log.error(f"Failed to get balance on finalize for {self.ctx.author.id}: {e}", exc_info=True)
            total_balance = "錯誤"

        # --- 新增的統計數據更新部分 ---
        try:
            await self.cog.stats_db.update_stats(
                self.ctx.author.id,
                'guesssize',  # 遊戲類型
                self.bet,      # 下注金額
                net_payout    # 淨盈虧
            )
            log.debug(f"Stats updated for user {self.ctx.author.id}, game 'guesssize', bet {self.bet}, profit {net_payout}")
        except Exception as e:
            log.error(f"Failed to update stats for user {self.ctx.author.id}: {e}", exc_info=True)
            result_desc += "\n**(統計更新失敗)**" # 可以選擇是否顯示給使用者
        # --- 新增部分結束 ---

        dice_faces = {1: "1⚀", 2: "2⚁", 3: "3⚂", 4: "4⚃", 5: "5⚄", 6: "6⚅"}
        dice_result_display = " ".join(dice_faces.get(die, str(die)) for die in self.dice_result) if self.dice_result else "錯誤"
        dice_sum_display = sum(self.dice_result) if self.dice_result else "N/A"

        desc = (
            "🎰 **猜大小遊戲結果 (骰寶)** 🎰\n"
            "━━━━━━━━━━━━━━━\n"
            f"🎟 **您的總投注**： {self.bet:,} 狗幣\n"
            f"🎯 **您的選擇**： {self.get_player_bet_display()}\n\n"
            f"🎲 骰子： {dice_result_display}\n"
            f"🧮 總點數： **{dice_sum_display}**\n\n"
            f"💰 **本輪淨輸贏**： {net_payout:+,}狗幣\n"
            f"💼 **剩餘狗幣**： {total_balance:,}\n\n"
            "━━━━━━━━━━━━━━━"
        )

        color = discord.Color.red()
        if net_payout > 0:
             color = discord.Color.green()
        elif net_payout == 0 :
             color = discord.Color.grey()

        # Embed 標題使用參數傳入的 result_desc，但描述使用我們自己構建的 desc
        embed = self.embed(f"🎲 {result_desc}", desc, color)

        if self.message:
            try:
                await self.message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.HTTPException) as e:
                log.warning(f"Failed to edit game message {self.message.id} on finalize: {e}")
        else:
            log.warning(f"Game for {self.ctx.author.id} finalized without a message object.")


        active_game = self.cog.active_guesssize_games.pop(self.ctx.author.id, None)
        if not active_game:
             log.warning(f"Game for {self.ctx.author.id} not found in active_guesssize_games during finalize.")

        if hasattr(self.cog, 'end_game') and callable(self.cog.end_game):
            try:
                 self.cog.end_game(self.ctx.author.id)
            except Exception as e:
                 log.error(f"Error calling cog.end_game for {self.ctx.author.id}: {e}", exc_info=True)

    def record_bet(self, bet_data: Dict[str, Any]):
        """
        Records the player's chosen bet. Assumes only one bet per game.
        bet_data: Dictionary containing 'type' and potentially 'number' or 'numbers'.
        """
        self.player_bet = bet_data
        log.debug(f"Bet recorded for {self.ctx.author.id}: {bet_data}")

    def get_player_bet_display(self) -> str:
        """Formats the player's single bet for display."""
        if not self.player_bet:
            return "尚未投注"

        bet_type = self.player_bet.get("type")
        num = self.player_bet.get("number")
        nums = self.player_bet.get("numbers")

        display_map = {
            "small": "小 (4-10)", "large": "大 (11-17)",
            "odd": "單數", "even": "雙數",
            "any_triple": "任意圍骰 (豹子)",
            "straight": "順子 (123, 234...)",
        }

        if bet_type in display_map:
             return display_map[bet_type]
        elif bet_type == "specific_triple" and num:
             return f"指定圍骰 ({num}, {num}, {num})"
        elif bet_type == "specific_double" and num:
             return f"指定對子 ({num}, {num})"
        elif bet_type == "two_dice_combo" and nums and len(nums) == 2:
             return f"兩骰組合 ({nums[0]}, {nums[1]})"
        elif bet_type == "three_dice_specific" and nums and len(nums) == 3:
             return f"指定三骰 ({nums[0]}, {nums[1]}, {nums[2]})"
        else:
             log.warning(f"Unknown bet_type for display: {bet_type}")
             return f"未知 ({bet_type})"

# =============================================================================
# User Interface Components
# =============================================================================

class GuessView(discord.ui.View):
    def __init__(self, game: GuessGame):
        super().__init__(timeout=120.0)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Checks if the user is the game owner and if the game is active."""
        if interaction.user.id != self.game.ctx.author.id:
            await interaction.response.send_message("這不是你的遊戲！", ephemeral=True)
            return False
        if self.game._finalized:
            await interaction.response.send_message("遊戲已經結束。", ephemeral=True)
            return False
        return True

    async def disable_all_buttons(self):
        """Disables all buttons on the view."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        # Update the message view
        if self.game.message:
            try:
                await self.game.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException) as e:
                log.warning(f"Failed to disable buttons on message {self.game.message.id}: {e}")

    async def handle_bet_and_finalize(self, interaction: discord.Interaction, bet_data: Dict[str, Any]):
        """Common handler for recording bet, rolling dice, and finalizing."""

        await interaction.response.defer(thinking=False, ephemeral=False)

        self.game.record_bet(bet_data)

        self.game.dice_result = self.game.roll_dice()
        net_payout = self.game.calculate_net_payout()

        if net_payout > 0:
            result_desc = f"恭喜！您淨贏得了 {net_payout} 狗幣。"
        elif net_payout == 0:
            result_desc = "打和或無效投注，退回本金。"
        else:
            result_desc = f"很抱歉，您輸掉了 {abs(net_payout)} 狗幣。"

        await self.game.finalize(result_desc, net_payout)


    # --- Button Handlers ---
    # Row 1: Standard Bets
    @discord.ui.button(label="小 (4-10)", style=discord.ButtonStyle.green, custom_id="small", row=0)
    async def small(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "small"})

    @discord.ui.button(label="大 (11-17)", style=discord.ButtonStyle.green, custom_id="large", row=0)
    async def large(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "large"})

    @discord.ui.button(label="單數", style=discord.ButtonStyle.blurple, custom_id="odd", row=0)
    async def odd(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "odd"})

    @discord.ui.button(label="雙數", style=discord.ButtonStyle.blurple, custom_id="even", row=0)
    async def even(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "even"})

    # Row 2: Triples & Doubles
    @discord.ui.button(label="任意圍骰", style=discord.ButtonStyle.red, custom_id="any_triple", row=1)
    async def any_triple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "any_triple"})

    @discord.ui.button(label="指定圍骰", style=discord.ButtonStyle.red, custom_id="specific_triple_modal", row=1)
    async def specific_triple_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DiceBetModal(
            game=self.game, view=self, bet_type_base="specific_triple",
            title="指定圍骰", label="輸入圍骰點數 (1-6)", placeholder="例如：3", requires_one_num=True
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="指定對子", style=discord.ButtonStyle.grey, custom_id="specific_double_modal", row=1)
    async def specific_double_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DiceBetModal(
            game=self.game, view=self, bet_type_base="specific_double",
            title="指定對子", label="輸入對子點數 (1-6)", placeholder="例如：4", requires_one_num=True
        )
        await interaction.response.send_modal(modal)

    # Row 3: Combinations & Others
    @discord.ui.button(label="兩骰組合", style=discord.ButtonStyle.grey, custom_id="two_dice_modal", row=2)
    async def two_dice_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DiceBetModal(
            game=self.game, view=self, bet_type_base="two_dice_combo",
            title="兩骰組合", label="輸入兩個不同骰子點數", placeholder="例如：1 5", requires_two_nums=True
        )
        await interaction.response.send_modal(modal)

    # Example "Straight" button
    @discord.ui.button(label="順子", style=discord.ButtonStyle.blurple, custom_id="straight", row=2)
    async def straight(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_and_finalize(interaction, {"type": "straight"})

    async def on_timeout(self) -> None:
        """Handles the view timing out."""
        if self.game._finalized:
            return

        log.info(f"Game view timed out for {self.game.ctx.author.id}. Refunding bet.")
        self.game._finalized = True

        await self.disable_all_buttons()

        if self.game.message:
            try:
                await self.game.message.edit(content=f"{self.game.ctx.author.mention} 的猜大小遊戲 (骰寶) 已超時，投注已取消並退款。", embed=None, view=None)
            except (discord.NotFound, discord.HTTPException) as e:
                log.warning(f"Failed to edit message {self.game.message.id} on timeout: {e}")

        active_game = self.game.cog.active_guesssize_games.pop(self.game.ctx.author.id, None)

        if active_game:
            try:
                await self.game.cog.update_balance(self.game.ctx.author, self.game.bet)
                log.info(f"Refunded {self.game.bet} to {self.game.ctx.author.id} due to timeout.")
            except Exception as e:
                log.error(f"Failed to refund bet on timeout for {self.game.ctx.author.id}: {e}", exc_info=True)

            if hasattr(self.game.cog, 'end_game') and callable(self.game.cog.end_game):
                try:
                    self.game.cog.end_game(self.game.ctx.author.id)
                except Exception as e:
                    log.error(f"Error calling cog.end_game on timeout for {self.game.ctx.author.id}: {e}", exc_info=True)
        else:
            log.warning(f"Game for {self.game.ctx.author.id} not found in active games during timeout.")


class DiceBetModal(discord.ui.Modal):
    def __init__(
        self,
        game: GuessGame,
        view: GuessView,
        bet_type_base: str,
        title: str, label: str, placeholder: str,
        requires_one_num: bool = False,
        requires_two_nums: bool = False,
        requires_three_nums: bool = False,
    ):
        super().__init__(title=title, timeout=120.0)
        self.game = game
        self.view = view
        self.bet_type_base = bet_type_base
        self.requires_one_num = requires_one_num
        self.requires_two_nums = requires_two_nums
        self.requires_three_nums = requires_three_nums

        self.input_field = discord.ui.TextInput(
            label=label, placeholder=placeholder, required=True, style=discord.TextStyle.short
        )
        self.add_item(self.input_field)

    async def on_submit(self, interaction: discord.Interaction):
        # Check game state
        if self.game._finalized:
            await interaction.response.send_message("遊戲已經結束或超時。", ephemeral=True)
            return

        value = self.input_field.value.strip()
        bet_data: Dict[str, Any] = {"type": self.bet_type_base}
        error_msg = None
        numbers = []

        try:
            raw_numbers = value.split()
            if not raw_numbers: raise ValueError("請至少輸入一個數字。")
            numbers = [int(n) for n in raw_numbers]
            if not all(1 <= n <= 6 for n in numbers):
                raise ValueError("骰子點數必須在 1 到 6 之間。")

            num_count = len(numbers)
            unique_count = len(set(numbers))

            if self.requires_one_num:
                if num_count != 1:
                    error_msg = "❌ 請只輸入一個 1 到 6 的整數。"
                else:
                    bet_data["number"] = numbers[0]
            elif self.requires_two_nums:
                if num_count != 2 or unique_count != 2:
                    error_msg = "❌ 請輸入兩個不同的 1 到 6 的整數。"
                else:
                    bet_data["numbers"] = sorted(numbers)
            elif self.requires_three_nums:
                if num_count != 3 or unique_count != 3:
                    error_msg = "❌ 請輸入三個不同的 1 到 6 的整數。"
                else:
                    bet_data["numbers"] = sorted(numbers)
            else:
                error_msg = "❌ 內部配置錯誤。"


        except ValueError as e:
            error_msg = f"❌ 輸入無效：{e}"
        except Exception as e:
            log.error(f"Unexpected error during modal input parsing: {e}", exc_info=True)
            error_msg = "❌ 處理輸入時發生未知錯誤。"


        # --- Handle Validation Result ---
        if error_msg:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        await self.view.handle_bet_and_finalize(interaction, bet_data)


    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error(f"Error in DiceBetModal processing: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("處理您的投注時發生錯誤，請稍後再試。", ephemeral=True)
        except Exception as e:
            log.error(f"Failed to send error message in Modal.on_error: {e}")

        if not self.game._finalized:
            log.warning("Finalizing game due to modal error.")
            await self.game.finalize("因內部錯誤導致遊戲中止，已退款。", -self.game.bet)


    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.game.message:
            await self.game.message.edit(view=None)

        refund = self.game.bet
        await self.game.cog.update_balance(self.game.ctx.author, refund)
        await self.game.ctx.send(
            f"{self.game.ctx.author.mention} 遊戲超時，退回下注 {refund} 狗幣。\n"
            f"目前總狗幣: {int(await self.game.cog.get_balance(self.game.ctx.author)):,}"
        )
        self.game.cog.end_game(self.game.ctx.author.id)