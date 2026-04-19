import discord
from redbot.core import commands
import random
from typing import Union
import time
import logging

log = logging.getLogger("red.BadwolfCogs.casino.slots")

class SlotGame:
    EMOJIS = [":skull:", ":cherries:", ":lemon:",":strawberry:" ,":tangerine:" , ":grapes:", ":watermelon:", ":seven:"]
    COLORS = {
        "base": discord.Color.gold(),
        "win": discord.Color.green(),
        "lose": discord.Color.red(),
        "jackpot": discord.Color.blurple()
    }

    def __init__(self, ctx: commands.Context, cog, bet: int):
        self.ctx = ctx
        self.cog = cog
        self.bet = bet
        self.message: discord.Message = None
        self.view = SlotView(self)
        self.payouts = {
            "three_same": {
                ":cherries:": 3,         # 櫻桃
                ":lemon:": 4,            # 檸檬
                ":strawberry:": 6,       # 草莓
                ":tangerine:": 6,        # 橘子
                ":grapes:": 8,           # 葡萄
                ":watermelon:": 14,      # 西瓜
                ":seven:": 56,           # 七
            },
            "two_same": {
                ":cherries:": 1,         # 櫻桃
                ":lemon:": 3,            # 檸檬
                ":strawberry:": 3,       # 草莓
                ":tangerine:": 3,        # 橘子
                ":grapes:": 4,           # 葡萄
                ":watermelon:": 7,       # 西瓜
                ":seven:": 14,           # 七
            },
        }
        self.emoji_weights = {
            ":skull:": 20,         # 骷髏，機率較高
            ":cherries:": 15,      # 櫻桃，機率較高
            ":lemon:": 12,         # 檸檬
            ":strawberry:": 12,    # 草莓
            ":tangerine:": 12,     # 橘子
            ":grapes:": 10,        # 葡萄
            ":watermelon:": 8,     # 西瓜
            ":seven:": 6,          # 七
        }
        self.last_spin_time: dict[int, float] = {}
        self.spin_cooldown = 3
        self.total_profit = 0
        self.ended = False

    async def start(self, ctx: Union[commands.Context, discord.Interaction] = None):
        if ctx:
            self.ctx = ctx
        
        embed = discord.Embed(
            title="🎰 拉 霸 遊 戲 🎰",
            color=self.COLORS["base"]
        )
        embed.add_field(
            name="🕹️ 遊戲規則",
            value=f"• 單次下注金額: **{self.bet:,}** 籌碼\n"
                  f"• 每次旋轉間隔: {self.spin_cooldown} 秒冷卻\n"
                  "• 中獎組合判定:\n"
                  "  ▸ 3個相同圖示: 獲得對應倍率\n"
                  "  ▸ 2個相同圖示: 獲得次級倍率\n"
                  "  ▸ 2個骷髏: 沒收本次下注",
            inline=False
        )
        embed.add_field(
            name="📢 操作提示",
            value="點擊下方按鈕開始遊戲！",
            inline=False
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1099716093741895700/1356496158037381120/6.png")
        embed.set_footer(text="遊戲將在 30 秒無操作後自動結束")
        
        self.message = await self.ctx.reply(embed=embed, view=self.view, mention_author=False)

class SlotView(discord.ui.View):
    def __init__(self, game: SlotGame):
        super().__init__(timeout=30)
        self.game = game
        self.spin_button = discord.ui.Button(
            label="Spin", 
            style=discord.ButtonStyle.blurple,
            emoji="🎰"
        )
        self.spin_button.callback = self.spin
        self.end_button = discord.ui.Button(
            label="結束遊戲", 
            style=discord.ButtonStyle.red,
            emoji="⏹️"
        )
        self.end_button.callback = self.end_game
        self.add_item(self.spin_button)
        self.add_item(self.end_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.game.ctx.author:
            await interaction.response.send_message("❌ 這不是你的遊戲！", ephemeral=True)
            return False
        return True

    async def spin(self, interaction: discord.Interaction):
        if self.game.ended:
            await interaction.response.send_message("⚠️ 遊戲已結束，無法再拉霸。", ephemeral=True)
            return
        user_id = interaction.user.id
        now = time.time()
        if now - self.game.last_spin_time.get(user_id, 0) < self.game.spin_cooldown:
            await interaction.response.send_message(
                f"⏳ 請稍後再試！冷卻時間剩 {self.game.spin_cooldown - (now - self.game.last_spin_time.get(user_id)):.1f} 秒。", ephemeral=True)
            return
        balance = await self.game.cog.get_balance(interaction.user)
        if balance < self.game.bet:
            await interaction.response.send_message(
                f"💸 籌碼不足！本次需 {self.game.bet:,}，但你只有 {balance:,}。", ephemeral=True)
            return
        self.game.last_spin_time[user_id] = now

        # 抽取結果
        emojis = list(self.game.emoji_weights.keys())
        weights = list(self.game.emoji_weights.values())
        result = random.choices(emojis, weights=weights, k=3)
        rstr = " ".join(result)
        winnings = 0
        color = self.game.COLORS["lose"]
        result_text = []

        if result.count(":skull:") >= 2:
            result_text.append("💀 **內務部查收！本次下注沒收**")
        elif result.count(result[0]) == 3:
            winnings = int(self.game.bet * self.game.payouts["three_same"].get(result[0], 0))
            color = self.game.COLORS["jackpot"]
            result_text.append(f"🎉 恭喜中大獎！獲得 {winnings:,} 籌碼")
        else:
            for e in self.game.EMOJIS:
                if result.count(e) == 2:
                    winnings = int(self.game.bet * self.game.payouts["two_same"].get(e, 0))
                    color = self.game.COLORS["win"]
                    result_text.append(f"🎊 部分中獎！獲得 {winnings:,} 籌碼")
                    break
            else:
                result_text.append("😢 未中獎")

        # 計算淨利並一次性更新 (winnings - bet)
        net = winnings - self.game.bet
        await self.game.cog.update_balance(self.game.ctx.author, net)
        self.game.total_profit += net

        try:
            await self.game.cog.stats_db.update_stats(user_id, 'slots', self.game.bet, net)
        except Exception as e:
            log.error(f"Failed to update stats for user {user_id}: {e}", exc_info=True)

        new_bal = int(await self.game.cog.get_balance(interaction.user))
        # 回傳嵌入
        embed = discord.Embed(title="🎰 拉霸機", color=color)
        embed.add_field(name="轉輪結果", value=f"\n**║**  {rstr.replace(' ', '  **║**  ')}  **║**\n", inline=False)
        embed.add_field(name="📊 結算", value=(
            f"• 本次下注: {self.game.bet:,} 籌碼\n"
            f"• 淨利: {net:,} 籌碼\n"
            f"• 累計盈虧: {self.game.total_profit:,} 籌碼\n"
            + "\n".join(result_text)
        ), inline=False)
        embed.add_field(name="📈 遊戲統計", value=f"• 當前餘額: {new_bal:,} 籌碼", inline=False)
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1099716093741895700/1356496158037381120/6.png")
        embed.set_footer(text=f"玩家 {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)
        self.refresh_timeout()

    def refresh_timeout(self):
        self._timeout_expiry = time.time() + self.timeout

    async def end_game(self, interaction: discord.Interaction):
        if self.game.ended:
            return
        self.game.ended = True
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=None)
        except discord.NotFound:
            pass
        final_embed = discord.Embed(
            title="🛑 遊戲結束",
            description=f"累計盈虧: **{self.game.total_profit:,}** 籌碼",
            color=self.game.COLORS["base"]
        )
        try:
            await interaction.followup.send(embed=final_embed, ephemeral=True)
        except discord.HTTPException:
            pass
        self.game.cog.end_game(self.game.ctx.author.id)
        self.stop()

    async def on_timeout(self):
        if self.game.ended:
            return
        self.game.ended = True
        for item in self.children:
            item.disabled = True
        try:
            await self.game.message.edit(view=None)
        except discord.NotFound:
            pass
        timeout_embed = discord.Embed(
            title="⏰ 遊戲超時",
            description=f"最終盈虧: **{self.game.total_profit:,}** 籌碼",
            color=self.game.COLORS["lose"]
        )
        timeout_embed.set_footer(text="由於長時間無操作，遊戲已自動結束")
        try:
            await self.game.ctx.reply(embed=timeout_embed)
        except discord.HTTPException:
            pass
        self.game.cog.end_game(self.game.ctx.author.id)
        self.stop()
