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

    def test_initialize_series_rejects_zero_rounds(self) -> None:
        with self.assertRaises(ValueError):
            initialize_series([RandomBot, RandomBot], rounds=0)
