import discord
import random
import time
from datetime import datetime
from typing import List, Optional, Union
from redbot.core import commands, Config, data_manager
from redbot.core.bot import Red
import logging

from .blackjack import BlackjackGame
from .guesssize import GuessGame
from .slots import SlotGame
from .baccarat import BaccaratRoom

log = logging.getLogger("red.BadwolfCogs.casino.commands")

class CasinoCommands():
    """賭場輔助指令：查詢籌碼與轉移籌碼"""

    def __init__(self, bot: Red, casino_cog):
        self.bot = bot
        self.casino = casino_cog

    def _resolve_balance_targets(
        self, ctx: commands.Context, user: Union[discord.Member, str]
    ) -> Optional[List[discord.Member]]:
        """解析餘額操作目標：可指定單一成員或 all/全部。"""
        if isinstance(user, discord.Member):
            return [user]

        if user.strip().lower() not in {"all", "全部"}:
            return None

        return [member for member in ctx.guild.members if not member.bot]

    @commands.guild_only()
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

    @commands.is_owner()
    @commands.guild_only()
    @commands.command(name="setbalance", aliases=["設定餘額"])
    async def setbalance(self, ctx: commands.Context, user: Union[discord.Member, str], amount: int):
        """設定使用者餘額，可使用 all/全部 套用到全體。"""
        if amount < 0:
            await ctx.send("餘額不能為負數。")
            return

        targets = self._resolve_balance_targets(ctx, user)
        if targets is None:
            await ctx.send("找不到該使用者，請指定成員。")
            return
        if not targets:
            await ctx.send("目前沒有可調整餘額的成員。")
            return

        if len(targets) > 1:
            for member in targets:
                await self.casino.set_balance(member, amount)
            await ctx.send(f"已將 {len(targets):,} 位使用者的餘額設置為 {amount:,} 狗幣。")
            return

        target = targets[0]
        await self.casino.set_balance(target, amount)

        new_balance = await self.casino.get_balance(target)

        await ctx.send(f"已將 {target.display_name} 的餘額設置為 {new_balance:,} 狗幣。")

    @commands.is_owner()
    @commands.guild_only()
    @commands.command(name="addbalance", aliases=["增加餘額"])
    async def addbalance(self, ctx: commands.Context, user: Union[discord.Member, str], amount: int):
        """增加使用者餘額，可使用 all/全部 套用到全體。"""
        if amount <= 0:
            await ctx.send("增加的金額必須大於零。")
            return

        targets = self._resolve_balance_targets(ctx, user)
        if targets is None:
            await ctx.send("找不到該使用者，請指定成員或使用 `all`。")
            return
        if not targets:
            await ctx.send("目前沒有可調整餘額的成員。")
            return

        if len(targets) > 1:
            for member in targets:
                await self.casino.update_balance(member, amount)
            await ctx.send(f"已為 {len(targets):,} 位使用者增加 {amount:,} 狗幣。")
            return

        target = targets[0]
        await self.casino.update_balance(target, amount)
        new_balance = await self.casino.get_balance(target)

        await ctx.send(f"已將 {target.display_name} 的餘額增加 {amount:,} 狗幣，新的餘額為 {new_balance:,} 狗幣。")

    @commands.is_owner()
    @commands.guild_only()
    @commands.command(name="removebalance", aliases=["減少餘額"])
    async def removebalance(self, ctx: commands.Context, user: Union[discord.Member, str], amount: int):
        """減少使用者餘額，可使用 all/全部 套用到全體。"""
        if amount <= 0:
            await ctx.send("減少的金額必須大於零。")
            return

        targets = self._resolve_balance_targets(ctx, user)
        if targets is None:
            await ctx.send("找不到該使用者，請指定成員或使用 `all`。")
            return
        if not targets:
            await ctx.send("目前沒有可調整餘額的成員。")
            return

        if len(targets) > 1:
            for member in targets:
                await self.casino.update_balance(member, -amount)
            await ctx.send(f"已為 {len(targets):,} 位使用者減少 {amount:,} 狗幣。")
            return

        target = targets[0]
        await self.casino.update_balance(target, -amount)
        new_balance = await self.casino.get_balance(target)

        await ctx.send(f"已將 {target.display_name} 的餘額減少 {amount:,} 狗幣，新的餘額為 {new_balance:,} 狗幣。")

    @commands.guild_only()
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
    
    @commands.guild_only()
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
        base_income = 196
        random_income = random.randint(10, 100)
        total_income = base_income + random_income
        await self.casino.update_balance(ctx.author, total_income)
        await ctx.reply(f"你工作賺取了 💰 {total_income:,} 狗幣！")

        # 設置冷卻
        await self.casino.stats_db.set_cooldown(user_id, command_name, 3600, commands.BucketType.user)

    @commands.guild_only()
    @commands.command(name="dogmeat", aliases=["賣狗肉", "賣狗哥", "dogexe", "賣dogexe", "賣DOGEXE"])
    async def dogmeat(self, ctx: commands.Context):
        """賣 DOGEXE 賺取籌碼，每月可執行一次。"""
        user_id = ctx.author.id
        now = datetime.now()
        command_name = f"dogmeat:{now.year}-{now.month:02d}"
        
        # 檢查冷卻
        expires_at = await self.casino.stats_db.get_cooldown(user_id, command_name)
        if expires_at:
            remaining = expires_at - time.time()
            if remaining > 0:
                seconds = int(remaining)
                if seconds >= 86400:
                    days = seconds // 86400
                    hours = (seconds % 86400) // 3600
                    remaining_str = f"{days} 天 {hours} 小時"
                else:
                    minutes = seconds // 60
                    remaining_str = f"{minutes} 分鐘" if minutes > 0 else f"{seconds} 秒"
                await ctx.reply(f"你這個月已經賣過 DOGEXE 了，請在 {remaining_str} 後再試。")
                return

        base_income = 29500
        random_income = random.randint(1000, 10000)
        total_income = base_income + random_income
        await self.casino.update_balance(ctx.author, total_income)
        await ctx.reply(f"賣 DOGEXE 賺取了 💰 {total_income:,} 狗幣！")

        # 本月用過一次後，要到次月 1 號才可再次使用
        if now.month == 12:
            next_month_start = datetime(year=now.year + 1, month=1, day=1)
        else:
            next_month_start = datetime(year=now.year, month=now.month + 1, day=1)
        cooldown_seconds = max(1, int((next_month_start - now).total_seconds()))
        await self.casino.stats_db.set_cooldown(
            user_id, command_name, cooldown_seconds, commands.BucketType.user
        )
##########################################################
# 遊戲指令
##########################################################
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
    @commands.command(name="guesssize", aliases=["猜大小", "骰寶", "dice", "sicbo"])
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
        """拉霸。 使令[p]slots <下注金額>"""
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
    @commands.command(name="baccarat", aliases=["百家樂", "百家乐"])
    async def baccarat(self, ctx: commands.Context, min_bet: int = None):
        """百家樂房間。指令格式：[p]baccarat [最低下注]"""
        if not await self.is_allowed_channel(ctx.message):
            await ctx.send(
                "這個頻道尚未開放百家樂。請管理員使用 "
                f"`{ctx.clean_prefix}casinochan add #{ctx.channel.name}` 設定允許頻道。"
            )
            return

        if self.is_playing(ctx.author.id):
            await ctx.send("你已經正在進行一個遊戲，請先完成後再開房。")
            return

        if ctx.channel.id in self.active_baccarat_rooms:
            await ctx.send("本頻道已經有一桌百家樂正在進行中。")
            return

        if min_bet is None:
            min_bet = self.default_baccarat_min_bet

        if min_bet <= 0:
            await ctx.send("最低下注金額必須大於 0。")
            return
        if min_bet % BaccaratRoom.BET_GRANULARITY != 0:
            await ctx.send(f"最低下注金額必須為 {BaccaratRoom.BET_GRANULARITY:,} 的倍數。")
            return

        try:
            room = BaccaratRoom(ctx=ctx, cog=self, min_bet=min_bet)
            await room.start()
        except Exception as e:
            log.error(f"啟動 百家樂 遊戲時發生錯誤：{e}", exc_info=True)
            self.active_baccarat_rooms.pop(ctx.channel.id, None)
            self.active_baccarat_user_rooms.pop(ctx.author.id, None)
            await ctx.send("啟動 百家樂 遊戲時發生錯誤，請稍後再試。")

########################################################
# 賭場頻道設定
########################################################

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
    
######################################################
# 賭場統計選單
######################################################

    @commands.guild_only()
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
        msg = await ctx.reply(embed=embed, view=view, mention_author=False)
        view.message = msg 

#########################################################
# 賭場統計選單
#########################################################
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
                user = self.casino.bot.get_user(user_id)
                display_name = user.display_name if user else f"用戶ID: {user_id}"
    
                leaderboard_entries.append(f"**#{i+1}.** {display_name}: **{int(balance):,}** 狗幣")
    
            embed.description = "\n".join(leaderboard_entries)
    
        await interaction.message.edit(embed=embed, view=self)



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
                user = self.casino.bot.get_user(user_id)
                display_name = user.display_name if user else f"用戶ID: {user_id}"


                leaderboard_entries.append(f"**#{i+1}.** {display_name}: **{total_profit:+,}** 狗幣")

            embed.description = "\n".join(leaderboard_entries)

        await interaction.message.edit(embed=embed, view=self)


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

        await interaction.message.edit(embed=embed, view=self)
