from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_catalog import BotCatalogRecord
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def build_catalog_record(bot_id: str, module_path: str) -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name="Random Bot",
        version="1.0.0",
        description="desc",
        author="a",
        tags=[],
        source_kind="local_api",
        source_base_url="http://127.0.0.1:8001",
        discovery_path="/bots",
        module_path=module_path,
    )


class StaticCatalogClient:
    def __init__(self, records: list[BotCatalogRecord]) -> None:
        self.records = records

    def list_bots(self) -> list[BotCatalogRecord]:
        return list(self.records)

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        for record in self.records:
            if record.bot_id == bot_id:
                return record
        raise KeyError(bot_id)


class NotebookLaunchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.spawn_calls = []

        def fake_spawner(notebook_path: str, port: int):
            self.spawn_calls.append((notebook_path, port))

            class FakeProcess:
                def poll(self_inner):
                    return None

            return FakeProcess()

        self.notebook_launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: 12345)

    def test_launch_returns_a_url_for_a_known_bot(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient(
                        [build_catalog_record("random_bot", "/repo/integrations/external/bots/random_bot.py")]
                    ),
                    remote_catalog_factory=lambda url: (_ for _ in ()).throw(AssertionError("no remote calls expected")),
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/random_bot/launch")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"botId": "random_bot", "url": "http://127.0.0.1:12345"})
        self.assertEqual(self.spawn_calls, [("/repo/integrations/external/bots/random_bot.py", 12345)])

    def test_launch_returns_not_found_for_an_unknown_bot(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient([]),
                    remote_catalog_factory=lambda url: (_ for _ in ()).throw(AssertionError("no remote calls expected")),
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/unknown_bot/launch")

        self.assertEqual(response.status_code, 404)

    def test_launching_the_same_bot_twice_reuses_the_session(self) -> None:
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient(
                        [build_catalog_record("random_bot", "/repo/integrations/external/bots/random_bot.py")]
                    ),
                    remote_catalog_factory=lambda url: (_ for _ in ()).throw(AssertionError("no remote calls expected")),
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        first_response = client.post("/notebooks/random_bot/launch")
        second_response = client.post("/notebooks/random_bot/launch")

        self.assertEqual(first_response.json(), second_response.json())
        self.assertEqual(len(self.spawn_calls), 1)

    def test_launch_rejects_remote_bots(self) -> None:
        from ticket_to_ride.backend.bot_catalog import BotCatalogRecord

        self.repository.create_bot_connection("http://friend-a:8001")
        remote_record = build_catalog_record("friend_bot", "")
        client = TestClient(
            create_app(
                repository=self.repository,
                bot_directory=BotDirectory(
                    self.repository,
                    local_catalog_factory=lambda: StaticCatalogClient([]),
                    remote_catalog_factory=lambda url: StaticCatalogClient([remote_record]),
                ),
                notebook_launcher=self.notebook_launcher,
            )
        )

        response = client.post("/notebooks/friend_bot/launch")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.spawn_calls, [])


if __name__ == "__main__":
    unittest.main()
