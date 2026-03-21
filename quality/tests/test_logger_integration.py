from collections import Counter
from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.repository import InMemoryMatchRepository
from ticket_to_ride.logging.game_logger import GameLogger


class TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method: str, path: str, payload=None):
        response = self.client.request(method, path, json=payload)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class FakeRoute:
    def __init__(self, route_id: str, route_label: str) -> None:
        self.route_id = route_id
        self.route_label = route_label

    def __repr__(self) -> str:
        return self.route_id


class FakeMap:
    def __init__(self, claimed_routes):
        self.claimed_routes = claimed_routes

    def get_claimed_routes(self, player_id: str):
        return self.claimed_routes.get(player_id, [])


class LoggerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        repository = InMemoryMatchRepository()
        self.client = TestClient(create_app(repository=repository))

    def test_game_logger_posts_match_rounds_turns_and_finalizes(self) -> None:
        players = [
            SimpleNamespace(
                player_id="bot_1",
                name="Alpha",
                color="red",
                trains_remaining=42,
                get_tickets=lambda: [],
                get_hand=lambda: Counter({"R": 2}),
            ),
            SimpleNamespace(
                player_id="bot_2",
                name="Beta",
                color="blue",
                trains_remaining=43,
                get_tickets=lambda: [],
                get_hand=lambda: Counter({"U": 1}),
            ),
        ]

        logger = GameLogger(players, transport=TestClientTransport(self.client))
        match_id = logger.start_match("alpha-beta")
        logger.start_round(0)

        context = SimpleNamespace(
            player_id="bot_1",
            score=4,
            map=FakeMap({"bot_1": [FakeRoute("Seattle-Portland-1", "Seattle-Portland-X")], "bot_2": []}),
            face_up_cards=["R", "G", "L", "U", "W"],
            opponents=[
                SimpleNamespace(
                    player_id="bot_2",
                    score=1,
                    remaining_trains=43,
                    destination_ticket_count=2,
                    num_cards_in_hand=4,
                    exposed_hand=Counter({"U": 1}),
                )
            ],
        )

        logger.record_turn(0, context)
        in_progress_match_payload = logger.fetch_match(match_id)
        finalize_payload = logger.finalize_match()
        match_payload = logger.fetch_match(match_id)

        self.assertEqual(in_progress_match_payload["status"], "in_progress")
        self.assertEqual(in_progress_match_payload["averageScores"][0]["scores"], [4])
        self.assertEqual(in_progress_match_payload["averageScores"][1]["scores"], [1])
        self.assertEqual(finalize_payload["matchId"], match_id)
        self.assertEqual(match_payload["status"], "completed")
        self.assertEqual(match_payload["playerNames"], ["Alpha", "Beta"])
        self.assertEqual(match_payload["rounds"][0]["turns"][0]["player"]["playerId"], "bot_1")
        self.assertEqual(
            match_payload["rounds"][0]["turns"][0]["player"]["claimedRoutes"],
            [{"routeId": "Seattle-Portland-1", "routeLabel": "Seattle-Portland-X"}],
        )
        self.assertEqual(match_payload["averageScores"][0]["scores"], [4])
        self.assertEqual(match_payload["averageScores"][1]["scores"], [1])


if __name__ == "__main__":
    unittest.main()
