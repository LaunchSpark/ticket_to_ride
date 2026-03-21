import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ticket_to_ride.backend.app import create_app
from ticket_to_ride.backend.pocketbase import PocketBaseError
from ticket_to_ride.backend.pocketbase import PocketBaseMatchRepository
from ticket_to_ride.backend.repository import InMemoryMatchRepository


TURN_ONE = {
    "player": {
        "playerId": "bot_1",
        "score": 5,
        "remainingTrains": 42,
        "claimedRoutes": [],
        "destinationTickets": [],
        "hand": {
            "black": 0,
            "blue": 0,
            "green": 0,
            "locomotive": 1,
            "orange": 0,
            "purple": 0,
            "red": 2,
            "white": 0,
            "yellow": 0,
        },
    },
    "opponents": [
        {
            "playerId": "bot_2",
            "score": 3,
            "remainingTrains": 43,
            "claimedRoutes": [],
            "destinationTicketCount": 2,
            "hand": {
                "public": {
                    "black": 0,
                    "blue": 1,
                    "green": 0,
                    "locomotive": 0,
                    "orange": 0,
                    "purple": 0,
                    "red": 0,
                    "white": 0,
                    "yellow": 0,
                },
                "hidden": 4,
            },
        }
    ],
    "gameObjects": {"decks": {"marketCards": ["R", "G", "L", "U", "W"]}},
}

TURN_TWO = {
    "player": {
        "playerId": "bot_2",
        "score": 7,
        "remainingTrains": 40,
        "claimedRoutes": [{"routeId": "Helena-Denver-1", "routeLabel": "Helena-Denver-G"}],
        "destinationTickets": [],
        "hand": {
            "black": 0,
            "blue": 1,
            "green": 0,
            "locomotive": 0,
            "orange": 0,
            "purple": 0,
            "red": 0,
            "white": 0,
            "yellow": 1,
        },
    },
    "opponents": [
        {
            "playerId": "bot_1",
            "score": 5,
            "remainingTrains": 42,
            "claimedRoutes": [],
            "destinationTicketCount": 2,
            "hand": {
                "public": {
                    "black": 0,
                    "blue": 0,
                    "green": 0,
                    "locomotive": 1,
                    "orange": 0,
                    "purple": 0,
                    "red": 2,
                    "white": 0,
                    "yellow": 0,
                },
                "hidden": 3,
            },
        }
    ],
    "gameObjects": {"decks": {"marketCards": ["B", "G", "L", "U", "W"]}},
}


class MatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMatchRepository()
        self.client = TestClient(create_app(repository=self.repository))

    def test_list_matches_is_empty_before_any_match_is_created(self) -> None:
        response = self.client.get("/matches")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_match_lifecycle_and_payload_shape(self) -> None:
        create_response = self.client.post(
            "/matches",
            json={
                "name": "alpha-beta",
                "players": [
                    {"playerId": "bot_1", "name": "Alpha", "color": "red"},
                    {"playerId": "bot_2", "name": "Beta", "color": "blue"},
                ],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        match_id = create_response.json()["matchId"]

        round_response = self.client.post(f"/matches/{match_id}/rounds", json={"roundNumber": 0})
        self.assertEqual(round_response.status_code, 200)
        round_id = round_response.json()["roundId"]

        turn_one_response = self.client.post(
            f"/matches/{match_id}/rounds/{round_id}/turns",
            json={"turnIndex": 0, "turnState": TURN_ONE},
        )
        turn_two_response = self.client.post(
            f"/matches/{match_id}/rounds/{round_id}/turns",
            json={"turnIndex": 1, "turnState": TURN_TWO},
        )
        self.assertEqual(turn_one_response.status_code, 200)
        self.assertEqual(turn_two_response.status_code, 200)

        in_progress_match_response = self.client.get(f"/matches/{match_id}")
        self.assertEqual(in_progress_match_response.status_code, 200)
        in_progress_match_payload = in_progress_match_response.json()
        self.assertEqual(in_progress_match_payload["status"], "in_progress")
        self.assertEqual(in_progress_match_payload["playerNames"], ["Alpha", "Beta"])
        self.assertEqual(in_progress_match_payload["averageScores"][0]["scores"], [5, 5])
        self.assertEqual(in_progress_match_payload["averageScores"][1]["scores"], [3, 7])

        finalize_response = self.client.post(f"/matches/{match_id}/finalize")
        self.assertEqual(finalize_response.status_code, 200)
        finalized_payload = finalize_response.json()
        self.assertEqual(finalized_payload["status"], "completed")
        self.assertEqual(finalized_payload["averageScores"][0]["scores"], [5, 5])
        self.assertEqual(finalized_payload["averageScores"][1]["scores"], [3, 7])

        list_response = self.client.get("/matches")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()[0]["matchId"], match_id)
        self.assertEqual(list_response.json()[0]["playerNames"], ["Alpha", "Beta"])

        match_response = self.client.get(f"/matches/{match_id}")
        self.assertEqual(match_response.status_code, 200)
        match_payload = match_response.json()
        self.assertEqual(match_payload["playerNames"], ["Alpha", "Beta"])
        self.assertEqual(match_payload["players"][0]["name"], "Alpha")
        self.assertEqual(match_payload["rounds"][0]["turns"][1]["player"]["playerId"], "bot_2")
        self.assertEqual(match_payload["averageScores"][1]["scores"], [3, 7])

    def test_pocketbase_errors_are_returned_as_service_unavailable(self) -> None:
        class FailingRepository(InMemoryMatchRepository):
            def list_matches(self):
                raise PocketBaseError("PocketBase request failed: connection refused")

        client = TestClient(create_app(repository=FailingRepository()))
        response = client.get("/matches")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["service"], "pocketbase")

    def test_match_payload_includes_turns_beyond_first_pocketbase_page(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")
        client = TestClient(create_app(repository=repository))

        turn_records_page_one = []
        for turn_index in range(30):
            turn_records_page_one.append(
                {
                    "id": f"turn-{turn_index}",
                    "match_id": "match-1",
                    "round_id": "round-1",
                    "turn_index": turn_index + 1,
                    "turn_state": {
                        **TURN_ONE,
                        "player": {
                            **TURN_ONE["player"],
                            "score": turn_index,
                        },
                    },
                }
            )

        turn_record_page_two = {
            "id": "turn-30",
            "match_id": "match-1",
            "round_id": "round-1",
            "turn_index": 31,
            "turn_state": {
                **TURN_TWO,
                "player": {
                    **TURN_TWO["player"],
                    "score": 999,
                },
            },
        }

        with patch.object(
            repository,
            "_request_json",
            side_effect=[
                {
                    "id": "match-1",
                    "name": "paged-match",
                    "players": [
                        {"playerId": "bot_1", "name": "Alpha", "color": "red"},
                        {"playerId": "bot_2", "name": "Beta", "color": "blue"},
                    ],
                    "status": "completed",
                    "averageScores": [],
                    "created": "2026-03-20 00:00:00.000Z",
                },
                {
                    "page": 1,
                    "perPage": 30,
                    "totalItems": 1,
                    "totalPages": 1,
                    "items": [{"id": "round-1", "match_id": "match-1", "round_number": 1}],
                },
                {
                    "page": 1,
                    "perPage": 30,
                    "totalItems": 31,
                    "totalPages": 2,
                    "items": turn_records_page_one,
                },
                {
                    "page": 2,
                    "perPage": 30,
                    "totalItems": 31,
                    "totalPages": 2,
                    "items": [turn_record_page_two],
                },
            ],
        ):
            response = client.get("/matches/match-1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rounds"][0]["turns"]), 31)
        self.assertEqual(payload["rounds"][0]["turns"][30]["player"]["score"], 999)


if __name__ == "__main__":
    unittest.main()
