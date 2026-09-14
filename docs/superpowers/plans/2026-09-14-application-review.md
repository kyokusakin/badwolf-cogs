# Application Review Cog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Redbot cog that reacts to application messages in one configured channel and lets authorized reviewers clear all thumbs-up reactions by adding `🚫`.

**Architecture:** Keep format and permission decisions in a dependency-free rules module. Connect those rules to Red listeners backed by guild-scoped `Config`, plus two administrator commands for setting or disabling the watched channel.

**Tech Stack:** Python 3.9+, Red-DiscordBot 3.5+, discord.py, stdlib `unittest`

**Spec:** `docs/superpowers/specs/2026-09-14-application-review-design.md`

## Global Constraints

- Store one application channel per guild.
- Match exactly two labeled lines using full-width `：` and non-empty values.
- Add `👍` and `🚫` to matching new messages only.
- Only Discord administrators or members with effective `Manage Channels` permission may clear `👍`.
- Clear every `👍` from target application message and preserve `🚫`.
- Add no runtime dependency beyond Red-DiscordBot and its bundled discord.py.

---

### Task 1: Application Rules

**Files:**
- Create: `applicationreview/rules.py`
- Create: `tests/test_applicationreview_rules.py`

**Interfaces:**
- Consumes: message content strings and two Discord permission booleans
- Produces: `is_application_message(content: str) -> bool` and `can_reject(administrator: bool, manage_channels: bool) -> bool`

- [x] **Step 1: Write failing rules tests**

```python
import unittest

from applicationreview.rules import can_reject, is_application_message


class ApplicationMessageTests(unittest.TestCase):
    def test_accepts_exact_application(self):
        self.assertTrue(is_application_message("申請：加入活動\n理由：想參加"))

    def test_requires_two_nonempty_labeled_lines(self):
        invalid_messages = (
            "申請：\n理由：想參加",
            "申請：加入活動\n理由：   ",
            "申請:加入活動\n理由:想參加",
            "申請：加入活動\n理由：想參加\n其他：內容",
        )
        for content in invalid_messages:
            with self.subTest(content=content):
                self.assertFalse(is_application_message(content))


class ReviewerPermissionTests(unittest.TestCase):
    def test_allows_administrator_or_channel_manager(self):
        self.assertTrue(can_reject(administrator=True, manage_channels=False))
        self.assertTrue(can_reject(administrator=False, manage_channels=True))
        self.assertFalse(can_reject(administrator=False, manage_channels=False))
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_applicationreview_rules -v`

Expected: FAIL because `applicationreview.rules` does not exist.

- [x] **Step 3: Implement minimal rules**

```python
APPLICATION_PREFIX = "申請："
REASON_PREFIX = "理由："


def is_application_message(content: str) -> bool:
    lines = content.splitlines()
    return (
        len(lines) == 2
        and lines[0].startswith(APPLICATION_PREFIX)
        and bool(lines[0][len(APPLICATION_PREFIX) :].strip())
        and lines[1].startswith(REASON_PREFIX)
        and bool(lines[1][len(REASON_PREFIX) :].strip())
    )


def can_reject(administrator: bool, manage_channels: bool) -> bool:
    return administrator or manage_channels
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_applicationreview_rules -v`

Expected: 3 tests pass.

- [x] **Step 5: Commit rules**

```bash
git add applicationreview/rules.py tests/test_applicationreview_rules.py
git commit -m "feat: add application review rules"
```

### Task 2: Redbot Cog

**Files:**
- Create: `applicationreview/__init__.py`
- Create: `applicationreview/applicationreview.py`
- Create: `applicationreview/info.json`

**Interfaces:**
- Consumes: `is_application_message` and `can_reject` from Task 1; Red message and raw reaction events
- Produces: loadable `ApplicationReview` cog, `[p]applicationreview channel`, and `[p]applicationreview disable`

- [x] **Step 1: Implement lazy package setup**

```python
async def setup(bot):
    from .applicationreview import ApplicationReview

    await bot.add_cog(ApplicationReview(bot))
```

- [x] **Step 2: Implement configuration commands and listeners**

```python
import discord
from redbot.core import Config, commands

from .rules import can_reject, is_application_message

THUMBS_UP = "👍"
REJECT = "🚫"


class ApplicationReview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=421765611811838116, force_registration=True
        )
        self.config.register_guild(channel_id=None)

    @commands.group(name="applicationreview")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def applicationreview(self, ctx: commands.Context):
        """Configure application review reactions."""

    @applicationreview.command(name="channel")
    async def applicationreview_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the application channel."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"已設定申請頻道為 {channel.mention}")

    @applicationreview.command(name="disable")
    async def applicationreview_disable(self, ctx: commands.Context):
        """Disable application review reactions."""
        await self.config.guild(ctx.guild).channel_id.set(None)
        await ctx.send("已停用申請頻道監聽")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        channel_id = await self.config.guild(message.guild).channel_id()
        if message.channel.id != channel_id or not is_application_message(message.content):
            return
        await message.add_reaction(THUMBS_UP)
        await message.add_reaction(REJECT)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or str(payload.emoji) != REJECT:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return
        channel_id = await self.config.guild(guild).channel_id()
        if payload.channel_id != channel_id:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        permissions = channel.permissions_for(member)
        if not can_reject(permissions.administrator, permissions.manage_channels):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        if not is_application_message(message.content):
            return
        await message.clear_reaction(THUMBS_UP)
```

- [x] **Step 3: Add cog metadata**

Set Redbot minimum version `3.5.0`, Python minimum `3.9.0`, no external requirements, and required permissions `add_reactions`, `read_message_history`, and `manage_messages`.

- [x] **Step 4: Verify cog files**

Run: `python -m compileall -q applicationreview`

Expected: exit code 0.

Run: `python -m json.tool applicationreview/info.json > $null`

Expected: exit code 0.

- [x] **Step 5: Run rules regression tests**

Run: `python -m unittest tests.test_applicationreview_rules -v`

Expected: 3 tests pass.

- [x] **Step 6: Commit cog**

```bash
git add applicationreview
git commit -m "feat: add application review cog"
```

### Task 3: Repository Listing and Final Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: completed cog metadata and command names
- Produces: repository catalog entry for `applicationreview`

- [x] **Step 1: Add README catalog entry**

```markdown
| applicationreview | Add review reactions to applications in a configured channel and let channel managers reject them. | Badwolf_TW |
```

- [x] **Step 2: Run complete verification**

Run: `python -m unittest tests.test_applicationreview_rules -v`

Expected: 3 tests pass.

Run: `python -m compileall -q applicationreview tests/test_applicationreview_rules.py`

Expected: exit code 0.

Run: `python -m json.tool applicationreview/info.json > $null`

Expected: exit code 0.

- [x] **Step 3: Review scope and commit**

Run: `git diff --check`

Expected: exit code 0.

```bash
git add README.md
git commit -m "docs: list application review cog"
```
