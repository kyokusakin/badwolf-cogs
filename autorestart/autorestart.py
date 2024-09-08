from redbot.core import commands
import asyncio

class AutoRestart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop_task = self.bot.loop.create_task(self.monitor_bot())

    async def monitor_bot(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if self.bot.latency > 10:
                    print(f"Latency too high ({self.bot.latency}s), shutting down bot...")
                    await self.bot.close()
                await asyncio.sleep(60)
            except Exception as e:
                print(f"Error in monitor_bot: {e}")
                await asyncio.sleep(60)

    def cog_unload(self):
        self.loop_task.cancel()
        try:
            self.bot.loop.run_until_complete(self.loop_task)
        except asyncio.CancelledError:
            pass

    @commands.is_owner()  # 確保只有機器人擁有者可以使用此指令
    @commands.command()
    async def test_restart(self, ctx):
        """測試指令，用於手動觸發重啟機制"""
        await ctx.send("測試指令執行中，將會關閉機器人...")
        try:
            await self.bot.close()  # 關閉機器人
        except Exception as e:
            await ctx.send(f"關閉機器人時發生錯誤: {e}")

def setup(bot):
    bot.add_cog(AutoRestart(bot))
