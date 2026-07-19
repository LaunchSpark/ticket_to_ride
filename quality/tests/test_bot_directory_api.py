from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_catalog import BotCatalogError, BotCatalogRecord
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.bot_scaffold import BotScaffoldError, ScaffoldedBot
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def catalog_record(bot_id: str, name: str) -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Author",
        tags=["test"],
        source_kind="local_api",
        source_base_url="http://127.0.0.1:8001",
        discovery_path="/bots",
        module_path=f"/repo/integrations/external/bots/{bot_id}.py",
    )


class StaticCatalog:
    def __init__(self, records):
        self.records = list(records)

    def list_bots(self):
        return list(self.records)

    def resolve_bot(self, bot_id: str):
        for record in self.records:
            if record.bot_id == bot_id:
                return record
        raise KeyError(bot_id)


class FailingCatalog:
    def list_bots(self):
        raise BotCatalogError("connection refused")

    def resolve_bot(self, bot_id: str):
        raise BotCatalogError("connection refused")


class FakeNotebookLauncher(NotebookLauncher):
    def __init__(self) -> None:
        self.launch_calls = []

    def launch(self, bot_id: str, notebook_path: str) -> str:
        self.launch_calls.append((bot_id, notebook_path))
        return "http://127.0.0.1:2718"


def build_client(repository, local_records, remote_catalogs, notebook_launcher=None):
    directory = BotDirectory(
        repository,
        local_catalog_factory=lambda: StaticCatalog(local_records),
        remote_catalog_factory=lambda url: remote_catalogs[url],
    )
    return TestClient(
        create_app(
            repository=repository,
            bot_directory=directory,
            notebook_launcher=notebook_launcher or FakeNotebookLauncher(),
        )
    )


class BotListingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_local_bots_are_listed_without_registration(self) -> None:
        client = build_client(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        response = client.get("/bots")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["bots"]), 1)
        self.assertEqual(payload["bots"][0]["botId"], "random_bot")
        self.assertEqual(payload["bots"][0]["source"], "local")
        self.assertIsNone(payload["bots"][0]["connectionId"])
        self.assertEqual(payload["connections"], [])

    def test_connections_report_status_and_remote_bots(self) -> None:
        online = self.repository.create_bot_connection("http://friend-a:8001")
        self.repository.create_bot_connection("http://friend-b:8001")
        client = build_client(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {
                "http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")]),
                "http://friend-b:8001": FailingCatalog(),
            },
        )

        payload = client.get("/bots").json()

        by_id = {bot["botId"]: bot for bot in payload["bots"]}
        self.assertEqual(by_id["friend_bot"]["source"], "remote")
        self.assertEqual(by_id["friend_bot"]["connectionId"], online["id"])
        self.assertEqual(by_id["friend_bot"]["baseUrl"], "http://friend-a:8001")
        statuses = {connection["url"]: connection["status"] for connection in payload["connections"]}
        self.assertEqual(statuses, {"http://friend-a:8001": "online", "http://friend-b:8001": "offline"})


class NewBotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.notebook_launcher = FakeNotebookLauncher()
        self.client = build_client(self.repository, [], {}, notebook_launcher=self.notebook_launcher)

    def test_new_bot_is_scaffolded_and_its_notebook_opened(self) -> None:
        scaffolded = ScaffoldedBot(bot_id="my_cool_bot", name="My Cool Bot", path="/repo/bots/my_cool_bot.py")

        with patch("ticket_to_ride.backend.service.scaffold_bot", return_value=scaffolded) as scaffold:
            response = self.client.post("/bots/new", json={"name": "My Cool Bot"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"botId": "my_cool_bot", "url": "http://127.0.0.1:2718"})
        scaffold.assert_called_once_with("My Cool Bot")
        self.assertEqual(self.notebook_launcher.launch_calls, [("my_cool_bot", "/repo/bots/my_cool_bot.py")])

    def test_invalid_bot_name_returns_bad_request(self) -> None:
        with patch("ticket_to_ride.backend.service.scaffold_bot", side_effect=BotScaffoldError("Bot name is required.")):
            response = self.client.post("/bots/new", json={"name": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Bot name is required.")


class ConnectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_add_connection_pings_and_persists(self) -> None:
        client = build_client(
            self.repository,
            [],
            {"http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")])},
        )

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001/"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["connection"]["url"], "http://friend-a:8001")
        self.assertEqual(payload["connection"]["status"], "online")
        self.assertEqual(payload["connection"]["botCount"], 1)
        self.assertEqual(payload["bots"][0]["botId"], "friend_bot")
        self.assertEqual(len(self.repository.list_bot_connections()), 1)

    def test_duplicate_connection_url_is_rejected(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        client = build_client(
            self.repository,
            [],
            {"http://friend-a:8001": StaticCatalog([])},
        )

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["detail"])

    def test_unreachable_connection_is_rejected(self) -> None:
        client = build_client(self.repository, [], {"http://friend-a:8001": FailingCatalog()})

        response = client.post("/bot-connections", json={"url": "http://friend-a:8001"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_non_http_url_is_rejected(self) -> None:
        client = build_client(self.repository, [], {})

        response = client.post("/bot-connections", json={"url": "ftp://friend-a:8001"})

        self.assertEqual(response.status_code, 400)

    def test_delete_connection(self) -> None:
        record = self.repository.create_bot_connection("http://friend-a:8001")
        client = build_client(self.repository, [], {"http://friend-a:8001": StaticCatalog([])})

        response = client.delete(f"/bot-connections/{record['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_delete_unknown_connection_returns_not_found(self) -> None:
        client = build_client(self.repository, [], {})

        response = client.delete("/bot-connections/nope")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
