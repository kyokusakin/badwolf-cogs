from .casino import Casino
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(Casino(bot))
