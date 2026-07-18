from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_series
from notebook_harness.spectate_shell_widget import SpectateShellWidget, build_shell, update_shell


class ShellWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = initialize_series([RandomBot, RandomBot], rounds=2, seed=99)
        cls.series.play()

    def test_build_shell_seeds_static_traits_once(self) -> None:
        shell = build_shell(self.series)

        self.assertIsInstance(shell, SpectateShellWidget)
        self.assertEqual(shell.players, self.series.roster())
        self.assertEqual(shell.rounds_meta, self.series.rounds_meta())
        self.assertEqual(len(shell.aggregates), 2)
        self.assertEqual(shell.playback, {"round": 0, "turn": 0})

    def test_update_shell_pushes_step_payloads(self) -> None:
        shell = build_shell(self.series)
        shell.playback = {"round": 1, "turn": 0}

        update_shell(shell, self.series)

        self.assertEqual(shell.current_player, self.series.active_player_at(1, 0))
        self.assertEqual(shell.leaderboard, self.series.leaderboard_at(1, 0))
        self.assertIn("nodes", shell.board)
        self.assertIn("links", shell.board)
        self.assertEqual(shell.tickets, self.series.tickets_at(1, 0, shell.current_player))

    def test_update_shell_clamps_out_of_range_playback(self) -> None:
        shell = build_shell(self.series)
        shell.playback = {"round": 99, "turn": 99}

        update_shell(shell, self.series)

        self.assertEqual(shell.current_player, self.series.active_player_at(
            self.series.round_count() - 1,
            self.series.turn_count(self.series.round_count() - 1) - 1,
        ))

    def test_selected_player_switches_tickets_and_culled_board(self) -> None:
        shell = build_shell(self.series)
        shell.selected_player = "bot_1"

        update_shell(shell, self.series)

        self.assertEqual(shell.tickets, self.series.tickets_at(0, 0, "bot_1"))
