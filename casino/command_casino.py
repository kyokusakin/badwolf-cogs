import discord
import random
from redbot.core import commands, Config
from redbot.core.bot import Red

class CasinoCommands(commands.Cog):
    """賭場輔助指令：查詢籌碼與轉移籌碼"""

    def __init__(self, bot: Red, casino_cog):
        self.bot = bot
        self.casino = casino_cog

    @commands.command(name="balance", aliases=["餘額", "查詢餘額", "狗幣", "籌碼"])
    async def balance(self, ctx: commands.Context, user: discord.Member = None):
        """查看你的或他人的籌碼數量。"""
        user = user or ctx.author
        balance = await self.casino.get_balance(user)
        await ctx.send(f"{user.display_name} 擁有 💰 {balance} 籌碼。\n -# 感謝您使用狗窩中央銀行服務")

    @commands.command(name="transfer", aliases=["轉移", "轉帳"])
    async def transfer(self, ctx: commands.Context, member: discord.Member, amount: int):
        """轉移籌碼給其他使用者。"""
        if member.id == ctx.author.id:
            await ctx.send("你不能轉移籌碼給自己。")
            return
        if amount <= 0:
            await ctx.send("轉移金額必須大於零。")
            return

        sender_balance = await self.casino.get_balance(ctx.author)
        if sender_balance < amount:
            await ctx.send("你的籌碼不足以轉移。")
            return

        await self.casino.update_balance(ctx.author, -amount)
        await self.casino.update_balance(member, amount)
        await ctx.send(f"✅ 已成功轉移 💰 {amount} 籌碼給 {member.display_name}。 \n -# 感謝您使用狗窩中央銀行服務")
    
    @commands.cooldown(1, 3600, commands.BucketType.user)
    @commands.command(name="work", aliases=["工作","打工"])
    async def work(self, ctx: commands.Context):
        """工作賺取籌碼，每小時可執行一次。"""
        base_income = 1000
        random_income = random.randint(100, 1000)
        total_income = base_income + random_income
        await self.casino.update_balance(ctx.author, total_income)
        await ctx.send(f"你工作賺取了 💰 {total_income} 籌碼！")

    @work.error
    async def work_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            seconds = int(error.retry_after)
            minutes = seconds // 60
            remaining = f"{minutes} 分鐘" if minutes > 0 else f"{seconds} 秒"
            await ctx.send(f"你已經工作過了，請在 {remaining} 後再試。")
        else:
            raise error