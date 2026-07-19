from __future__ import annotations

import unittest

from ticket_to_ride.backend.repository import InMemoryMatchRepository


class BotConnectionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()

    def test_created_connections_are_listed_oldest_first(self) -> None:
        first = self.repository.create_bot_connection("http://friend-a:8001")
        second = self.repository.create_bot_connection("http://friend-b:8001")

        listed = self.repository.list_bot_connections()

        self.assertEqual([record["id"] for record in listed], [first["id"], second["id"]])
        self.assertEqual(listed[0]["url"], "http://friend-a:8001")
        self.assertTrue(listed[0]["createdAt"])

    def test_delete_removes_the_connection(self) -> None:
        record = self.repository.create_bot_connection("http://friend-a:8001")

        self.repository.delete_bot_connection(record["id"])

        self.assertEqual(self.repository.list_bot_connections(), [])

    def test_delete_unknown_connection_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.repository.delete_bot_connection("nope")


if __name__ == "__main__":
    unittest.main()
