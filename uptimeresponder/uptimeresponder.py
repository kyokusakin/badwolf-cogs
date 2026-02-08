from __future__ import annotations
import os
import asyncio
from datetime import datetime, timezone
from typing import Optional
from jinja2 import Environment, FileSystemLoader
from ipaddress import ip_network, ip_address

from aiohttp import web
from aiohttp.web_exceptions import HTTPBadRequest, HTTPInternalServerError

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

from .vexutils import format_help, format_info, get_vex_logger

log = get_vex_logger(__name__)

class UptimeResponder(commands.Cog):
    __version__ = "2.0.0"
    __author__ = "@vexingvexed, @badwolf_tw"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=418078199982063626, force_registration=True)
        self.config.register_global(port=8710, allowed_ips=['127.0.0.1', '::1'])
        self.app = web.Application()
        self.runner = None
        self._setup_file_paths()
        self.env = Environment(loader=FileSystemLoader(self.templates_dir))

    def _setup_file_paths(self):
        """Initialize paths for static and template directories."""
        self.cog_dir = os.path.dirname(os.path.abspath(__file__))
        self.static_dir = os.path.join(self.cog_dir, 'static')
        self.templates_dir = os.path.join(self.cog_dir, 'templates')

    async def cog_load(self):
        await self.start_webserver()

    async def cog_unload(self):
        await self.shutdown_webserver()

    def format_help_for_context(self, ctx: commands.Context) -> str:
        return format_help(self, ctx)

    @commands.command(hidden=True)
    async def uptimeresponderinfo(self, ctx: commands.Context):
        """Display the cog's information."""
        await ctx.send(await format_info(ctx, self.qualified_name, self.__version__))

    async def shutdown_webserver(self):
        """Shut down the web server if it is currently running."""
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            log.info("Web server for UptimeResponder has been stopped due to cog unload.")

    async def get_status(self, request: web.Request) -> web.Response:
        """Return the current bot status as a JSON response."""
        status = {
            'latency': f"{self.get_latency():.2f}",
            'uptime': self.get_uptime_string(),
        }
        return web.json_response(status)

    async def main_page(self, request: web.Request) -> web.Response:
        """Render and return the main status page."""
        name = self.bot.user.name if self.bot.user else "Unknown"
        html_content = self.render_template('uptime_page.html', name=name)
        return web.Response(text=html_content, content_type='text/html', status=200)

    def get_uptime_string(self) -> str:
        """Calculate and return the bot's uptime as a formatted string."""
        now = datetime.now(timezone.utc)
        uptime = now - self.bot.uptime.replace(tzinfo=timezone.utc)
        return str(int(uptime.total_seconds()))

    def get_latency(self) -> float:
        """Get the current WebSocket latency in milliseconds."""
        return self.bot.latency * 1000

    def render_template(self, template_name: str, **context) -> str:
        """Render a Jinja2 template with the provided context."""
        return self.env.get_template(template_name).render(**context)

    async def static_file_handler(self, request: web.Request) -> web.Response:
        """Serve static files from the static directory."""
        filename = request.match_info['filename']
        file_path = os.path.join(self.static_dir, filename)
        if not file_path.startswith(self.static_dir):
            raise web.HTTPForbidden()
        if not os.path.isfile(file_path):
            # Try to serve files with .txt or .html extensions if the base filename is not found.
            for ext in ['txt', 'html']:
                alt_path = os.path.join(self.static_dir, f"{filename}.{ext}")
                if os.path.isfile(alt_path):
                    return web.FileResponse(alt_path)
            raise web.HTTPNotFound()
        return web.FileResponse(file_path)

    async def start_webserver(self, port: Optional[int] = None):
        """
        Start the web server on the specified port or the default port.
        """
        await asyncio.sleep(1)
        port = port or await self.config.port()

        try:
            self._setup_routes()
            self.runner = web.AppRunner(self.app, access_log=None)
            await self.runner.setup()
            await web.TCPSite(self.runner, port=port).start()
            log.info(f"Web server for UptimeResponder has started on port {port}.")
        except OSError as e:
            # Log and raise an error if the server fails to start on the specified port
            log.error(f"Failed to start web server on port {port}: {e}")
            raise

    def _setup_routes(self):
        """Set up the routes for the web application."""
        self.app.middlewares.append(self.error_middleware)
        self.app.router.add_get("/", self.main_page)
        self.app.router.add_get("/status", self.get_status)
        self.app.router.add_route('GET', '/{filename:.*}', self.static_file_handler)
    
    @web.middleware
    async def error_middleware(self, request, handler):
        try:
            client_ip = ip_address(request.remote)
            allowed_ips = await self.config.allowed_ips()
            allowed_networks = [ip_network(ip) for ip in allowed_ips]
            if not any(client_ip in network for network in allowed_networks):
                log.warning(f"Access denied for IP: {client_ip}, path: {request.path}, method: {request.method}")
                raise web.HTTPForbidden()
            return await handler(request)
        except web.HTTPException as e:
            log.warning(f"HTTP Exception encountered: {e.status}, path: {request.path}, method: {request.method}")
            raise
        except Exception as e:
            log.error(f"Error handling request: {e}, path: {request.path}, method: {request.method}")
            raise web.HTTPBadRequest()
    
    @commands.is_owner()
    @commands.command()
    async def uptimeresponderport(self, ctx: commands.Context, port: Optional[int] = None):
        """Get or set the port for the UptimeResponder web server."""
        if port is None:
            current_port = await self.config.port()
            await ctx.send(f"The current port is {current_port}.\nTo change it, run `{ctx.clean_prefix}uptimeresponderport <port>`")
            return

        async with ctx.typing():
            await self.shutdown_webserver()
            try:
                await self.config.port.set(port)
                await self.start_webserver(port)
                await ctx.send(f"The web server has been restarted on port {port}.")
            except OSError as e:
                await ctx.send(f"Failed to start web server on port {port}: ```\n{e}```\nPlease choose a different port. No web server is running at the moment.")
    @commands.is_owner()
    @commands.command()
    async def uptimeresponderips(self, ctx: commands.Context, *ips: str):
        """Set the allowed IPs for the UptimeResponder web server."""
        if not ips:
            current_ips = await self.config.allowed_ips()
            await ctx.send(f"The current allowed IPs are: {', '.join(current_ips)}\nTo change them, run `{ctx.clean_prefix}uptimeresponderips <ip1> <ip2> ...`")
            return

        async with ctx.typing():
            valid_ips = []
            for ip in ips:
                try:
                    # Validate if the input is a valid IP or CIDR
                    ip_network(ip, strict=False)
                    valid_ips.append(ip)
                except ValueError:
                    await ctx.send(f"Invalid IP or CIDR: {ip}")
                    return

            await self.config.allowed_ips.set(valid_ips)
            await ctx.send(f"The allowed IPs have been updated to: {', '.join(valid_ips)}")