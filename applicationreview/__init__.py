async def setup(bot):
    from .applicationreview import ApplicationReview

    await bot.add_cog(ApplicationReview(bot))
