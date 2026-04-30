from .fxembed import FxEmbed
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(FxEmbed(bot))