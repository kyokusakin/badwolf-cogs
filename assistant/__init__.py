from .assistant import OpenAIChat
from redbot.core.bot import Red

async def setup(bot: Red):
    await bot.add_cog(OpenAIChat(bot))
