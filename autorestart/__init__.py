from .autorestart import AutoRestart

async def setup(bot):
    cog = AutoRestart(bot)
    await cog.initialize()
    await bot.add_cog(AutoRestart(bot))
