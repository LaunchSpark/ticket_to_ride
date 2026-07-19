from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ticket_to_ride.backend.bot_catalog import BotCatalogError, LocalApiBotCatalogClient


def _fake_response(payload):
    class FakeResponse:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return FakeResponse()


REMOTE_BOT_PAYLOAD = [
    {
        "schemaVersion": 1,
        "botId": "friend_bot",
        "name": "Friend Bot",
        "version": "2.0.0",
        "description": "A bot served from another machine.",
        "author": "Friend",
        "tags": ["remote"],
    }
]


class RemoteCatalogClientTests(unittest.TestCase):
    def test_non_loopback_base_url_is_rejected_by_default(self) -> None:
        client = LocalApiBotCatalogClient("http://friend-host:8001")

        with self.assertRaises(BotCatalogError):
            client.list_bots()

    def test_non_loopback_base_url_is_allowed_when_loopback_is_not_required(self) -> None:
        client = LocalApiBotCatalogClient("http://friend-host:8001", require_loopback=False)

        with patch(
            "ticket_to_ride.backend.bot_catalog.urlopen",
            return_value=_fake_response(REMOTE_BOT_PAYLOAD),
        ):
            records = client.list_bots()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].bot_id, "friend_bot")
        self.assertEqual(records[0].source_base_url, "http://friend-host:8001")

    def test_non_http_scheme_is_rejected_even_without_loopback_requirement(self) -> None:
        client = LocalApiBotCatalogClient("ftp://friend-host:8001", require_loopback=False)

        with self.assertRaises(BotCatalogError):
            client.list_bots()


if __name__ == "__main__":
    unittest.main()
