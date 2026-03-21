from __future__ import annotations

import unittest
from unittest.mock import patch

from ticket_to_ride.backend.pocketbase import PocketBaseMatchRepository


class PocketBaseRepositoryTests(unittest.TestCase):
    def test_list_matches_fetches_all_pages_and_sorts_locally(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")
        page_one = {
            "page": 1,
            "perPage": 1,
            "totalItems": 2,
            "totalPages": 2,
            "items": [
                {
                    "id": "older",
                    "name": "older-match",
                    "players": [],
                    "status": "completed",
                    "averageScores": [],
                    "created": "2026-03-19 20:00:00.000Z",
                },
            ],
        }
        page_two = {
            "page": 2,
            "perPage": 1,
            "totalItems": 2,
            "totalPages": 2,
            "items": [
                {
                    "id": "newer",
                    "name": "newer-match",
                    "players": [],
                    "status": "completed",
                    "averageScores": [],
                    "created": "2026-03-19 21:00:00.000Z",
                },
            ],
        }

        with patch.object(repository, "_request_json", side_effect=[page_one, page_two]) as request_json:
            matches = repository.list_matches()

        self.assertEqual(
            request_json.call_args_list,
            [
                unittest.mock.call(
                    "GET",
                    "/api/collections/matches/records",
                    query={"page": 1, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
                unittest.mock.call(
                    "GET",
                    "/api/collections/matches/records",
                    query={"page": 2, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
            ],
        )
        self.assertEqual([match["id"] for match in matches], ["newer", "older"])

    def test_get_round_records_fetches_all_pages(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")

        with patch.object(
            repository,
            "_request_json",
            side_effect=[
                {
                    "page": 1,
                    "perPage": 1,
                    "totalItems": 2,
                    "totalPages": 2,
                    "items": [{"id": "r1", "match_id": "m1", "round_number": 1}],
                },
                {
                    "page": 2,
                    "perPage": 1,
                    "totalItems": 2,
                    "totalPages": 2,
                    "items": [{"id": "r2", "match_id": "m1", "round_number": 2}],
                },
            ],
        ) as request_json:
            rounds = repository.get_round_records("m1")

        self.assertEqual([round_record["roundNumber"] for round_record in rounds], [0, 1])
        self.assertEqual(
            request_json.call_args_list,
            [
                unittest.mock.call(
                    "GET",
                    "/api/collections/rounds/records",
                    query={"filter": 'match_id="m1"', "sort": "round_number", "page": 1, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
                unittest.mock.call(
                    "GET",
                    "/api/collections/rounds/records",
                    query={"filter": 'match_id="m1"', "sort": "round_number", "page": 2, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
            ],
        )

    def test_get_turn_records_fetches_all_pages_in_order(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")

        with patch.object(
            repository,
            "_request_json",
            side_effect=[
                {
                    "page": 1,
                    "perPage": 2,
                    "totalItems": 3,
                    "totalPages": 2,
                    "items": [
                        {"id": "t1", "match_id": "m1", "round_id": "r1", "turn_index": 1, "turn_state": {"n": 0}},
                        {"id": "t2", "match_id": "m1", "round_id": "r1", "turn_index": 2, "turn_state": {"n": 1}},
                    ],
                },
                {
                    "page": 2,
                    "perPage": 2,
                    "totalItems": 3,
                    "totalPages": 2,
                    "items": [
                        {"id": "t3", "match_id": "m1", "round_id": "r1", "turn_index": 3, "turn_state": {"n": 2}},
                    ],
                },
            ],
        ) as request_json:
            turns = repository.get_turn_records("r1")

        self.assertEqual([turn["turnIndex"] for turn in turns], [0, 1, 2])
        self.assertEqual(turns[2]["turnState"], {"n": 2})
        self.assertEqual(
            request_json.call_args_list,
            [
                unittest.mock.call(
                    "GET",
                    "/api/collections/turns/records",
                    query={"filter": 'round_id="r1"', "sort": "turn_index", "page": 1, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
                unittest.mock.call(
                    "GET",
                    "/api/collections/turns/records",
                    query={"filter": 'round_id="r1"', "sort": "turn_index", "page": 2, "perPage": repository.RECORDS_PAGE_SIZE},
                ),
            ],
        )

    def test_create_round_offsets_zero_based_round_number_for_pocketbase(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")

        with patch.object(repository, "_request_json", return_value={"id": "round-1"}) as request_json:
            round_id = repository.create_round("match-1", 0)

        self.assertEqual(round_id, "round-1")
        request_json.assert_called_once_with(
            "POST",
            "/api/collections/rounds/records",
            {
                "match_id": "match-1",
                "round_number": 1,
                "turn_count": 0,
            },
        )

    def test_create_turn_offsets_zero_based_turn_index_for_pocketbase(self) -> None:
        repository = PocketBaseMatchRepository("http://127.0.0.1:8090")
        turn_state = {
            "player": {
                "playerId": "bot_1",
                "score": 5,
                "remainingTrains": 42,
                "claimedRoutes": [],
                "destinationTickets": [],
                "hand": {},
            },
            "opponents": [],
            "gameObjects": {"decks": {"marketCards": ["R", "G", "L", "U", "W"]}},
        }

        with patch.object(repository, "_request_json", side_effect=[{"id": "turn-1"}, {}]) as request_json:
            turn_id = repository.create_turn("match-1", "round-1", 0, turn_state)

        self.assertEqual(turn_id, "turn-1")
        self.assertEqual(
            request_json.call_args_list[0].args,
            (
                "POST",
                "/api/collections/turns/records",
                {
                    "match_id": "match-1",
                    "round_id": "round-1",
                    "turn_index": 1,
                    "active_player_id": "bot_1",
                    "active_player_score": 5,
                    "active_player_remaining_trains": 42,
                    "active_player_claimed_routes": [],
                    "active_player_destination_tickets": [],
                    "active_player_hand": {},
                    "opponents": [],
                    "market_cards": ["R", "G", "L", "U", "W"],
                    "turn_state": turn_state,
                },
            ),
        )
        self.assertEqual(
            request_json.call_args_list[1].args,
            (
                "PATCH",
                "/api/collections/rounds/records/round-1",
                {"turn_count": 1},
            ),
        )

    def test_normalized_round_and_turn_records_decode_zero_based_indexes(self) -> None:
        self.assertEqual(
            PocketBaseMatchRepository._normalize_round({"id": "r1", "match_id": "m1", "round_number": 1}),
            {"id": "r1", "matchId": "m1", "roundNumber": 0},
        )
        self.assertEqual(
            PocketBaseMatchRepository._normalize_turn(
                {"id": "t1", "match_id": "m1", "round_id": "r1", "turn_index": 1, "turn_state": {}}
            ),
            {"id": "t1", "matchId": "m1", "roundId": "r1", "turnIndex": 0, "turnState": {}},
        )


if __name__ == "__main__":
    unittest.main()
