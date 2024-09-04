from .autorestart import AutoRestart
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(AutoRestart(bot))
