from collections.abc import Collection


def is_invite_blocked(
    *,
    destination_guild_id: int,
    current_guild_id: int,
    allowlist: Collection[int],
    blocklist: Collection[int],
    block_all: bool,
) -> bool:
    if destination_guild_id in allowlist:
        return False
    if block_all:
        return True
    if destination_guild_id == current_guild_id:
        return False
    if allowlist:
        return True
    return destination_guild_id in blocklist
