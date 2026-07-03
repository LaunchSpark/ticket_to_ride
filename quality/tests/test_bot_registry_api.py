from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_catalog import BotCatalogError, BotCatalogRecord
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def build_catalog_record(
    bot_id: str,
    *,
    name: str,
    source_base_url: str = "http://127.0.0.1:8001",
    discovery_path: str = "/bots",
    module_path: str = "",
) -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Lucas Starkey",
        tags=["test"],
        source_kind="local_api",
        source_base_url=source_base_url,
        discovery_path=discovery_path,
        module_path=module_path,
    )


class StaticCatalogClient:
    def __init__(self, available_bots: list[BotCatalogRecord]) -> None:
        self.available_bots = available_bots

    def list_bots(self) -> list[BotCatalogRecord]:
        return list(self.available_bots)

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        requested_key = bot_id.casefold()
        match = next((bot for bot in self.available_bots if bot.bot_id.casefold() == requested_key), None)
        if match is None:
            raise KeyError(bot_id)
        return match


class FailingCatalogClient:
    def list_bots(self) -> list[BotCatalogRecord]:
        raise BotCatalogError("Bot catalog request failed: refused")

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        raise BotCatalogError("Bot catalog request failed: refused")


class BotRegistryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_list_bots_is_empty_before_any_bot_is_registered(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient([build_catalog_record("random_bot", name="Random Bot")]),
            )
        )

        response = client.get("/bots")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_register_bot_and_list_registered_bots(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient([build_catalog_record("random_bot", name="Random Bot")]),
            )
        )

        register_response = client.post("/bots", json={"botId": "random_bot"})

        self.assertEqual(register_response.status_code, 200)
        payload = register_response.json()
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["botId"], "random_bot")
        self.assertEqual(payload["name"], "Random Bot")
        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["sourceKind"], "local_api")
        self.assertEqual(payload["sourceBaseUrl"], "http://127.0.0.1:8001")
        self.assertEqual(payload["discoveryPath"], "/bots")

        list_response = client.get("/bots")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(list_response.json()[0]["botId"], "random_bot")

    def test_duplicate_registration_refreshes_existing_record(self) -> None:
        first_client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient(
                    [build_catalog_record("random_bot", name="Random Bot", source_base_url="http://127.0.0.1:8001")]
                ),
            )
        )
        second_client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient(
                    [build_catalog_record("random_bot", name="Random Bot", source_base_url="http://localhost:8001")]
                ),
            )
        )

        first_response = first_client.post("/bots", json={"botId": "random_bot"})
        second_response = second_client.post("/bots", json={"botId": "random_bot"})
        list_response = second_client.get("/bots")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(list_response.json()[0]["sourceBaseUrl"], "http://localhost:8001")

    def test_register_bot_returns_not_found_when_catalog_does_not_contain_id(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_catalog_client=StaticCatalogClient([build_catalog_record("other_bot", name="Other Bot")]),
            )
        )

        response = client.post("/bots", json={"botId": "random_bot"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown bot", response.json()["detail"])

    def test_bot_catalog_errors_are_returned_as_service_unavailable(self) -> None:
        client = TestClient(create_app(repository=self.repository, bot_catalog_client=FailingCatalogClient()))

        response = client.post("/bots", json={"botId": "random_bot"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["service"], "bot_catalog")

    def test_non_local_bot_api_base_url_is_rejected_in_v1(self) -> None:
        with patch.dict("os.environ", {"BOT_API_BASE_URL": "http://example.com:8001"}):
            client = TestClient(create_app(repository=self.repository))
            response = client.post("/bots", json={"botId": "random_bot"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["service"], "bot_catalog")
        self.assertIn("local loopback", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
