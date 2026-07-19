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

    def list_all(self) -> DirectoryListing:
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


if __name__ == "__main__":
    unittest.main()
