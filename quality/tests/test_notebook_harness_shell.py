from __future__ import annotations

import unittest
from importlib.resources import files

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

    def test_composite_css_includes_embedded_widget_styles(self) -> None:
        css = SpectateShellWidget._css
        self.assertIn(".info-bar-widget", css)
        self.assertIn(".float-tooltip-kap", css)
        self.assertIn(".spectate-shell-grid", css)
        self.assertIn("container-type: inline-size", css)
        self.assertIn("@container (max-width: 760px)", css)

    def test_bundled_graph_resizes_its_canvas_to_the_shell_column(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn("new ResizeObserver(resize_to_host)", source)
        self.assertIn("Math.min(configured_width, host_content_width())", source)
        self.assertIn("measured_width > 32 ? measured_width : configured_width", source)
        self.assertIn("plot.zoomToFit(0, 20)", source)

    def test_bundled_graph_dims_only_unclaimed_routes(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn("var unclaimed_route_opacity = 0.8", source)
        self.assertIn(
            "ctx.globalAlpha = link.claimedColor ? 1 : unclaimed_route_opacity",
            source,
        )
        self.assertIn(
            ".linkOpacity((link) => link.claimedColor ? 0 : unclaimed_route_opacity)",
            source,
        )

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
        shell.playback = {"round": 10**9, "turn": 10**9}

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
