from __future__ import annotations

import random
import time
import unittest
from collections import Counter

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.logging.game_logger import GameLogger
from ticket_to_ride.runtime.cli import BootstrapRandomBot


TURN_TIMEOUT_SECONDS = 3.0
TURN_INDEX_TO_INSPECT = 5


def canonical_double_route_key(route_id: str) -> str:
    parts = route_id.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else route_id


class TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method: str, path: str, payload=None):
        response = self.client.request(method, path, json=payload)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class RandomBotMatchPerformanceTests(unittest.TestCase):
    def test_random_bot_match_turns_stay_under_three_seconds_and_turn_five_claimed_routes_are_readable(self) -> None:
        random.seed(0)
        repository = InMemoryMatchRepository()
        client = TestClient(create_app(repository=repository))

        players = [
            Player("bot_0", BootstrapRandomBot(), "random_1", "red"),
            Player("bot_1", BootstrapRandomBot(), "random_2", "blue"),
        ]
        logger = GameLogger(players, transport=TestClientTransport(client))
        match_id = logger.start_match("random_1-random_2")
        logger.start_round(0)

        context = GameContext([player.player_id for player in players])
        game = Game(context, players, logger, 0)

        turn_durations: list[float] = []
        original_next_turn = game.next_turn

        def timed_next_turn() -> None:
            start = time.perf_counter()
            original_next_turn()
            duration = time.perf_counter() - start
            turn_number = len(turn_durations)
            turn_durations.append(duration)
            self.assertLess(
                duration,
                TURN_TIMEOUT_SECONDS,
                msg=(
                    f"Turn {turn_number} took {duration:.3f}s, which exceeds the "
                    f"{TURN_TIMEOUT_SECONDS:.1f}s limit. All turn durations so far: "
                    f"{[round(value, 3) for value in turn_durations]}"
                ),
            )

        game.next_turn = timed_next_turn  # type: ignore[method-assign]
        game.play()
        logger.finalize_match()

        match_payload = logger.fetch_match(match_id)
        rounds = match_payload.get("rounds", [])
        self.assertTrue(rounds, msg=f"Expected at least one logged round for match {match_id}, but found none.")

        turns = rounds[0].get("turns", [])
        self.assertGreater(
            len(turns),
            TURN_INDEX_TO_INSPECT,
            msg=(
                f"Expected at least {TURN_INDEX_TO_INSPECT + 1} logged turns so turn "
                f"{TURN_INDEX_TO_INSPECT} could be inspected, but only found {len(turns)} turns."
            ),
        )

        turn_five = turns[TURN_INDEX_TO_INSPECT]
        player_claimed_routes = turn_five.get("player", {}).get("claimedRoutes")
        self.assertIsNotNone(
            player_claimed_routes,
            msg=(
                f"Turn {TURN_INDEX_TO_INSPECT} did not include player.claimedRoutes. "
                f"Turn payload keys: {sorted(turn_five.keys())}"
            ),
        )
        self.assertIsInstance(
            player_claimed_routes,
            list,
            msg=(
                f"Turn {TURN_INDEX_TO_INSPECT} player.claimedRoutes should be a list, "
                f"but received {type(player_claimed_routes).__name__}: {player_claimed_routes!r}"
            ),
        )
        self.assertTrue(
            all(isinstance(route_name, dict) for route_name in player_claimed_routes),
            msg=(
                f"Turn {TURN_INDEX_TO_INSPECT} player.claimedRoutes should contain route objects only, "
                f"but received: {player_claimed_routes!r}"
            ),
        )

        opponent_claimed_routes = [
            opponent.get("claimedRoutes")
            for opponent in turn_five.get("opponents", [])
        ]
        self.assertTrue(
            all(isinstance(route_list, list) for route_list in opponent_claimed_routes),
            msg=(
                f"Turn {TURN_INDEX_TO_INSPECT} opponent claimed-routes payloads should all be lists, "
                f"but received: {opponent_claimed_routes!r}"
            ),
        )
        self.assertTrue(
            all(
                isinstance(route_name, dict)
                for route_list in opponent_claimed_routes
                for route_name in route_list
            ),
            msg=(
                f"Turn {TURN_INDEX_TO_INSPECT} opponent claimed-routes payloads should contain only route objects, "
                f"but received: {opponent_claimed_routes!r}"
            ),
        )

        all_turn_five_claimed_route_names = [route["routeId"] for route in player_claimed_routes]
        for route_list in opponent_claimed_routes:
            all_turn_five_claimed_route_names.extend(route["routeId"] for route in route_list)

        self.assertIsNotNone(
            all_turn_five_claimed_route_names,
            msg=f"Unable to read claimed route names for turn {TURN_INDEX_TO_INSPECT}.",
        )

        final_turn = rounds[0]["turns"][-1]
        final_claimed_route_ids = [route["routeId"] for route in final_turn["player"]["claimedRoutes"]]
        for opponent in final_turn.get("opponents", []):
            final_claimed_route_ids.extend(route["routeId"] for route in opponent.get("claimedRoutes", []))

        grouped_parallel_routes = Counter(canonical_double_route_key(route_id) for route_id in final_claimed_route_ids)
        illegal_parallel_claims = {key: count for key, count in grouped_parallel_routes.items() if count > 1}
        self.assertFalse(
            illegal_parallel_claims,
            msg=(
                "Two-player random bot match should not allow both sides of a double route to be claimed. "
                f"Observed duplicate route groups: {illegal_parallel_claims}"
            ),
        )

        print(
            "Random bot match performance summary:",
            {
                "matchId": match_id,
                "turnCount": len(turn_durations),
                "maxTurnSeconds": round(max(turn_durations), 3),
                "turnFiveClaimedRoutes": all_turn_five_claimed_route_names,
            },
        )


if __name__ == "__main__":
    unittest.main()
