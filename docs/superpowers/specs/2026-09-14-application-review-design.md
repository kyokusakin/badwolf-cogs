# Application Review Cog Design

## Goal

Add a Redbot cog that watches one configured application channel per guild, marks valid application messages with review reactions, and lets channel managers reject an application by clearing every thumbs-up reaction from that message.

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

For each valid new message, the bot adds `👍` followed by `🚫`.

When `🚫` is added in the configured channel, the cog ignores bot users and fetches the target message. It proceeds only when the message still matches the application format and the reacting member has Discord administrator permission or effective `Manage Channels` permission in that channel. It then calls `clear_reaction("👍")`, removing every user's `👍` from that message. Other messages and reactions remain unchanged; `🚫` remains.

The bot needs `Add Reactions`, `Read Message History`, and `Manage Messages` permissions.

## Verification

Pure Python unit tests cover exact message recognition and reviewer permission rules without requiring Redbot installation. Python compilation verifies cog syntax. Runtime Discord behavior remains dependent on a Redbot instance with required permissions.
