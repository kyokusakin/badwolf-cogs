import asyncio
import contextlib
import io
import logging
import math
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple

import discord
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from redbot.core import Config, commands

log = logging.getLogger("red.badwolf.bot_trap")


class BotTrap(commands.Cog):
    __author__ = ["Badwolf_TW"]
    __version__ = "1.1.0"
    CAPTCHA_TIMEOUT_SECONDS = 30
    NOTICE_DELETE_SECONDS = 10
    CAPTCHA_LENGTH = 6
    CAPTCHA_CHARSET = "0123456789"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=948327150726910421, force_registration=True)
        self.config.register_guild(
            trap_channel_id=None,
            temp_ban_seconds=15,
            delete_window_seconds=3600,
            enabled=True,
        )
        self._active_traps: Set[Tuple[int, int]] = set()

    async def red_delete_data_for_user(self, **kwargs):
        return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if await self.bot.is_automod_immune(message.author):
            return
        # Follow Red bot-level privilege checks: admins/mods are immune.
        if await self.bot.is_admin(message.author) or await self.bot.is_mod(message.author):
            return

        conf = self.config.guild(message.guild)
        if not await conf.enabled():
            return

        trap_channel_id = await conf.trap_channel_id()
        if trap_channel_id is None or message.channel.id != trap_channel_id:
            return

        key = (message.guild.id, message.author.id)
        if key in self._active_traps:
            return

        self._active_traps.add(key)
        try:
            passed, captcha_prompt = await self._run_captcha_challenge(message)
            if passed:
                return
            await self._run_trap(message, captcha_prompt=captcha_prompt)
        finally:
            self._active_traps.discard(key)

    async def _run_captcha_challenge(
        self, message: discord.Message, *, delete_trigger_message: bool = True
    ) -> Tuple[bool, Optional[discord.Message]]:
        guild = message.guild
        member = message.author
        if guild is None or not isinstance(member, discord.Member):
            return False, None

        code = self._generate_captcha_code()
        image_bytes = self._build_captcha_image(code)
        file = discord.File(fp=image_bytes, filename="captcha.png")
        prompt_embed = self._build_notice_embed(
            title="圖片驗證",
            description=(
                f"{member.mention} 請在 {self.CAPTCHA_TIMEOUT_SECONDS} 秒內輸入圖片中的 "
                f"{self.CAPTCHA_LENGTH} 碼數字驗證碼。"
            ),
            color=discord.Color.gold(),
        )
        prompt_embed.set_image(url="attachment://captcha.png")

        prompt = await message.reply(
            embed=prompt_embed,
            file=file,
            mention_author=True,
        )

        def check(reply: discord.Message) -> bool:
            return (
                reply.guild is not None
                and reply.guild.id == guild.id
                and reply.channel.id == message.channel.id
                and reply.author.id == member.id
            )

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=self.CAPTCHA_TIMEOUT_SECONDS)
            user_input = reply.content.strip()
            if secrets.compare_digest(user_input, code):
                with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await reply.delete()
                if delete_trigger_message:
                    with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                        await message.delete()
                await self._send_notice(
                    message.channel,
                    self._build_notice_embed(
                        title="驗證通過",
                        description=f"{member.mention} 驗證通過。",
                        color=discord.Color.green(),
                    ),
                )
                with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await prompt.delete()
                return True, None

            await self._send_notice(
                message.channel,
                self._build_notice_embed(
                    title="驗證失敗",
                    description=f"{member.mention} 驗證碼錯誤。",
                    color=discord.Color.red(),
                ),
            )
            return False, prompt
        except asyncio.TimeoutError:
            await self._send_notice(
                message.channel,
                self._build_notice_embed(
                    title="驗證失敗",
                    description=f"{member.mention} 驗證逾時。",
                    color=discord.Color.red(),
                ),
            )
            return False, prompt

    def _generate_captcha_code(self) -> str:
        return "".join(secrets.choice(self.CAPTCHA_CHARSET) for _ in range(self.CAPTCHA_LENGTH))

    def _build_captcha_image(self, code: str) -> io.BytesIO:
        rng = random.SystemRandom()
        width, height = 320, 120
        image = Image.new("RGB", (width, height), (240, 243, 247))
        draw = ImageDraw.Draw(image)
        self._draw_captcha_background(draw, width, height, rng)
        fonts = self._get_captcha_fonts()

        glyphs = [self._build_digit_glyph(ch, fonts, rng) for ch in code]
        placements = self._place_glyphs_without_overlap(glyphs, width, height, rng)
        for glyph, (x, y) in zip(glyphs, placements):
            image.paste(glyph, (x, y), glyph)

        # Overlay a few foreground color blocks on top of digits.
        self._draw_digit_overlay_blocks(draw, width, height, rng)
        self._draw_digit_cross_lines(draw, width, height, rng)

        # Curved clutter to disrupt segmentation.
        for _ in range(5):
            amplitude = rng.randint(7, 16)
            frequency = rng.uniform(0.018, 0.045)
            phase = rng.uniform(0.0, math.tau)
            offset = rng.randint(24, height - 24)
            points = [
                (x, int(offset + amplitude * math.sin((x * frequency) + phase)))
                for x in range(0, width, 2)
            ]
            color = (rng.randint(85, 170), rng.randint(85, 170), rng.randint(85, 170))
            draw.line(points, fill=color, width=rng.randint(1, 3))

        for _ in range(20):
            left = rng.randint(-30, width - 20)
            top = rng.randint(-30, height - 20)
            right = left + rng.randint(30, 115)
            bottom = top + rng.randint(18, 75)
            color = (rng.randint(95, 190), rng.randint(95, 190), rng.randint(95, 190))
            draw.arc((left, top, right, bottom), rng.randint(0, 180), rng.randint(181, 360), fill=color, width=1)

        for _ in range(12):
            x1 = rng.randint(0, width)
            y1 = rng.randint(0, height)
            x2 = rng.randint(0, width)
            y2 = rng.randint(0, height)
            color = (rng.randint(65, 170), rng.randint(65, 170), rng.randint(65, 170))
            draw.line((x1, y1, x2, y2), fill=color, width=rng.randint(1, 2))

        for _ in range(1200):
            x = rng.randint(0, width - 1)
            y = rng.randint(0, height - 1)
            color = (rng.randint(95, 225), rng.randint(95, 225), rng.randint(95, 225))
            draw.point((x, y), fill=color)

        image = image.filter(ImageFilter.GaussianBlur(radius=0.55))
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=180, threshold=3))
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return output

    def _draw_captcha_background(self, draw: ImageDraw.ImageDraw, width: int, height: int, rng: random.SystemRandom):
        start = (rng.randint(228, 246), rng.randint(230, 246), rng.randint(228, 246))
        end = (rng.randint(202, 226), rng.randint(204, 228), rng.randint(202, 226))
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = tuple(int(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
            draw.line((0, y, width, y), fill=color)

        # Random color blocks to make segmentation harder.
        for _ in range(70):
            block_w = rng.randint(10, 42)
            block_h = rng.randint(8, 30)
            x = rng.randint(-12, width - 1)
            y = rng.randint(-12, height - 1)
            fill = (
                rng.randint(150, 245),
                rng.randint(150, 245),
                rng.randint(150, 245),
            )
            draw.rectangle((x, y, x + block_w, y + block_h), fill=fill)

        for _ in range(45):
            cx = rng.randint(-20, width + 20)
            cy = rng.randint(-20, height + 20)
            radius = rng.randint(4, 14)
            fill = (rng.randint(185, 245), rng.randint(185, 245), rng.randint(185, 245))
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=fill, width=1)

    def _random_digit_color(self, rng: random.SystemRandom) -> Tuple[int, int, int]:
        palette = (
            (34, 56, 138),
            (24, 105, 118),
            (128, 39, 96),
            (145, 68, 22),
            (76, 32, 131),
            (98, 44, 44),
            (22, 86, 46),
            (120, 32, 32),
        )
        base = rng.choice(palette)
        return (
            max(0, min(255, base[0] + rng.randint(-22, 22))),
            max(0, min(255, base[1] + rng.randint(-22, 22))),
            max(0, min(255, base[2] + rng.randint(-22, 22))),
        )

    def _build_digit_glyph(
        self, ch: str, fonts: List[ImageFont.ImageFont], rng: random.SystemRandom
    ) -> Image.Image:
        glyph = Image.new("RGBA", (72, 94), (255, 255, 255, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        font = rng.choice(fonts)
        fill_rgb = self._random_digit_color(rng)
        outline = (
            min(255, fill_rgb[0] + rng.randint(65, 105)),
            min(255, fill_rgb[1] + rng.randint(65, 105)),
            min(255, fill_rgb[2] + rng.randint(65, 105)),
            210,
        )
        fill = (*fill_rgb, 255)
        glyph_draw.text((16, 12), ch, font=font, fill=outline, stroke_width=1, stroke_fill=(250, 250, 250, 180))
        glyph_draw.text((12, 8), ch, font=font, fill=fill, stroke_width=2, stroke_fill=(30, 30, 30, 180))

        # Cut a few thin gaps to break clean OCR strokes while keeping legibility.
        for _ in range(rng.randint(1, 2)):
            x1 = rng.randint(8, 64)
            y1 = rng.randint(12, 80)
            x2 = min(70, max(2, x1 + rng.randint(-20, 20)))
            y2 = min(92, max(2, y1 + rng.randint(-14, 14)))
            glyph_draw.line((x1, y1, x2, y2), fill=(255, 255, 255, rng.randint(120, 185)), width=rng.randint(1, 2))

        resampling = getattr(Image, "Resampling", Image)
        transform_mode = getattr(getattr(Image, "Transform", Image), "AFFINE", Image.AFFINE)
        warped = glyph.transform(
            glyph.size,
            transform_mode,
            (
                rng.uniform(0.84, 1.14),
                rng.uniform(-0.35, 0.35),
                0,
                rng.uniform(-0.18, 0.18),
                rng.uniform(0.82, 1.08),
                0,
            ),
            resample=resampling.BICUBIC,
        )
        return warped.rotate(rng.randint(-33, 33), resample=resampling.BICUBIC, expand=1)

    def _place_glyphs_without_overlap(
        self, glyphs: List[Image.Image], width: int, height: int, rng: random.SystemRandom
    ) -> List[Tuple[int, int]]:
        if not glyphs:
            return []

        left_margin = 16
        right_margin = 16
        min_gap = 4
        available_width = max(80, width - left_margin - right_margin)
        total_width = sum(glyph.width for glyph in glyphs)
        required_width = total_width + (min_gap * (len(glyphs) - 1))

        if required_width > available_width:
            resampling = getattr(Image, "Resampling", Image)
            scale = max(0.7, (available_width - (min_gap * (len(glyphs) - 1))) / max(1, total_width))
            for idx, glyph in enumerate(glyphs):
                resized_w = max(20, int(glyph.width * scale))
                resized_h = max(28, int(glyph.height * scale))
                glyphs[idx] = glyph.resize((resized_w, resized_h), resample=resampling.LANCZOS)

        placements: List[Tuple[int, int]] = []
        cursor = left_margin - min_gap
        for idx, glyph in enumerate(glyphs):
            remaining = glyphs[idx + 1 :]
            remaining_width = sum(g.width for g in remaining)
            remaining_gaps = min_gap * len(remaining)

            min_x = cursor + min_gap
            max_x = width - right_margin - glyph.width - remaining_width - remaining_gaps
            if max_x <= min_x:
                x = min_x
            else:
                x = min_x + rng.randint(0, min(10, max_x - min_x))

            base_center_y = int(height * 0.46) + rng.randint(-4, 6)
            y = base_center_y - (glyph.height // 2) + rng.randint(-3, 4)
            y = max(6, min(height - glyph.height - 6, y))

            placements.append((x, y))
            cursor = x + glyph.width

        return placements

    def _draw_digit_overlay_blocks(
        self, draw: ImageDraw.ImageDraw, width: int, height: int, rng: random.SystemRandom
    ) -> None:
        # Keep blocks mostly on the text band so they partially occlude digits.
        for _ in range(rng.randint(4, 7)):
            block_w = rng.randint(14, 40)
            block_h = rng.randint(10, 26)
            x = rng.randint(8, max(8, width - block_w - 8))
            y = rng.randint(int(height * 0.2), int(height * 0.72))
            fill = (
                rng.randint(115, 230),
                rng.randint(115, 230),
                rng.randint(115, 230),
            )
            draw.rectangle((x, y, x + block_w, y + block_h), fill=fill)

    def _draw_digit_cross_lines(self, draw: ImageDraw.ImageDraw, width: int, height: int, rng: random.SystemRandom) -> None:
        for _ in range(rng.randint(2, 3)):
            amplitude = rng.randint(5, 11)
            frequency = rng.uniform(0.028, 0.052)
            phase = rng.uniform(0.0, math.tau)
            offset = rng.randint(int(height * 0.35), int(height * 0.65))
            points = [
                (x, int(offset + amplitude * math.sin((x * frequency) + phase)))
                for x in range(0, width, 2)
            ]
            color = (rng.randint(45, 155), rng.randint(45, 155), rng.randint(45, 155))
            draw.line(points, fill=color, width=rng.randint(2, 3))

    def _get_captcha_fonts(self) -> List[ImageFont.ImageFont]:
        fonts: List[ImageFont.ImageFont] = []
        for font_name, font_size in (
            ("arial.ttf", 46),
            ("arialbd.ttf", 46),
            ("calibrib.ttf", 45),
            ("bahnschrift.ttf", 44),
            ("DejaVuSans-Bold.ttf", 45),
        ):
            with contextlib.suppress(OSError):
                fonts.append(ImageFont.truetype(font_name, font_size))
        if not fonts:
            fonts.append(ImageFont.load_default())
        return fonts

    def _build_notice_embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=color)

    async def _send_notice(self, channel: discord.TextChannel, embed: discord.Embed) -> None:
        with contextlib.suppress(discord.Forbidden, discord.HTTPException):
            await channel.send(embed=embed, delete_after=self.NOTICE_DELETE_SECONDS)

    async def _run_trap(self, message: discord.Message, captcha_prompt: Optional[discord.Message] = None):
        guild = message.guild
        member = message.author
        if guild is None or not isinstance(member, discord.Member):
            return

        if captcha_prompt is not None:
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                await captcha_prompt.delete()

        me = guild.me
        if me is None:
            return
        my_perms = guild.me.guild_permissions
        if not (my_perms.ban_members and my_perms.manage_messages):
            log.warning("Missing required permissions in guild %s (%s)", guild.name, guild.id)
            return
        if member == guild.owner or member.top_role >= me.top_role:
            log.info(
                "Cannot trap user %s (%s) in guild %s (%s) because of role hierarchy.",
                member,
                member.id,
                guild.name,
                guild.id,
            )
            return

        delete_window_seconds = await self.config.guild(guild).delete_window_seconds()
        deleted_count = await self._delete_recent_messages(guild, member, delete_window_seconds)

        reason = f"BotTrap triggered in #{message.channel} ({message.channel.id})"
        banned = await self._ban_without_deleting_messages(guild, member, reason)
        if not banned:
            return

        temp_ban_seconds = await self.config.guild(guild).temp_ban_seconds()
        await asyncio.sleep(max(1, temp_ban_seconds))

        with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
            await guild.unban(discord.Object(id=member.id), reason="BotTrap temporary ban expired")

        log.info(
            "BotTrap executed for user %s (%s) in guild %s (%s); deleted %s recent messages.",
            member,
            member.id,
            guild.name,
            guild.id,
            deleted_count,
        )

    async def _ban_without_deleting_messages(
        self, guild: discord.Guild, member: discord.Member, reason: str
    ) -> bool:
        try:
            await guild.ban(member, reason=reason, delete_message_seconds=0)
            return True
        except TypeError:
            try:
                await guild.ban(member, reason=reason, delete_message_days=0)
                return True
            except (discord.Forbidden, discord.HTTPException):
                log.exception("Failed to ban user %s (%s) in guild %s (%s)", member, member.id, guild.name, guild.id)
                return False
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Failed to ban user %s (%s) in guild %s (%s)", member, member.id, guild.name, guild.id)
            return False

    async def _delete_recent_messages(
        self, guild: discord.Guild, member: discord.Member, delete_window_seconds: int
    ) -> int:
        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(60, delete_window_seconds))

        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.read_message_history and perms.manage_messages):
                continue

            try:
                pending = []
                async for msg in channel.history(limit=None, after=cutoff):
                    if msg.author.id != member.id:
                        continue
                    pending.append(msg)
                    if len(pending) >= 100:
                        deleted += await self._delete_message_batch(channel, pending)
                        pending = []

                if pending:
                    deleted += await self._delete_message_batch(channel, pending)
            except (discord.Forbidden, discord.HTTPException):
                log.debug(
                    "Cannot read/delete history in #%s (%s) on guild %s (%s)",
                    channel.name,
                    channel.id,
                    guild.name,
                    guild.id,
                )
        return deleted

    async def _delete_message_batch(self, channel: discord.TextChannel, messages: list) -> int:
        if not messages:
            return 0
        if len(messages) == 1:
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                await messages[0].delete()
                return 1
            return 0

        try:
            await channel.delete_messages(messages)
            return len(messages)
        except discord.HTTPException:
            count = 0
            for msg in messages:
                with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await msg.delete()
                    count += 1
            return count

    @commands.group(name="bottrap")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def bottrap(self, ctx: commands.Context):
        """Bot trap settings."""

    @bottrap.command(name="channel")
    async def bottrap_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the trap channel."""
        await self.config.guild(ctx.guild).trap_channel_id.set(channel.id)
        await ctx.send(f"已設定陷阱頻道為 {channel.mention}")

    @bottrap.command(name="clear")
    async def bottrap_clear(self, ctx: commands.Context):
        """Clear trap channel."""
        await self.config.guild(ctx.guild).trap_channel_id.set(None)
        await ctx.send("已清除陷阱頻道設定")

    @bottrap.command(name="duration")
    async def bottrap_duration(self, ctx: commands.Context, seconds: int):
        """Set temp-ban duration in seconds."""
        if seconds < 1 or seconds > 86400:
            await ctx.send("秒數必須介於 1 到 86400 之間")
            return
        await self.config.guild(ctx.guild).temp_ban_seconds.set(seconds)
        await ctx.send(f"已設定暫時 Ban 時間為 {seconds} 秒")

    @bottrap.command(name="enable")
    async def bottrap_enable(self, ctx: commands.Context, enabled: bool):
        """Enable or disable trap."""
        await self.config.guild(ctx.guild).enabled.set(enabled)
        await ctx.send("BotTrap 已啟用" if enabled else "BotTrap 已停用")

    @bottrap.command(name="status")
    async def bottrap_status(self, ctx: commands.Context):
        """Show current settings."""
        conf = await self.config.guild(ctx.guild).all()
        channel_id = conf["trap_channel_id"]
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        channel_text = channel.mention if channel else "未設定"
        enabled_text = "啟用" if conf["enabled"] else "停用"
        await ctx.send(
            f"狀態: {enabled_text}\n"
            f"陷阱頻道: {channel_text}\n"
            f"暫時 Ban 秒數: {conf['temp_ban_seconds']}\n"
            f"清理訊息範圍: {int(conf['delete_window_seconds'] / 60)} 分鐘"
        )

    @bottrap.command(name="test")
    async def bottrap_test(self, ctx: commands.Context):
        """Run captcha challenge test without taking moderation action."""
        passed, prompt = await self._run_captcha_challenge(ctx.message, delete_trigger_message=False)
        if prompt is not None:
            with contextlib.suppress(discord.NotFound, discord.Forbidden, discord.HTTPException):
                await prompt.delete()
        if not passed:
            await ctx.send("測試完成：未通過驗證（僅測試，不會封鎖）。", delete_after=self.NOTICE_DELETE_SECONDS)
