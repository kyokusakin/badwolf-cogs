from .reaction import Reaction
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(Reaction(bot))
