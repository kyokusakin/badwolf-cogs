from .autorestart import AutoRestart

async def setup(bot):
    await bot.add_cog(AutoRestart(bot))
