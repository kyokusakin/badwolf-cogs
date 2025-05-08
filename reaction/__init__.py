from .reaction import reaction
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(reaction(bot))
