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
        self.assertEqual(shell.unclaimed_route_opacity, 0.5)
        self.assertEqual(shell.frame["round"], 0)
        self.assertEqual(shell.frame["turn"], 0)
        self.assertEqual(shell.frame["leaderboard"], shell.leaderboard)
        self.assertEqual(shell.route_usage["playerId"], "bot_0")
        self.assertFalse(shell.route_usage["winsOnly"])
        self.assertEqual(shell.route_usage["gamesIncluded"], 2)

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
        self.assertIn("const became_visible = !host_layout_ready", source)
        self.assertIn("if (changed_size || became_visible) refit_after_layout()", source)
        self.assertGreaterEqual(
            source.count("refit_frame = requestAnimationFrame(() => {"), 2
        )

    def test_bundled_graph_dims_only_unclaimed_routes(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn("var default_unclaimed_route_opacity = 0.5", source)
        self.assertIn(
            "ctx.globalAlpha = route_opacity(link)",
            source,
        )

    def test_bundled_shell_uses_inline_player_cards_without_a_modal(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn("shell-stats-card shell-player-card", source)
        self.assertIn('"Aggregate Stats"', source)
        self.assertIn('frameValue(model, "ticket_player")', source)
        self.assertNotIn("openStatsModal", source)
        self.assertIn(
            'color_with_alpha(link.color || "#999999", route_opacity(link))',
            source,
        )
        self.assertNotIn(".linkOpacity(", source)

    def test_bundled_player_hands_filter_sort_and_share_locomotive_rainbow(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        css = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.css"
        ).read_text()
        self.assertIn(".filter(([, count]) => Number(count) > 0)", source)
        self.assertIn("Number(countB) - Number(countA)", source)
        self.assertIn('frameValue(model, "market")', source)
        self.assertIn("shellCssColor(locomotiveColor)", source)
        self.assertIn(
            "linear-gradient(to right, red, orange, yellow, green, blue, indigo, violet)",
            css,
        )

    def test_bundled_shell_exposes_live_unclaimed_opacity_slider(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn('"Unclaimed opacity"', source)
        self.assertIn('.type = "range"', source)
        self.assertIn('.step = "0.05"', source)
        self.assertIn('model.set("unclaimed_route_opacity", value)', source)
        self.assertIn('model.on("change:unclaimed_route_opacity"', source)

    def test_bundled_shell_mounts_independent_route_usage_heatmap(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        css = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.css"
        ).read_text()
        self.assertIn("Route Claim Heatmap", source)
        self.assertIn("Winning games only", source)
        self.assertIn('model.set("route_usage_wins_only", checkbox.checked)', source)
        self.assertIn('data: "route_usage"', source)
        self.assertIn('selected_ids: "route_usage_selected_ids"', source)
        self.assertIn("Number.isFinite(Number(link.opacity))", source)
        self.assertIn("let local_selected_ids = []", source)
        self.assertIn('"usage usage"', css)
        self.assertIn(".shell-slot-usage", css)

    def test_bundled_playback_controls_survive_leaderboard_redraws(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn(
            'container.querySelector(":scope > .shell-sidebar-header")', source
        )
        self.assertIn('header.querySelector(".shell-play-toggle").textContent', source)
        self.assertIn(
            'board.replaceChildren(elem("p", "shell-section-heading", "Players"))',
            source,
        )
        self.assertNotIn(
            '["change:leaderboard", "change:playback", "change:aggregates"',
            source,
        )

    def test_update_shell_pushes_step_payloads(self) -> None:
        shell = build_shell(self.series)
        shell.playback = {"round": 1, "turn": 0}

        update_shell(shell, self.series)

        self.assertEqual(shell.current_player, self.series.active_player_at(1, 0))
        self.assertEqual(shell.leaderboard, self.series.leaderboard_at(1, 0))
        self.assertEqual(shell.frame["leaderboard"], shell.leaderboard)
        self.assertEqual((shell.frame["round"], shell.frame["turn"]), (1, 0))
        self.assertEqual(shell.frame["ticket_player"], shell.current_player)
        self.assertIn("nodes", shell.board)
        self.assertIn("links", shell.board)
        self.assertEqual(shell.board["layoutKey"], "__full__")
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
        self.assertEqual(shell.frame["ticket_player"], "bot_1")
        self.assertEqual(shell.board["layoutKey"], "bot_1")
        self.assertEqual(shell.route_usage["playerId"], "bot_1")

    def test_route_usage_can_filter_to_games_selected_player_won(self) -> None:
        shell = build_shell(self.series)
        shell.selected_player = "bot_1"
        shell.route_usage_wins_only = True

        update_shell(shell, self.series)

        expected_wins = next(
            entry["wins"] for entry in self.series.aggregates()
            if entry["playerId"] == "bot_1"
        )
        self.assertTrue(shell.route_usage["winsOnly"])
        self.assertEqual(shell.route_usage["playerId"], "bot_1")
        self.assertEqual(shell.route_usage["gamesIncluded"], expected_wins)
        self.assertTrue(shell.route_usage["layoutKey"].startswith("__usage__:bot_1:"))

    def test_bundled_graph_updates_preserve_force_continuity(self) -> None:
        source = files("notebook_harness").joinpath(
            "static", "spectate_shell_widget.js"
        ).read_text()
        self.assertIn("if (sameTopology)", source)
        self.assertIn("currentData.layoutKey = newData.layoutKey", source)
        self.assertIn('plot.d3Force("__continuity_probe"', source)
        self.assertIn("plot.d3AlphaDecay(1 - desired_alpha)", source)
        self.assertIn("seed_from_members(node, currentData.nodes)", source)
        self.assertIn("plot.cooldownTicks(Infinity)", source)
        self.assertNotIn("plot.cooldownTicks(0)", source)
        self.assertIn("plot.warmupTicks(0)", source)
        self.assertIn("node.vx = previous.vx", source)
        self.assertIn("node.vy = previous.vy", source)
        self.assertNotIn("node.fx = previous.fx", source)
        self.assertNotIn("node.fy = previous.fy", source)
