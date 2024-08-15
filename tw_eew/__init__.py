from .tw_eew import tweew
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(tweew(bot))
