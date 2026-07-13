from __future__ import annotations

import unittest

from external.bots.codex_best_bot import CodexBestBot
from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import available_bots, initialize_game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


class CodexBestBotRegistrationTests(unittest.TestCase):
    def test_codex_best_bot_is_discovered_by_the_loader(self) -> None:
        bots = available_bots()
        self.assertIn("Codex Best Bot", bots)
        self.assertEqual(bots["Codex Best Bot"].__name__, "CodexBestBot")


class CodexBestBotGameTests(unittest.TestCase):
    def test_codex_best_bot_plays_a_full_game_and_claims_routes(self) -> None:
        harness_game = initialize_game([CodexBestBot(), RandomBot()], seed=17)

        harness_game.play()

        self.assertGreater(harness_game.snapshot_count(), 0)
        claimed = harness_game.game.context.get_map().get_claimed_routes("bot_0")
        self.assertGreater(len(claimed), 0)


class CodexBestBotHeuristicTests(unittest.TestCase):
    def setUp(self) -> None:
        class _Stub:
            def set_player(self, player):
                self.player = player

        self.bot = CodexBestBot()
        self.players = [
            Player("p0", self.bot, "p0", "red"),
            Player("p1", _Stub(), "p1", "blue"),
        ]
        self.context = GameContext(["p0", "p1"], seed=23)
        for player in self.players:
            player.attach(self.context, self.players)
        self._prime()

    def _prime(self) -> PlayerView:
        view = PlayerView("p0", self.context, self.players)
        self.bot._prime_view(view)
        return view

    def test_claim_priority_grabs_fragile_short_link_before_big_replaceable_route(self) -> None:
        view = self._prime()
        short = next(route for route in view.routes if route.length == 1)
        long = next(route for route in view.routes if route.length >= 5)

        def fake_replan():
            self.bot._planned_routes = [short, long]
            self.bot._planned_route_ids = {short.route_id, long.route_id}
            return self.bot._planned_routes

        self.bot._replan = fake_replan
        self.bot._route_pressure = (
            lambda route: float("inf") if route.route_id == short.route_id else 0.0
        )

        route, _ = self.bot._choose_route_pick([(long, 0), (short, 0)])

        self.assertEqual(route, short)

    def test_score_mode_claims_best_point_route_when_no_tickets_are_pending(self) -> None:
        view = self._prime()
        short = next(route for route in view.routes if route.length == 1)
        long = next(route for route in view.routes if route.length >= 5)

        route, _ = self.bot._choose_route_pick([(short, 0), (long, 0)])

        self.assertEqual(route, long)


if __name__ == "__main__":
    unittest.main()
