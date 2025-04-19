import discord
import random
import time
import aiosqlite
import os
import pathlib
from redbot.core import commands, Config, data_manager
from redbot.core.bot import Red

class CasinoCommands():
    """賭場輔助指令：查詢籌碼與轉移籌碼"""

    def __init__(self, bot: Red, casino_cog):
        self.bot = bot
        self.casino = casino_cog
        self.db_path = self._get_db_path()
        self.connection = None
        bot.loop.create_task(self.initialize_db())

    def _get_db_path(self) -> pathlib.Path:
        """建立資料夾並回傳資料庫檔案路徑"""
        base_path = data_manager.cog_data_path(raw_name="Casino")
        os.makedirs(base_path, exist_ok=True)
        return base_path / "casino.db"

    async def initialize_db(self):
        """初始化資料庫連接"""
        self.connection = await aiosqlite.connect(self.db_path)
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id INTEGER,
                command_name TEXT,
                expires_at REAL,
                bucket_type TEXT,
                PRIMARY KEY (user_id, command_name)
            )
        ''')
        await self.connection.commit()
        
    async def cog_unload(self):
        """Cog卸載時關閉資料庫連接"""
        await self.connection.close()

    async def get_cooldown(self, user_id: int, command_name: str) -> float:
        """從資料庫獲取冷卻時間"""
        async with self.connection.execute(
            "SELECT expires_at FROM cooldowns WHERE user_id = ? AND command_name = ?",
            (user_id, command_name)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                expires_at = row[0]
                current_time = time.time()
                if expires_at > current_time:
                    return expires_at
                else:
                    await self.connection.execute(
                        "DELETE FROM cooldowns WHERE user_id = ? AND command_name = ?",
                        (user_id, command_name)
                    )
                    await self.connection.commit()
        return None

    async def set_cooldown(self, user_id: int, command_name: str, duration: float, bucket_type: commands.BucketType):
        """設置冷卻時間到資料庫"""
        expires_at = time.time() + duration
        await self.connection.execute(
            "REPLACE INTO cooldowns (user_id, command_name, expires_at, bucket_type) VALUES (?, ?, ?, ?)",
            (user_id, command_name, expires_at, bucket_type.name.lower())
        )
        await self.connection.commit()

    @commands.command(name="balance", aliases=["餘額", "查詢餘額", "狗幣", "籌碼"])
    async def balance(self, ctx: commands.Context, user: discord.Member = None):
        """查看你的或他人的籌碼數量。"""
        user = user or ctx.author
        balance = await self.casino.get_balance(user)

        interface = (
            f"> 🏦 **狗窩中央銀行**\n"
            "> ──────────────────\n"
            f"> **👤 玩家**：`{user.display_name}`\n"
            f"> **💰 餘額**：**{balance:,}** 狗幣\n"
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
            f"> **💰 餘額**：**{new_balance:,}** 狗幣\n"
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
        expires_at = await self.get_cooldown(user_id, command_name)
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
        await self.set_cooldown(user_id, command_name, 3600, commands.BucketType.user)

    @commands.command(name="dogmeat", aliases=["賣狗肉", "賣狗哥"])
    async def dogmeat(self, ctx: commands.Context):
        """賣狗肉賺取籌碼，每天可執行一次。"""
        user_id = ctx.author.id
        command_name = "dogmeat"
        
        # 檢查冷卻
        expires_at = await self.get_cooldown(user_id, command_name)
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
        await self.set_cooldown(user_id, command_name, 86400, commands.BucketType.user)