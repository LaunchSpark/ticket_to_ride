from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_series
from notebook_harness.stored_match import StoredMatchSeries


def _payload_from_series(series) -> dict:
    """Build a GET /matches/{id}-shaped payload from played games."""
    return {
        "name": "fixture",
        "players": [
            {"playerId": player["id"], "name": player["name"], "color": player["color"]}
            for player in series.roster()
        ],
        "mapName": "classic",
        "seed": series.games[0].game.context.seed,
        "rounds": [
            {
                "roundNumber": index,
                "turns": [snapshot["turnState"] for snapshot in game.logger.snapshots],
            }
            for index, game in enumerate(series.games)
        ],
        "averageScores": [],
    }


class StoredMatchSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        live = initialize_series([RandomBot, RandomBot], rounds=2, seed=11)
        live.play()
        cls.live = live
        cls.stored = StoredMatchSeries(_payload_from_series(live))

    def test_protocol_shape_matches_live_series(self) -> None:
        self.assertEqual(self.stored.roster(), self.live.roster())
        self.assertEqual(self.stored.round_count(), 2)
        self.assertEqual(self.stored.rounds_meta(), self.live.rounds_meta())
        self.assertEqual(self.stored.active_player_at(0, 0), self.live.active_player_at(0, 0))
        self.assertEqual(self.stored.leaderboard_at(0, 3), self.live.leaderboard_at(0, 3))
        self.assertEqual(self.stored.aggregates(), self.live.aggregates())
        self.assertEqual(
            self.stored.route_usage("bot_0"), self.live.route_usage("bot_0")
        )
        self.assertEqual(
            self.stored.route_usage("bot_1", wins_only=True),
            self.live.route_usage("bot_1", wins_only=True),
        )

    def test_board_at_matches_live_series(self) -> None:
        stored_nodes, stored_edges = self.stored.board_at(0, 5)
        live_nodes, live_edges = self.live.board_at(0, 5)
        self.assertEqual(stored_nodes, live_nodes)
        self.assertEqual(stored_edges, live_edges)

    def test_market_is_snapshot_only(self) -> None:
        market = self.stored.market_at(0, 0)
        self.assertEqual(market["pie"], [])
        self.assertIsNone(market["deck_count"])
        self.assertIsNone(market["discard_count"])
        self.assertEqual(
            market["face_up"],
            self.live.games[0].logger.snapshots[0]["turnState"]["gameObjects"]["decks"][
                "marketCards"
            ],
        )

    def test_stats_expose_partial_opponent_hands(self) -> None:
        stats = self.stored.stats_at(0, 0)
        active = self.stored.active_player_at(0, 0)
        other = next(player_id for player_id in stats if player_id != active)
        self.assertIsNone(stats[active]["hiddenCards"])
        self.assertIsInstance(stats[other]["hiddenCards"], int)

    def test_tickets_fall_back_to_latest_owned_snapshot(self) -> None:
        active = self.stored.active_player_at(0, 0)
        tickets = self.stored.tickets_at(0, 0, active)
        self.assertGreater(len(tickets), 0)
        for ticket in tickets:
            self.assertIn(ticket["status"], {"open", "completed"})
            self.assertIsNone(ticket["trainsShort"])


if __name__ == "__main__":
    unittest.main()
