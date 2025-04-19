import discord
from redbot.core import commands
import random
from typing import Union
import time

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
                ":cherries:": 2,
                ":lemon:": 4,
                ":strawberry:": 5,
                ":tangerine:": 5,
                ":grapes:": 10,
                ":watermelon:": 30,
                ":seven:": 100,
            },
            "two_same": {
                ":cherries:": 1,
                ":lemon:": 2,
                ":strawberry:": 2,
                ":tangerine:": 2,
                ":grapes:": 4,
                ":watermelon:": 8,
                ":seven:": 20,
            },
        }
        self.emoji_weights = {
            ":skull:": 18,
            ":cherries:": 35,
            ":lemon:": 25,
            ":strawberry:": 25,
            ":tangerine:": 25,
            ":grapes:": 20,
            ":watermelon:": 10,
            ":seven:": 8,
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
                  "• 每次旋轉間隔: 5 秒冷卻\n"
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
        last = self.game.last_spin_time.get(user_id, 0)
        if now - last < self.game.spin_cooldown:
            await interaction.response.send_message(
                f"⏳ 請稍後再試！冷卻時間剩 {self.game.spin_cooldown - (now - last):.1f} 秒。",
                ephemeral=True
            )
            return

        balance = await self.game.cog.get_balance(interaction.user)
        if balance < self.game.bet:
            await interaction.response.send_message(
                f"💸 籌碼不足！本次需 {self.game.bet:,}，但你只有 {balance:,}。",
                ephemeral=True
            )
            return

        # 生成結果
        self.game.last_spin_time[user_id] = now
        emojis = list(self.game.emoji_weights.keys())
        weights = list(self.game.emoji_weights.values())
        result = random.choices(emojis, weights=weights, k=3)
        rstr = " ".join(result)
        winnings = 0
        color = self.game.COLORS["lose"]
        result_text = []

        # 判斷中獎
        if result.count(":skull:") >= 2:
            # 兩骷髏或以上，沒收本注
            result_text.append("💀 **內務部查收！本次下注沒收**")
        elif result.count(result[0]) == 3:
            mul = self.game.payouts["three_same"].get(result[0], 0)
            winnings = int(self.game.bet * mul)
            color = self.game.COLORS["jackpot"]
            result_text.append(f"🎉 恭喜中大獎！獲得 {winnings:,} 籌碼")
        else:
            for e in SlotGame.EMOJIS:
                if result.count(e) == 2:
                    mul2 = self.game.payouts["two_same"].get(e, 0)
                    winnings = int(self.game.bet * mul2)
                    color = self.game.COLORS["win"]
                    result_text.append(f"🎊 部分中獎！獲得 {winnings:,} 籌碼")
                    break
            else:
                result_text.append("😢 未中獎")

        # 扣款與返還處理
        if winnings > 0:
            # 返還本注並發放獎金
            payout = self.game.bet + winnings
            await self.game.cog.update_balance(self.game.ctx.author, payout)
            self.game.total_profit += winnings
        else:
            # 未中獎或沒收本注
            await self.game.cog.update_balance(self.game.ctx.author, -self.game.bet)
            self.game.total_profit -= self.game.bet

        new_bal = await self.game.cog.get_balance(self.game.ctx.author)

        # 構建嵌入訊息
        embed = discord.Embed(
            title=f"🎰 拉霸機",
            color=color
        )
        slot_display = f"**║**  {rstr.replace(' ', '  **║**  ')}  **║**"
        embed.add_field(
            name="轉輪結果",
            value=f"\n{slot_display}\n",
            inline=False
        )
        result_info = [
            f"• 本次下注: {self.game.bet:,} 籌碼",
            f"• 獲得獎金: {winnings:,} 籌碼",
            f"• 累計盈虧: {self.game.total_profit:,} 籌碼",
            *result_text
        ]
        embed.add_field(
            name="📊 結算",
            value="\n".join(result_info),
            inline=False
        )
        embed.add_field(
            name="📈 遊戲統計",
            value=f"• 當前餘額: {new_bal:,} 籌碼",
            inline=False
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1099716093741895700/1356496158037381120/6.png")
        embed.set_footer(
            text=f"玩家 {interaction.user.display_name}",
            icon_url=interaction.user.avatar.url
        )
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
