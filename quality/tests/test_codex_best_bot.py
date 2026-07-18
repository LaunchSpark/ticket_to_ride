from __future__ import annotations

import unittest
from collections import Counter

from external.bots.codex_best_bot import CodexBestBot
from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import available_bots, initialize_game
from ticket_to_ride.engine.actions import ClaimRoute
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import Route
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

    def test_portfolio_values_bycatch_for_a_later_route(self) -> None:
        red = Route("A", "B", 2, "R", "portfolio-red")
        blue = Route("B", "C", 3, "U", "portfolio-blue")
        self.bot._odds = {color: 0.1 for color in self.bot._CARD_COLORS}
        self.bot._odds["L"] = 0.1
        self.bot._blind_draw_cache.clear()
        self.bot._portfolio_cache.clear()

        useful = self.bot._portfolio_expected_turns(
            [red, blue], Counter({"R": 2, "U": 1}), face_up_cards=()
        )
        irrelevant = self.bot._portfolio_expected_turns(
            [red, blue], Counter({"R": 2, "G": 1}), face_up_cards=()
        )

        self.assertLess(useful, irrelevant)

    def test_path_weight_is_structural_not_repriced_from_the_hand(self) -> None:
        route = next(candidate for candidate in self._prime().routes if candidate.length >= 4)
        before = self.bot._route_cost(route)
        self.players[0].get_hand().update({route.color or "R": route.length, "L": 3})
        self._prime()

        self.assertEqual(self.bot._route_cost(route), before)
        self.assertEqual(before, self.bot._route_points(route))

    def test_mixed_components_are_aggregated_without_collapsing_colors(self) -> None:
        mixed = Route(
            "A", "B", 5, "X", "mixed",
            cost=parse_cost("3U+2R", 5),
        )

        demand, locomotive_floor = self.bot._portfolio_requirements(
            [mixed], Counter(), ()
        )

        self.assertEqual(demand, Counter({"U": 3, "R": 2}))
        self.assertEqual(locomotive_floor, 0)

    def test_claim_payment_preserves_wilds_for_the_remaining_portfolio(self) -> None:
        view = self._prime()
        route = next(
            candidate for candidate in view.routes
            if candidate.color in self.bot._CARD_COLORS and candidate.length >= 2
        )
        future_color = next(
            color for color in self.bot._CARD_COLORS if color != route.color
        )
        future = Route("Future A", "Future B", route.length, future_color, "future")
        hand = self.players[0].get_hand()
        hand.clear()
        hand.update({route.color: route.length, "L": route.length})
        view = self._prime()

        def fake_replan():
            self.bot._planned_routes = [route, future]
            self.bot._planned_route_ids = {route.route_id, future.route_id}
            return self.bot._planned_routes

        self.bot._replan = fake_replan
        colored = ClaimRoute(route.route_id, route.color, 0)
        wild = ClaimRoute(route.route_id, "L", route.length)

        chosen = self.bot._claim_action(view, [wild, colored])

        self.assertEqual(chosen, colored)


if __name__ == "__main__":
    unittest.main()
