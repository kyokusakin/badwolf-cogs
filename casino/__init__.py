from .casino import casino
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(casino(bot))
