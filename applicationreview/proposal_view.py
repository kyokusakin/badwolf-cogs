from __future__ import annotations

import discord


class ProposalView(discord.ui.View):
    def __init__(
        self,
        cog,
        *,
        disabled: bool = False,
        voting_closed: bool = False,
        confirm_enabled: bool = False,
    ):
        super().__init__(timeout=None)
        buttons = (
            ("贊成", "yes", discord.ButtonStyle.success),
            ("反對", "no", discord.ButtonStyle.secondary),
            ("禁止", "prohibit", discord.ButtonStyle.danger),
            ("確認", "confirm", discord.ButtonStyle.primary),
        )
        for label, action, style in buttons:
            button = discord.ui.Button(
                label=label,
                custom_id=f"applicationreview:proposal:{action}",
                style=style,
                disabled=(
                    disabled
                    or (voting_closed and action in ("yes", "no"))
                    or (action == "confirm" and not confirm_enabled)
                ),
            )

            async def callback(interaction, selected=action):
                if selected in ("yes", "no"):
                    await cog._handle_proposal_vote(interaction, selected)
                else:
                    await cog._handle_proposal_admin(interaction, selected)

            button.callback = callback
            self.add_item(button)
