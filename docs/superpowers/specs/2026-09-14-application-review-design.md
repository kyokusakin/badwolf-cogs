# Application Review Cog Design

## Goal

Add a Redbot cog that watches one configured application channel per guild, marks valid application messages with vote reactions, marks an application as approved while thumbs-up votes outnumber thumbs-down votes, and lets channel managers reject an application by clearing every thumbs-up reaction from that message.

## Configuration

The cog stores one `channel_id` per guild with Red `Config`.
Configuration commands live in `c_applicationreview.py`; the main cog owns configuration state and event listeners.

- `[p]applicationreview channel #channel` sets the watched text channel.
- `[p]applicationreview disable` clears the setting.
- Both commands require Discord administrator permission or `Manage Channels` permission.

## Message Recognition

The cog ignores bots, direct messages, disabled guilds, and messages outside the configured channel. A valid message has exactly two lines, uses the full-width `：` separator, and has non-whitespace text after both labels:

```text
申請：TEXT
理由：TEXT
```

Line endings may be LF or CRLF. Edited messages are outside scope.

## Reaction Flow

For each valid new message, the bot adds `👍`, `👎`, and `🚫` in that order.

`👍` and `👎` are votes. Whenever either is added or removed in the configured channel by someone other than the bot, the cog fetches the target message, counts each vote emoji excluding the bot's own seed reaction, and applies `is_approved(approvals, oppositions)`, which is true only when `👍` strictly outnumbers `👎`. When approved the bot adds `✅`; otherwise it removes its own `✅`. The bot only ever changes its own `✅` reaction.

When `🚫` is added in the configured channel, the cog ignores bot users and fetches the target message. It proceeds only when the message still matches the application format and the reacting member has Discord administrator permission or effective `Manage Channels` permission in that channel. It then calls `clear_reaction("👍")`, removing every user's `👍` from that message, and removes its own `✅`. Other messages and reactions remain unchanged; `👎` and `🚫` remain.

The bot needs `Add Reactions`, `Read Message History`, and `Manage Messages` permissions.

## Verification

Pure Python unit tests cover exact message recognition, reviewer permission, and approval-threshold rules without requiring Redbot installation. Python compilation verifies cog syntax. Runtime Discord behavior remains dependent on a Redbot instance with required permissions.
