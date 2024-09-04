from redbot.core import commands
import asyncio
import os
import sys

class AutoRestart(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop_task = self.bot.loop.create_task(self.monitor_bot())

    async def monitor_bot(self):
        await self.bot.wait_until_ready()
        while True:
            if self.bot.is_closed():
                await self.bot.close()
            elif self.bot.latency > 10:
                await self.bot.close()
            await asyncio.sleep(60)


    def cog_unload(self):
        self.loop_task.cancel()
        try:
            self.bot.loop.run_until_complete(self.loop_task)
        except asyncio.CancelledError:
            pass

def setup(bot):
    bot.add_cog(AutoRestart(bot))