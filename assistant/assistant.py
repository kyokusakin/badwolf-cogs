import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from typing import Optional
import openai
import base64
import urllib.parse

class OpenAIChat(commands.Cog):
    """A RedBot cog for OpenAI API integration with advanced features."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {
            "api_keys": {},
            "api_url_base": "https://api.openai.com",
            "model": "gpt-4",
        }
        default_guild = {
            "channels": {},
            "prompt": "",
        }
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

    def encode_key(self, key: str) -> str:
        return base64.b64encode(key.encode()).decode()

    def decode_key(self, encoded_key: str) -> str:
        return base64.b64decode(encoded_key.encode()).decode()

    @commands.group()
    @commands.guild_only()
    async def openai(self, ctx: commands.Context):
        """Group command for OpenAI settings."""
        pass

    @openai.command()
    async def setkey(self, ctx: commands.Context, key: str):
        """Set the OpenAI API key."""
        encoded_key = self.encode_key(key)
        async with self.config.api_keys() as keys:
            keys[str(ctx.author.id)] = encoded_key
        await ctx.send("API key has been securely stored.")

    @openai.command()
    async def seturl(self, ctx: commands.Context, url_base: str):
        """Set the API base URL for OpenAI requests."""
        parsed_url = urllib.parse.urlparse(url_base)
        if not parsed_url.scheme or not parsed_url.netloc:
            await ctx.send("Invalid URL. Please provide a valid API base URL.")
            return
        await self.config.api_url_base.set(url_base.rstrip("/"))
        await ctx.send(f"API base URL has been set to: {url_base.rstrip('/')}")

    @openai.command()
    async def setmodel(self, ctx: commands.Context, model: str):
        """Set the model for OpenAI requests."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to: {model}")

    @openai.command()
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for OpenAI responses in this guild."""
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[str(channel.id)] = {}
        await ctx.send(f"Channel {channel.mention} has been set for OpenAI responses.")

    @openai.command()
    async def setprompt(self, ctx: commands.Context, *, prompt: str):
        """Set a custom prompt for this guild."""
        await self.config.guild(ctx.guild).prompt.set(prompt)
        await ctx.send("Custom prompt has been set.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = await self.config.guild(message.guild).all()
        channels = config["channels"]

        if str(message.channel.id) not in channels:
            return

        prompt = config["prompt"]
        user_input = message.content

        if not user_input:
            return

        api_keys = await self.config.api_keys()
        api_key = api_keys.get(str(message.author.id))

        if not api_key:
            await message.channel.send("API key not set. Use `openai setkey` to set your key.")
            return

        api_key = self.decode_key(api_key)
        api_url_base = await self.config.api_url_base()
        api_url = f"{api_url_base}/v1/chat/completions"
        model = await self.config.model()

        response = await self.query_openai(api_key, api_url, model, prompt + "\n" + user_input)

        if response:
            await message.channel.send(response)

    async def query_openai(self, api_key: str, api_url: str, model: str, prompt: str) -> Optional[str]:
        openai.api_key = api_key
        openai.api_base = api_url.rsplit("/v1/chat/completions", 1)[0]

        try:
            response = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "system", "content": prompt}],
            )
            return response["choices"][0]["message"]["content"]
        except openai.error.OpenAIError as e:
            return f"Error: {e}"

    async def cog_unload(self):
        pass