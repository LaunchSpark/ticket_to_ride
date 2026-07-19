import time
import unittest
from collections import defaultdict
from typing import Dict, List, Tuple
from unittest.mock import patch

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.bot_directory import DirectoryBot, DirectoryListing
from ticket_to_ride.backend.runtime import BotExecutor, ExecutionResult, ManagedMatchRuntimeManager
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.engine.state.views import PlayerView


def local_directory_bot(bot_id: str, name: str) -> DirectoryBot:
    return DirectoryBot(
        bot_id=bot_id,
        name=name,
        version="1.0.0",
        description=f"{name} description",
        author="Test",
        tags=[],
        source="local",
        connection_id=None,
        base_url=None,
        module_path=f"/repo/bots/{bot_id}.py",
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


class FakeExecutor(BotExecutor):
    def __init__(self, bot_id: str, outcomes: List[Tuple[str, int]]) -> None:
        self.bot_id = bot_id
        self.outcomes = list(outcomes)

    def start(self) -> None:
        return None

    def invoke(
        self,
        action_name: str,
        *,
        player,
        timeout_ms,
        remaining_time_ms,
        initial_time_ms,
        increment_ms,
        args,
    ) -> ExecutionResult:
        status, elapsed_ms = self.outcomes.pop(0) if self.outcomes else ("ok", 50)
        if status == "ok":
            return ExecutionResult(status="ok", elapsed_ms=elapsed_ms, payload=1)
        return ExecutionResult(status=status, elapsed_ms=elapsed_ms, detail=f"{self.bot_id}:{status}")

    def close(self) -> ExecutionResult:
        return ExecutionResult(status="ok", elapsed_ms=0)


class FakeExecutorFactory:
    def __init__(self, plans: Dict[str, List[List[Tuple[str, int]]]]) -> None:
        self.plans = {bot_id: list(plan_list) for bot_id, plan_list in plans.items()}
        self.creation_counts = defaultdict(int)

    def __call__(self, bot_id: str) -> FakeExecutor:
        self.creation_counts[bot_id] += 1
        plan_list = self.plans.get(bot_id) or []
        if plan_list:
            outcomes = plan_list.pop(0)
        else:
            outcomes = [("ok", 50)]
        return FakeExecutor(bot_id, outcomes)


class ScriptedGame:
    def __init__(self, context, players, logger, round_number: int) -> None:
        self.base_context = context
        self.players = players
        self.logger = logger
        self.round_number = round_number
        self.context = self

    def play(self) -> None:
        for player in self.players:
            player.attach(self.base_context, self.players)
            player.set_context(PlayerView(player.player_id, self.base_context, self.players))
            self.logger.record_turn(self.round_number, player.context)
            interface = player.get_interface()
            interface.begin_turn()
            try:
                interface.choose_turn_action()
            finally:
                interface.end_turn(True)

    def get_score(self, player_id: str) -> int:
        return 100 if player_id == self.players[0].player_id else 50


class ManagedMatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.bot_directory = FakeBotDirectory(
            [
                local_directory_bot("slow_bot", "Slow Bot"),
                local_directory_bot("steady_bot", "Steady Bot"),
                local_directory_bot("random_bot", "Random Bot"),
                local_directory_bot("qualifier_bot", "Qualifier Bot"),
            ]
        )

    def test_failover_is_round_scoped_and_primary_returns_next_round(self) -> None:
        factory = FakeExecutorFactory(
            {
                "slow_bot": [[("per_call_timeout", 100)], [("ok", 50)]],
                "steady_bot": [[("ok", 50)], [("ok", 50)]],
                "random_bot": [[("ok", 10)]],
            }
        )
        runtime_manager = ManagedMatchRuntimeManager(
            self.repository, executor_factory=factory, bot_directory=self.bot_directory
        )
        client = TestClient(create_app(repository=self.repository, runtime_manager=runtime_manager))

        with patch("ticket_to_ride.backend.runtime.round_runtime.Game", ScriptedGame):
            response = client.post(
                "/managed-matches",
                json={
                    "name": "scripted-series",
                    "seats": [
                        {"seatId": "seat_1", "primaryBotId": "slow_bot"},
                        {"seatId": "seat_2", "primaryBotId": "steady_bot"},
                    ],
                    "fallbackBotId": "random_bot",
                    "roundCount": 2,
                    "timeControl": {
                        "initialTimeMs": 200,
                        "incrementMs": 20,
                        "perCallHardLimitMs": 100,
                    },
                    "timeoutPolicy": "switch_to_fallback",
                    "executionMode": "bot_api",
                },
            )

            self.assertEqual(response.status_code, 200)
            match_id = response.json()["matchId"]
            match_payload = self._wait_for_terminal_match(client, match_id)

        self.assertEqual(match_payload["status"], "completed")
        self.assertEqual(match_payload["aggregateResults"][0]["roundsWon"], 2)

        replay_payload = client.get(f"/matches/{match_payload['replayMatchId']}").json()
        self.assertEqual(replay_payload["mapName"], "classic")
        self.assertIsInstance(replay_payload["seed"], int)

        rounds_response = client.get(f"/managed-matches/{match_id}/rounds")
        self.assertEqual(rounds_response.status_code, 200)
        rounds = rounds_response.json()
        self.assertEqual(len(rounds), 2)

        round_zero = client.get(f"/managed-matches/{match_id}/rounds/0").json()
        round_one = client.get(f"/managed-matches/{match_id}/rounds/1").json()
        seat_zero_round_zero = self._seat_result(round_zero["seatResults"], "seat_1")
        seat_zero_round_one = self._seat_result(round_one["seatResults"], "seat_1")
        self.assertEqual(seat_zero_round_zero["activeRole"], "fallback")
        self.assertTrue(seat_zero_round_zero["hasFailedOver"])
        self.assertEqual(seat_zero_round_zero["remainingTimeMs"], 110)
        self.assertEqual(seat_zero_round_one["activeRole"], "primary")
        self.assertFalse(seat_zero_round_one["hasFailedOver"])
        self.assertEqual(seat_zero_round_one["remainingTimeMs"], 170)

        runtime_view = client.get(f"/managed-matches/{match_id}/rounds/0/runtime").json()
        runtime_seat = self._runtime_seat(runtime_view["seats"], "seat_1")
        self.assertEqual(runtime_seat["activeRole"], "fallback")
        self.assertTrue(runtime_seat["hasFailedOver"])

        clock_view = client.get(f"/managed-matches/{match_id}/rounds/1/clock").json()
        clock_seat = self._clock_seat(clock_view["seats"], "seat_1")
        self.assertEqual(clock_seat["remainingTimeMs"], 170)

    def test_failed_fallback_ends_round_but_series_continues(self) -> None:
        factory = FakeExecutorFactory(
            {
                "slow_bot": [[("per_call_timeout", 100)], [("ok", 50)]],
                "steady_bot": [[("ok", 50)], [("ok", 50)]],
                "random_bot": [[("bot_exception", 10)]],
            }
        )
        runtime_manager = ManagedMatchRuntimeManager(
            self.repository, executor_factory=factory, bot_directory=self.bot_directory
        )
        client = TestClient(create_app(repository=self.repository, runtime_manager=runtime_manager))

        with patch("ticket_to_ride.backend.runtime.round_runtime.Game", ScriptedGame):
            response = client.post(
                "/managed-matches",
                json={
                    "seats": [
                        {"seatId": "seat_1", "primaryBotId": "slow_bot"},
                        {"seatId": "seat_2", "primaryBotId": "steady_bot"},
                    ],
                    "fallbackBotId": "random_bot",
                    "roundCount": 2,
                    "timeControl": {
                        "initialTimeMs": 200,
                        "incrementMs": 20,
                        "perCallHardLimitMs": 100,
                    },
                    "timeoutPolicy": "switch_to_fallback",
                    "executionMode": "bot_api",
                },
            )

            self.assertEqual(response.status_code, 200)
            match_id = response.json()["matchId"]
            match_payload = self._wait_for_terminal_match(client, match_id)

        self.assertEqual(match_payload["status"], "completed")
        aggregate_by_seat = {entry["seatId"]: entry for entry in match_payload["aggregateResults"]}
        self.assertEqual(aggregate_by_seat["seat_1"]["runtimeFailures"], 1)
        self.assertEqual(aggregate_by_seat["seat_1"]["roundsLost"], 1)
        self.assertEqual(aggregate_by_seat["seat_1"]["roundsWon"], 1)

        round_zero = client.get(f"/managed-matches/{match_id}/rounds/0").json()
        round_one = client.get(f"/managed-matches/{match_id}/rounds/1").json()
        self.assertEqual(round_zero["status"], "failed")
        self.assertEqual(round_one["status"], "completed")
        seat_zero_round_zero = self._seat_result(round_zero["seatResults"], "seat_1")
        seat_one_round_zero = self._seat_result(round_zero["seatResults"], "seat_2")
        self.assertEqual(seat_zero_round_zero["outcome"], "runtime_failure")
        self.assertEqual(seat_one_round_zero["outcome"], "won_by_forfeit")

    def test_default_runtime_plays_action_bots_in_process(self) -> None:
        runtime_manager = ManagedMatchRuntimeManager(self.repository, bot_directory=self.bot_directory)
        client = TestClient(create_app(repository=self.repository, runtime_manager=runtime_manager))

        response = client.post(
            "/managed-matches",
            json={
                "name": "local-action-bots",
                "seats": [
                    {"seatId": "seat_1", "primaryBotId": "random_bot"},
                    {"seatId": "seat_2", "primaryBotId": "qualifier_bot"},
                ],
                "fallbackBotId": "random_bot",
                "roundCount": 1,
                "timeControl": {"initialTimeMs": 60000, "incrementMs": 0},
                "timeoutPolicy": "loss_on_time",
                "executionMode": "bot_api",
            },
        )

        self.assertEqual(response.status_code, 200)
        match = self._wait_for_terminal_match(client, response.json()["matchId"])
        self.assertEqual(match["status"], "completed")
        replay = client.get(f"/matches/{match['replayMatchId']}").json()
        self.assertGreater(len(replay["rounds"][0]["turns"]), 0)

    def _wait_for_terminal_match(self, client: TestClient, match_id: str) -> dict:
        for _ in range(200):
            response = client.get(f"/managed-matches/{match_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            if payload["status"] in {"completed", "failed", "aborted", "interrupted"}:
                return payload
            time.sleep(0.01)
        self.fail("Managed match did not reach a terminal state in time.")

    @staticmethod
    def _seat_result(seat_results: list[dict], seat_id: str) -> dict:
        return next(result for result in seat_results if result["seatId"] == seat_id)

    @staticmethod
    def _runtime_seat(seat_results: list[dict], seat_id: str) -> dict:
        return next(result for result in seat_results if result["seatId"] == seat_id)

    @staticmethod
    def _clock_seat(seat_results: list[dict], seat_id: str) -> dict:
        return next(result for result in seat_results if result["seatId"] == seat_id)


if __name__ == "__main__":
    unittest.main()
