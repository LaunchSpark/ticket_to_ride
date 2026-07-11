from __future__ import annotations

import unittest

from external.bots.qualifier_bot import QualifierBot
from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import available_bots, initialize_game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


class QualifierBotRegistrationTests(unittest.TestCase):
    def test_qualifier_bot_is_discovered_by_the_loader(self) -> None:
        bots = available_bots()
        self.assertIn("Qualifier Bot", bots)
        self.assertEqual(bots["Qualifier Bot"].__name__, "QualifierBot")


class QualifierBotGameTests(unittest.TestCase):
    def test_qualifier_bot_plays_a_full_game_and_claims_routes(self) -> None:
        harness_game = initialize_game([QualifierBot(), RandomBot()], seed=17)

        harness_game.play()

        self.assertGreater(harness_game.snapshot_count(), 0)
        claimed = harness_game.game.context.get_map().get_claimed_routes("bot_0")
        self.assertGreater(len(claimed), 0)


class RouteCostTests(unittest.TestCase):
    """_route_cost: risk-adjusted expected turns to assemble and claim."""

    def setUp(self) -> None:
        class _Stub:
            def set_player(self, player):
                self.player = player

        self.bot = QualifierBot()
        self.players = [
            Player("p0", self.bot, "p0", "red"),
            Player("p1", _Stub(), "p1", "blue"),
        ]
        self.context = GameContext(["p0", "p1"], seed=23)
        for player in self.players:
            player.attach(self.context, self.players)
        self._prime()

    def _prime(self) -> PlayerView:
        """Build a fresh view and prime the bot's per-decision caches the
        same way act() does."""
        view = PlayerView("p0", self.context, self.players)
        self.bot._prime_view(view)
        return view

    def _sibling_free_route(self, view, min_length: int = 3):
        return next(
            route for route in view.routes
            if route.color != "X"
            and route.length >= min_length
            and len(self.bot._siblings_by_key[route.sibling_group_key()]) == 1
        )

    def test_matching_cards_in_hand_make_a_route_cheaper(self) -> None:
        view = self._prime()
        route = self._sibling_free_route(view)
        baseline = self.bot._route_cost(route)

        self.players[0].get_hand().update([route.color] * route.length)
        self._prime()

        affordable_cost = self.bot._route_cost(route)
        self.assertLess(affordable_cost, baseline)
        # nothing left to draw: the cost is exactly the claim turn
        self.assertEqual(affordable_cost, 1.0)

    def test_double_routes_price_in_the_closure_risk(self) -> None:
        view = self._prime()
        double = next(
            route for route in view.routes
            if len(self.bot._siblings_by_key[route.sibling_group_key()]) > 1
        )
        risky = self.bot._route_cost(double)

        # pretend the twin does not exist: the risk multiplier must vanish
        self.bot._siblings_by_key[double.sibling_group_key()] = [double]
        base = self.bot._route_cost(double)

        self.assertAlmostEqual(risky, base * QualifierBot._DOUBLE_ROUTE_RISK)

    def test_exhausted_color_is_unbuildable(self) -> None:
        view = self._prime()
        route = self._sibling_free_route(view)
        # every copy of the color is publicly accounted for: none in the
        # market, none unseen -> the route cannot be assembled
        self.bot._odds = {c: p for c, p in self.bot._odds.items() if c != route.color}
        self.bot._odds["L"] = 0.0
        self.bot._view.face_up_cards = [
            card for card in self.bot._view.face_up_cards if card != route.color
        ]

        self.assertEqual(self.bot._route_cost(route), float("inf"))


if __name__ == "__main__":
    unittest.main()
