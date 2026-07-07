from __future__ import annotations

from typing import Any

from external.contracts.base_bot import ActionBot


BOT_META = {
    "schema_version": 1,
    "id": "your_bot_id",
    "name": "Your Bot Name",
    "version": "1.0.0",
    "description": "Describe the strategy or purpose of this bot.",
    "author": "",
    "tags": [],
}


class YourBotName(ActionBot):
    META = BOT_META

    def act(self, view: Any, legal_actions: list[Any]) -> Any:
        """Choose and return one action from legal_actions."""
        return legal_actions[0]
