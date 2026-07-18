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
        match_id = logger.start_match("alpha-beta", map_name="classic", seed=1234)
        logger.start_round(0)

        context = SimpleNamespace(
            player_id="bot_1",
            score=4,
            routes=[FakeRoute("Seattle-Portland-1", "Seattle-Portland-X")],
            claimed_by={"Seattle-Portland-1": "bot_1"},
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
        self.assertEqual(match_payload["mapName"], "classic")
        self.assertEqual(match_payload["seed"], 1234)
        self.assertEqual(match_payload["rounds"][0]["turns"][0]["player"]["playerId"], "bot_1")
        self.assertEqual(
            match_payload["rounds"][0]["turns"][0]["player"]["claimedRoutes"],
            [{"routeId": "Seattle-Portland-1", "routeLabel": "Seattle-Portland-X"}],
        )
        self.assertEqual(match_payload["averageScores"][0]["scores"], [4])
        self.assertEqual(match_payload["averageScores"][1]["scores"], [1])

    def test_game_logger_defaults_match_metadata_to_none(self) -> None:
        player = SimpleNamespace(
            player_id="bot_1",
            name="Alpha",
            color="red",
            trains_remaining=45,
            get_tickets=lambda: [],
            get_hand=lambda: Counter(),
        )
        logger = GameLogger([player], transport=TestClientTransport(self.client))

        match_id = logger.start_match("alpha")
        match_payload = logger.fetch_match(match_id)

        self.assertIsNone(match_payload["mapName"])
        self.assertIsNone(match_payload["seed"])


if __name__ == "__main__":
    unittest.main()
