from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import HarnessSeries, initialize_series


class HarnessSeriesTests(unittest.TestCase):
    def test_initialize_series_builds_one_game_per_round_with_derived_seeds(self) -> None:
        series = initialize_series([RandomBot, RandomBot], rounds=2, seed=123)

        self.assertIsInstance(series, HarnessSeries)
        self.assertEqual(series.round_count(), 2)
        self.assertEqual(series.games[0].game.context.seed, 123)
        self.assertEqual(series.games[1].game.context.seed, 124)
        # Fresh bot instances per round, shared roster shape
        self.assertEqual(series.roster(), series.games[1].roster())

    def test_play_records_snapshots_for_every_round(self) -> None:
        series = initialize_series([RandomBot, RandomBot], rounds=2, seed=7)

        series.play()

        self.assertGreater(series.turn_count(0), 0)
        self.assertGreater(series.turn_count(1), 0)
        meta = series.rounds_meta()
        self.assertEqual(meta[0], {"roundNumber": 0, "turnCount": series.turn_count(0)})
        self.assertEqual(meta[1], {"roundNumber": 1, "turnCount": series.turn_count(1)})

    def test_play_reports_round_progress_after_each_completed_game(self) -> None:
        series = initialize_series([RandomBot, RandomBot], rounds=2, seed=7)
        progress = []

        series.play(on_round_complete=lambda completed, total: progress.append((completed, total)))

        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_initialize_series_rejects_zero_rounds(self) -> None:
        with self.assertRaises(ValueError):
            initialize_series([RandomBot, RandomBot], rounds=0)


class SeriesAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = initialize_series([RandomBot, RandomBot], rounds=2, seed=42)
        cls.series.play()

    def test_leaderboard_ranks_players_by_score_with_trains_left(self) -> None:
        last = self.series.turn_count(0) - 1
        board = self.series.leaderboard_at(0, last)

        self.assertEqual(len(board), 2)
        self.assertEqual(board[0]["place"], 1)
        self.assertGreaterEqual(board[0]["score"], board[1]["score"])
        for entry in board:
            self.assertIn("remainingTrains", entry)
            self.assertIn("color", entry)
            self.assertIn("name", entry)

    def test_leaderboard_ties_keep_stable_seat_order(self) -> None:
        game = self.series.games[0]
        state = game.logger.snapshots[0]["turnState"]
        for row in (state["player"], *state["opponents"]):
            row["score"] = 10

        board = game.leaderboard_at(0)

        self.assertEqual(
            [entry["playerId"] for entry in board],
            [entry["id"] for entry in game.roster()],
        )

    def test_stats_include_full_hands_for_every_player(self) -> None:
        stats = self.series.stats_at(0, 0)

        self.assertEqual(set(stats), {"bot_0", "bot_1"})
        for record in stats.values():
            self.assertEqual(
                set(record["hand"]),
                {"black", "blue", "green", "locomotive", "orange", "purple", "red", "white", "yellow"},
            )
            self.assertIsNone(record["hiddenCards"])  # omniscient in-kernel view
            for key in ("score", "remainingTrains", "ticketCount", "routeCount"):
                self.assertIn(key, record)

    def test_tickets_carry_status_and_trains_short(self) -> None:
        last = self.series.turn_count(0) - 1
        tickets = self.series.tickets_at(0, last, "bot_0")

        self.assertGreater(len(tickets), 0)
        for ticket in tickets:
            self.assertIn(ticket["status"], {"open", "completed", "cut_off"})
            if ticket["status"] == "completed":
                self.assertEqual(ticket["trainsShort"], 0)
            if ticket["status"] == "cut_off":
                self.assertIsNone(ticket["trainsShort"])

    def test_active_player_matches_snapshot_owner(self) -> None:
        snapshot = self.series.games[0].logger.snapshots[0]
        self.assertEqual(
            self.series.active_player_at(0, 0),
            snapshot["turnState"]["player"]["playerId"],
        )

    def test_aggregates_average_final_scores_and_count_wins(self) -> None:
        aggregates = self.series.aggregates()

        self.assertEqual(len(aggregates), 2)
        self.assertEqual(sum(entry["wins"] for entry in aggregates), 2)
        for entry in aggregates:
            self.assertEqual(len(entry["scores"]), 2)
            self.assertEqual(entry["bestScore"], max(entry["scores"]))
            self.assertAlmostEqual(entry["averageScore"], sum(entry["scores"]) / 2, places=1)
