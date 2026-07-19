from __future__ import annotations

import unittest

from ticket_to_ride.backend.bot_directory import DirectoryBot, DirectoryListing
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.backend.runtime import ManagedMatchRuntimeManager
from ticket_to_ride.backend.runtime.executor import BotApiExecutor, InProcessBotExecutor


def directory_bot(bot_id: str, *, source: str, base_url: str | None = None) -> DirectoryBot:
    return DirectoryBot(
        bot_id=bot_id,
        name=bot_id.replace("_", " ").title(),
        version="1.0.0",
        description="d",
        author="",
        tags=[],
        source=source,
        connection_id="conn1" if source == "remote" else None,
        base_url=base_url,
        module_path="" if source == "remote" else f"/repo/bots/{bot_id}.py",
    )


class FakeBotDirectory:
    def __init__(self, bots: list[DirectoryBot]) -> None:
        self.bots = list(bots)
        self.list_all_calls = 0

    def list_all(self) -> DirectoryListing:
        self.list_all_calls += 1
        return DirectoryListing(bots=list(self.bots), connections=[])

    def resolve(self, bot_id: str) -> DirectoryBot:
        for bot in self.bots:
            if bot.bot_id == bot_id:
                return bot
        raise KeyError(f"Unknown bot '{bot_id}'.")


class RemoteExecutorRoutingTests(unittest.TestCase):
    def build_manager(self, bots: list[DirectoryBot]) -> ManagedMatchRuntimeManager:
        return ManagedMatchRuntimeManager(
            InMemoryMatchRepository(),
            bot_directory=FakeBotDirectory(bots),
        )

    def test_remote_bot_routes_to_bot_api_executor_with_connection_url(self) -> None:
        manager = self.build_manager(
            [directory_bot("friend_bot", source="remote", base_url="http://friend-host:8001")]
        )

        executor = manager.executor_factory("friend_bot")

        self.assertIsInstance(executor, BotApiExecutor)
        self.assertEqual(executor.base_url, "http://friend-host:8001")

    def test_local_bot_routes_to_in_process_executor(self) -> None:
        manager = self.build_manager([directory_bot("random_bot", source="local")])

        executor = manager.executor_factory("random_bot")

        self.assertIsInstance(executor, InProcessBotExecutor)

    def test_unresolvable_bot_falls_back_to_in_process_executor(self) -> None:
        manager = self.build_manager([])

        executor = manager.executor_factory("ghost_bot")

        self.assertIsInstance(executor, InProcessBotExecutor)

    def test_round_executor_factory_fetches_directory_listing_only_once(self) -> None:
        fake_directory = FakeBotDirectory(
            [
                directory_bot("friend_bot", source="remote", base_url="http://friend-host:8001"),
                directory_bot("random_bot", source="local"),
            ]
        )
        manager = ManagedMatchRuntimeManager(
            InMemoryMatchRepository(),
            bot_directory=fake_directory,
        )

        round_factory = manager._round_executor_factory()

        remote_executor = round_factory("friend_bot")
        local_executor = round_factory("random_bot")
        another_remote_lookup = round_factory("friend_bot")

        self.assertIsInstance(remote_executor, BotApiExecutor)
        self.assertEqual(remote_executor.base_url, "http://friend-host:8001")
        self.assertIsInstance(local_executor, InProcessBotExecutor)
        self.assertIsInstance(another_remote_lookup, BotApiExecutor)
        self.assertEqual(fake_directory.list_all_calls, 1)

    def test_round_executor_factory_passes_through_injected_factory_unchanged(self) -> None:
        def custom_factory(bot_id: str) -> BotApiExecutor:
            return BotApiExecutor(bot_id, base_url="http://custom-host:9000")

        manager = ManagedMatchRuntimeManager(
            InMemoryMatchRepository(),
            executor_factory=custom_factory,
            bot_directory=FakeBotDirectory([]),
        )

        self.assertIs(manager._round_executor_factory(), custom_factory)


if __name__ == "__main__":
    unittest.main()
