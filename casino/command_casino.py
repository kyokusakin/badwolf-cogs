import discord
import random
import time
from redbot.core import commands, Config, data_manager
from redbot.core.bot import Red
import logging

from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame

log = logging.getLogger("red.BadwolfCogs.casino.commands")

class CasinoCommands():
    """賭場輔助指令：查詢籌碼與轉移籌碼"""

    def __init__(self, bot: Red, casino_cog):
        self.bot = bot
        self.casino = casino_cog

    @commands.command(name="balance", aliases=["餘額", "查詢餘額", "狗幣", "籌碼"])
    async def balance(self, ctx: commands.Context, user: discord.Member = None):
        """查看你的或他人的籌碼數量。"""
        user = user or ctx.author
        balance = await self.casino.get_balance(user)

        interface = (
            f"> 🏦 **狗窩中央銀行**\n"
            "> ──────────────────\n"
            f"> **👤 玩家**：`{user.display_name}`\n"
            f"> **💰 餘額**：**{int(balance):,}** 狗幣\n"
            "> ──────────────────\n"
            "> **🔁 轉帳**：`>transfer @用戶 <數量>`\n"
            "> ──────────────────\n"
            "> 如需查看更多指令，輸入 `>help Casino`"
        )
        await ctx.reply(interface)

    @commands.command(name="transfer", aliases=["轉移", "轉帳"])
    async def transfer(self, ctx: commands.Context, member: discord.Member, amount: int):
        """轉移籌碼給其他使用者。"""
        if member.id == ctx.author.id:
            await ctx.send("你不能轉移給自己。")
            return
        if amount <= 0:
            await ctx.send("轉移金額必須大於零。")
            return

        sender_balance = await self.casino.get_balance(ctx.author)
        if sender_balance < amount:
            await ctx.send("你的狗幣不足。")
            return

        # 執行轉帳
        await self.casino.update_balance(ctx.author, -amount)
        await self.casino.update_balance(member, amount)

        new_balance = await self.casino.get_balance(ctx.author)
        interface = (
            f"> 🏦 **狗窩中央銀行**\n"
            "> ──────────────────\n"
            f"> ✅ 成功轉移 💰 **{amount:,}** 給 {member.display_name}\n"
            "> ──────────────────\n"
            f"> **👤 玩家**：`{ctx.author.display_name}`\n"
            f"> **💰 餘額**：**{int(new_balance):,}** 狗幣\n"
            "> ──────────────────\n"
            "> **🔁 轉帳**：`>transfer @用戶 <數量>`\n"
            "> ──────────────────\n"
            "> 如需查看更多指令，輸入 `>help Casino`"
        )
        await ctx.reply(interface)
    
    @commands.command(name="work", aliases=["工作", "打工"])
    async def work(self, ctx: commands.Context):
        """工作賺取籌碼，每小時可執行一次。"""
        user_id = ctx.author.id
        command_name = "work"

        # 檢查冷卻
        expires_at = await self.stats_db.get_cooldown(user_id, command_name)
        if expires_at:
            remaining = expires_at - time.time()
            if remaining > 0:
                seconds = int(remaining)
                minutes = seconds // 60
                remaining_str = f"{minutes} 分鐘" if minutes > 0 else f"{seconds} 秒"
                await ctx.reply(f"你已經工作過了，請在 {remaining_str} 後再試。")
                return

        # 執行工作邏輯
        base_income = 1000
        random_income = random.randint(100, 1000)
        total_income = base_income + random_income
        await self.casino.update_balance(ctx.author, total_income)
        await ctx.reply(f"你工作賺取了 💰 {total_income:,} 狗幣！")

        # 設置冷卻
        await self.casino.stats_db.set_cooldown(user_id, command_name, 3600, commands.BucketType.user)

    @commands.command(name="dogmeat", aliases=["賣狗肉", "賣狗哥"])
    async def dogmeat(self, ctx: commands.Context):
        """賣狗肉賺取籌碼，每天可執行一次。"""
        user_id = ctx.author.id
        command_name = "dogmeat"
        
        # 檢查冷卻
        expires_at = await self.casino.stats_db.get_cooldown(user_id, command_name)
        if expires_at:
            remaining = expires_at - time.time()
            if remaining > 0:
                seconds = int(remaining)
                minutes = seconds // 60
                remaining_str = f"{minutes} 分鐘" if minutes > 0 else f"{seconds} 秒"
                await ctx.reply(f"你已經工作過了，請在 {remaining_str} 後再試。")
                return

        # 執行賣狗肉邏輯
        base_income = 8000
        random_income = random.randint(500, 10000)
        total_income = base_income + random_income
        await self.casino.update_balance(ctx.author, total_income)
        await ctx.reply(f"賣狗哥賺取了 💰 {total_income:,} 狗幣！")

        # 設置冷卻
        await self.casino.stats_db.set_cooldown(user_id, command_name, 86400, commands.BucketType.user)


    @commands.guild_only()
    @commands.command(name="blackjack", aliases=["21點", "二十一點"])
    async def blackjack(self, ctx: commands.Context, bet: int = None):
        """21 點。使令[p]blackjack <下注金額>"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_blackjack_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        try:
            game = BlackjackGame(ctx, self, bet)
            self.active_blackjack_games[ctx.author.id] = game
            await game.start()
        except Exception as e:
            log.error(f"啟動 21 點遊戲時發生錯誤：{e}", exc_info=True)
            await ctx.send("啟動 21 點遊戲時發生錯誤，請稍後再試。")

    @commands.guild_only()
    @commands.command(name="guesssize", aliases=["猜大小", "骰寶"])
    async def guesssize(self, ctx: commands.Context, bet: int = None):
        """猜大小。 使令[p]guesssize <下注金額>"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_guesssize_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        try:
            game = GuessGame(ctx, self, bet)
            self.active_guesssize_games[ctx.author.id] = game
            await game.start()
        except Exception as e:
            log.error(f"啟動 猜大小 遊戲時發生錯誤：{e}", exc_info=True)
            await ctx.send("啟動 猜大小 遊戲時發生錯誤，請稍後再試。")

    @commands.guild_only()
    @commands.command(name="slots")
    async def slots(self, ctx: commands.Context, bet: int = None):
        """拉霸 未完工"""
        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成該遊戲。")
            return
        if bet is None:
            bet = self.default_slots_bet
        if bet <= 0:
            await ctx.send("下注金額必須大於零。")
            return
        balance = await self.get_balance(ctx.author)
        if bet > balance:
            await ctx.send("你的餘額不足。")
            return

        try:
            game = SlotGame(ctx, self, bet)
            self.active_slots_games[ctx.author.id] = game
            await game.start()
        except Exception as e:
            log.error(f"啟動 拉霸 遊戲時發生錯誤：{e}", exc_info=True)
            await ctx.send("啟動 拉霸 遊戲時發生錯誤，請稍後再試。")

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="casinochan")
    async def casinochan(self, ctx: commands.Context):
        """設定允許使用 on_message 賭場的頻道。"""
        pass

    @casinochan.command(name="add")
    async def casinochan_add(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = self.config.guild(ctx.guild)
        allowed = await cfg.allowed_channels()
        if channel.id in allowed:
            await ctx.send(f"{channel.mention} 已經是允許頻道。")
        else:
            allowed.append(channel.id)
            await cfg.allowed_channels.set(allowed)
            await ctx.send(f"✅ 已新增 {channel.mention} 為賭場頻道。")

    @casinochan.command(name="remove")
    async def casinochan_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        cfg = self.config.guild(ctx.guild)
        allowed = await cfg.allowed_channels()
        if channel.id not in allowed:
            await ctx.send(f"{channel.mention} 並不在允許清單中。")
        else:
            allowed.remove(channel.id)
            await cfg.allowed_channels.set(allowed)
            await ctx.send(f"✅ 已移除 {channel.mention}。")

    @casinochan.command(name="list")
    async def casinochan_list(self, ctx: commands.Context):
        allowed = await self.config.guild(ctx.guild).allowed_channels()
        if not allowed:
            await ctx.send("目前尚未設定任何允許的頻道。")
            return
        mentions = [f"<#{cid}>" for cid in allowed]
        await ctx.send("🎰 允許的賭場頻道如下：\n" + "\n".join(mentions))

    @commands.command(name="mystats")
    async def mystats(self, ctx):
        """查詢你的賭場統計數據"""
        data = await self.stats_db.get_stats(ctx.author.id)
        
        embed = discord.Embed(
            title=f"📊 {ctx.author.display_name} 的賭場統計",
            color=0x00ff00
        )
        
        # 總體統計
        if data["total"]:
            embed.add_field(
                name="🎰 總體統計",
                value=(
                    f"• 總下注: {data['total']['bet']} 💵\n"
                    f"• 總遊戲: {data['total']['games']} 🎲\n"
                    f"• 勝利次數: {data['total']['wins']} ✅\n"
                    f"• 失敗次數: {data['total']['losses']} ❌\n"
                    f"• 總盈虧: {data['total']['profit']} 💰"
                ),
                inline=False
            )
        
        # 各遊戲統計
        for game_type, stats in data["games"].items():
            embed.add_field(
                name=f"🎮 {game_type.capitalize()}",
                value=(
                    f"下注: {stats['bet']}\n"
                    f"遊戲數: {stats['games']}\n"
                    f"勝利: {stats['wins']}\n"
                    f"失敗: {stats['losses']}\n"
                    f"盈虧: {stats['profit']}"
                )
            )
        
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="stats", aliases=["統計"])
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def show_stats_menu(self, ctx: commands.Context):
        """顯示賭場統計與排行榜選單。"""
        embed = discord.Embed(
            title="📊 賭場統計與排行榜",
            description="請選擇您想查看的統計資訊：",
            color=discord.Color.blue()
        )
        # 傳入主 Cog 的實例和使用者，以便 View 可以存取統計數據和餘額
        view = StatsMenuView(self.casino, ctx.author)
        await ctx.reply(embed=embed, view=view, mention_author=False)

    @commands.is_owner()
    @commands.command(name="setbalance", aliases=["設定餘額"])
    async def set_balance(self, ctx: commands.Context, user: discord.Member, amount: int):
        """設定使用者的餘額。"""
        if amount < 0:
            await ctx.send("餘額不能為負數。")
            return

        # 更新使用者的餘額
        await self.casino.set_balance(user, amount)

        # 獲取更新後的餘額
        new_balance = await self.casino.get_balance(user)

        await ctx.send(f"已將 {user.display_name} 的餘額設置為 {new_balance:,} 狗幣。")

######################################################
# 賭場統計選單
######################################################

class StatsMenuView(discord.ui.View):
    def __init__(self, casino_cog, author: discord.User):
        super().__init__(timeout=60)
        self.casino = casino_cog
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """檢查是否為指令發布者在互動。"""
        if interaction.user != self.author:
            await interaction.response.send_message("這不是你的選單！", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """選單超時時停用按鈕。"""
        for item in self.children:
            item.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=None)
        except discord.HTTPException:
            pass


    @discord.ui.button(label="總資產排行榜", style=discord.ButtonStyle.green, custom_id="top_assets_leaderboard")
    async def total_assets_leaderboard_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按鈕：顯示總資產 (餘額) 排行榜前 20 名。"""
        await interaction.response.defer(ephemeral=True)
    
        # 從資料庫獲取總資產排行榜，這裡使用了直接查詢的方式
        async with self.casino.stats_db.connection.cursor() as cursor:
            await cursor.execute('''
                SELECT user_id, balance FROM balances
                ORDER BY balance DESC
                LIMIT 20
            ''')
            top_users_data = await cursor.fetchall()
    
        embed = discord.Embed(
            title="💰 賭場總資產排行榜 (前20名)",
            color=discord.Color.green()
        )
    
        if not top_users_data:
            embed.description = "目前沒有總資產排行榜數據。"
        else:
            leaderboard_entries = []
            for i, (user_id, balance) in enumerate(top_users_data):
                try:
                    user = await self.casino.bot.fetch_user(user_id)
                    display_name = user.display_name
                except discord.NotFound:
                    display_name = f"未知用戶 ({user_id})"
                except discord.HTTPException:
                    display_name = f"用戶ID: {user_id}"
    
                leaderboard_entries.append(f"**#{i+1}.** {display_name}: **{int(balance):,}** 狗幣")
    
            embed.description = "\n".join(leaderboard_entries)
    
        await interaction.followup.send(embed=embed, ephemeral=True)



    @discord.ui.button(label="總盈虧排行榜", style=discord.ButtonStyle.blurple, custom_id="top_profit_leaderboard")
    async def total_profit_leaderboard_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按鈕：顯示總盈虧排行榜前 20 名。"""
        await interaction.response.defer(ephemeral=True)

        top_users_data = await self.casino.stats_db.get_top_users_by_profit(limit=20)

        embed = discord.Embed(
            title="📈 賭場總盈虧排行榜 (前 20名)",
            color=discord.Color.blurple()
        )

        if not top_users_data:
            embed.description = "目前沒有總盈虧排行榜數據。"
        else:
            leaderboard_entries = []
            for i, (user_id, total_profit) in enumerate(top_users_data):
                try:
                    user = await self.casino.bot.fetch_user(user_id)
                    display_name = user.display_name
                except discord.NotFound:
                    display_name = f"未知用戶 ({user_id})"
                except discord.HTTPException:
                    display_name = f"用戶ID: {user_id}"

                leaderboard_entries.append(f"**#{i+1}.** {display_name}: **{total_profit:+,}** 狗幣")

            embed.description = "\n".join(leaderboard_entries)

        await interaction.followup.send(embed=embed, ephemeral=True)


    @discord.ui.button(label="各遊戲統計", style=discord.ButtonStyle.red, custom_id="game_stats")
    async def game_stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """按鈕：顯示使用者的各遊戲統計。"""
        await interaction.response.defer(ephemeral=True)
        stats = await self.casino.stats_db.get_stats(self.author.id)

        embed = discord.Embed(
            title=f"🎮 {self.author.display_name} 的各遊戲統計",
            color=0x00ff00
        )

        # 檢查 stats 是否包含 games 鍵且不為空
        if not stats or not stats.get("games"):
             embed.description = "目前沒有遊戲統計數據。"
        else:
            for game_type, game_stats in stats["games"].items():
                bet = game_stats.get("bet", 0)
                games_played = game_stats.get("games", 0)
                wins = game_stats.get("wins", 0)
                losses = game_stats.get("losses", 0)
                profit = game_stats.get("profit", 0)

                embed.add_field(
                    name=f"🎲 {game_type.capitalize()}",
                    value=(f"• 下注: {bet:,}\n"
                           f"• 遊戲數: {games_played:,}\n"
                           f"• 勝利: {wins:,}\n"
                           f"• 失敗: {losses:,}\n"
                           f"• 盈虧: {profit:,}"),
                    inline=True
                )

        await interaction.followup.send(embed=embed, ephemeral=True)