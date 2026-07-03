from __future__ import annotations

import unittest
from unittest.mock import patch

from ticket_to_ride.backend.bot_catalog import LocalApiBotCatalogClient


class BotCatalogModulePathTests(unittest.TestCase):
    def test_list_bots_carries_module_path_through_to_the_catalog_record(self) -> None:
        payload = [
            {
                "schemaVersion": 1,
                "botId": "random_bot",
                "name": "Random Bot",
                "version": "1.0.0",
                "description": "desc",
                "author": "a",
                "tags": [],
                "modulePath": "/repo/integrations/external/bots/random_bot.py",
            }
        ]

        client = LocalApiBotCatalogClient(base_url="http://127.0.0.1:8001")

        with patch.object(LocalApiBotCatalogClient, "_request_json", return_value=payload):
            records = client.list_bots()

        self.assertEqual(records[0].module_path, "/repo/integrations/external/bots/random_bot.py")


if __name__ == "__main__":
    unittest.main()
