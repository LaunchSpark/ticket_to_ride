from __future__ import annotations

import unittest

from ticket_to_ride.backend.bot_catalog import BotCatalogError, BotCatalogRecord
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.repository import InMemoryMatchRepository


def catalog_record(bot_id: str, name: str, base_url: str = "http://127.0.0.1:8001") -> BotCatalogRecord:
    return BotCatalogRecord(
        schema_version=1,
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Author",
        tags=["test"],
        source_kind="local_api",
        source_base_url=base_url,
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


def build_directory(repository, local_records, remote_catalogs):
    return BotDirectory(
        repository,
        local_catalog_factory=lambda: StaticCatalog(local_records),
        remote_catalog_factory=lambda url: remote_catalogs[url],
    )


class BotDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_local_bots_are_listed_without_connections(self) -> None:
        directory = build_directory(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        listing = directory.list_all()

        self.assertEqual([bot.bot_id for bot in listing.bots], ["random_bot"])
        self.assertEqual(listing.bots[0].source, "local")
        self.assertIsNone(listing.bots[0].connection_id)
        self.assertEqual(listing.connections, [])

    def test_online_connection_contributes_remote_bots(self) -> None:
        connection = self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "Friend Bot")])},
        )

        listing = directory.list_all()

        remote = next(bot for bot in listing.bots if bot.bot_id == "friend_bot")
        self.assertEqual(remote.source, "remote")
        self.assertEqual(remote.connection_id, connection["id"])
        self.assertEqual(remote.base_url, "http://friend-a:8001")
        self.assertEqual(len(listing.connections), 1)
        self.assertEqual(listing.connections[0].status, "online")
        self.assertEqual(listing.connections[0].bot_count, 1)

    def test_offline_connection_is_reported_without_bots(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": FailingCatalog()},
        )

        listing = directory.list_all()

        self.assertEqual([bot.bot_id for bot in listing.bots], ["random_bot"])
        self.assertEqual(listing.connections[0].status, "offline")
        self.assertIn("connection refused", listing.connections[0].error)

    def test_local_bots_shadow_remote_bots_with_the_same_id(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        directory = build_directory(
            self.repository,
            [catalog_record("random_bot", "Random Bot")],
            {"http://friend-a:8001": StaticCatalog([catalog_record("random_bot", "Impostor Bot")])},
        )

        listing = directory.list_all()

        matches = [bot for bot in listing.bots if bot.bot_id == "random_bot"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].source, "local")
        self.assertEqual(listing.connections[0].bot_count, 1)

    def test_oldest_connection_wins_duplicate_remote_ids(self) -> None:
        self.repository.create_bot_connection("http://friend-a:8001")
        self.repository.create_bot_connection("http://friend-b:8001")
        directory = build_directory(
            self.repository,
            [],
            {
                "http://friend-a:8001": StaticCatalog([catalog_record("friend_bot", "First Friend")]),
                "http://friend-b:8001": StaticCatalog([catalog_record("friend_bot", "Second Friend")]),
            },
        )

        listing = directory.list_all()

        matches = [bot for bot in listing.bots if bot.bot_id == "friend_bot"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].base_url, "http://friend-a:8001")

    def test_resolve_finds_bots_case_insensitively(self) -> None:
        directory = build_directory(self.repository, [catalog_record("random_bot", "Random Bot")], {})

        self.assertEqual(directory.resolve("Random_Bot").bot_id, "random_bot")
        with self.assertRaises(KeyError):
            directory.resolve("missing_bot")


if __name__ == "__main__":
    unittest.main()
