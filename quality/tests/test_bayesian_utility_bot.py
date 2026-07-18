from __future__ import annotations

import math
import unittest

from external.bots.bayesian_utility_bot import BayesianUtilityBot
from external.bots.random_bot import RandomBot
from notebook_harness.game_runner import available_bots, initialize_game
from ticket_to_ride.engine.actions import ClaimRoute, legal_turn_actions
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.views import PlayerView


class BayesianUtilityBotRegistrationTests(unittest.TestCase):
    def test_bot_is_discovered_by_metadata_loader(self) -> None:
        bots = available_bots()

        self.assertIn("Bayesian Utility Bot", bots)
        self.assertIs(bots["Bayesian Utility Bot"], BayesianUtilityBot)


class BayesianUtilityBotGameTests(unittest.TestCase):
    def test_bot_finishes_a_game_and_claims_routes(self) -> None:
        harness = initialize_game([BayesianUtilityBot(), RandomBot()], seed=8107)

        harness.play()

        self.assertGreater(harness.snapshot_count(), 0)
        self.assertTrue(
            harness.game.context.get_map().get_claimed_routes("bot_0")
        )


class BayesianUtilityModelTests(unittest.TestCase):
    def test_hypergeometric_tail_uses_finite_unknown_pool(self) -> None:
        # Four useful cards among ten, drawing two without replacement.
        expected = 1.0 - math.comb(6, 2) / math.comb(10, 2)

        self.assertAlmostEqual(
            BayesianUtilityBot._hypergeom_tail(10, 4, 2, 1), expected
        )
        self.assertEqual(BayesianUtilityBot._hypergeom_tail(10, 4, 2, 3), 0.0)

    def test_public_exposed_cards_raise_opponent_affordability(self) -> None:
        class Stub:
            def set_player(self, player):
                self.player = player

        bot = BayesianUtilityBot()
        players = [
            Player("p0", bot, "p0", "red"),
            Player("p1", Stub(), "p1", "blue"),
        ]
        context = GameContext(["p0", "p1"], seed=99)
        for player in players:
            player.attach(context, players)
        route = next(
            candidate for candidate in context.get_map().routes
            if candidate.color not in (None, "X") and candidate.length >= 2
        )

        view = PlayerView("p0", context, players)
        bot._prepare(view)
        before = bot._opponent_affordability(route, view.opponents[0])

        players[1].get_hand().update({route.color: route.length})
        players[1].exposed.update({route.color: route.length})
        view = PlayerView("p0", context, players)
        bot._prepare(view)
        after = bot._opponent_affordability(route, view.opponents[0])

        self.assertLess(before, after)
        self.assertEqual(after, 1.0)

    def test_direct_ticket_completion_beats_unrelated_legal_moves(self) -> None:
        bot = BayesianUtilityBot()
        harness = initialize_game([bot, RandomBot()], seed=411)
        player = harness.players[0]
        route = next(
            candidate for candidate in harness.game.context.get_map().routes
            if candidate.color not in (None, "X") and candidate.length >= 4
        )
        player.get_hand().update({route.color: route.length})
        player.get_tickets().append(
            DestinationTicket(route.city1, route.city2, value=20)
        )
        view = PlayerView(
            player.player_id, harness.game.context, harness.game.players
        )
        legal = legal_turn_actions(player)

        action = bot.act(view, legal)

        self.assertIsInstance(action, ClaimRoute)
        self.assertEqual(action.route_id, route.route_id)
        self.assertIn(action, legal)

    def test_mixed_cost_demands_preserve_component_colors_and_loco_floor(self) -> None:
        bot = BayesianUtilityBot()
        harness = initialize_game([bot, RandomBot()], seed=73)
        view = PlayerView("bot_0", harness.game.context, harness.game.players)
        bot._prepare(view)
        route = Route(
            "A", "B", 7, "X", "mixed-bayesian",
            cost=parse_cost("2L+3U+2R", 7),
        )

        demands = bot._payment_demands(route)

        blue = bot._COLORS.index("U")
        red = bot._COLORS.index("R")
        self.assertEqual(len(demands), 1)
        demand, floor = demands[0]
        self.assertEqual((demand[blue], demand[red]), (3, 2))
        self.assertEqual(floor, 2)


if __name__ == "__main__":
    unittest.main()
