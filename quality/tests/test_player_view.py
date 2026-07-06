import unittest

from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _make_players(context):
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(2)]
    for player in players:
        player.attach(context, players)
    return players


class PlayerViewTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=5)
        self.players = _make_players(self.context)

    def test_view_has_no_live_handles(self):
        view = PlayerView("p0", self.context, self.players)
        for forbidden in ("map", "train_deck", "ticket_deck"):
            self.assertFalse(hasattr(view, forbidden), forbidden)

    def test_scalars_and_copies(self):
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.player_id, "p0")
        self.assertEqual(view.trains_remaining, 45)
        self.assertEqual(view.train_cards_in_deck, len(self.context.get_train_deck()))
        self.assertEqual(view.tickets_in_deck, len(self.context.get_ticket_deck()))
        self.assertEqual(len(view.face_up_cards), 5)
        # hand is a copy: mutating it must not touch the player
        view.hand["R"] += 99
        self.assertEqual(self.players[0].get_hand().get("R", 0), 0)

    def test_claimed_by_and_culled_map(self):
        map_graph = self.context.get_map()
        route = next(r for r in map_graph.routes if map_graph.is_route_claimable(r, "p0"))
        map_graph.claim_route(route, "p0")
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.claimed_by[route.route_id], "p0")
        self.assertTrue(view.is_connected(route.city1, route.city2))
        self.assertEqual(view.connection_cost(route.city1, route.city2), 0)
        self.assertIs(view.route_by_id(route.route_id), route)

    def test_affordable_routes_matches_player(self):
        player = self.players[0]
        player.get_hand().update(["R"] * 6 + ["L"] * 2)
        view = PlayerView("p0", self.context, self.players)
        from_view = {(r.route_id, n) for r, n in view.affordable_routes()}
        from_player = {(r.route_id, n) for r, n in player.get_affordable_routes()}
        self.assertEqual(from_view, from_player)


class DrawOddsTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=9)
        self.players = _make_players(self.context)

    def test_unknown_pool_accounts_for_all_public_information(self):
        deck = self.context.get_train_deck()
        # deal real cards (not invented ones) so 110-card conservation holds
        p0_cards = [deck.draw_face_down() for _ in range(3)]
        p1_cards = [deck.draw_face_down() for _ in range(3)]
        self.players[0].get_hand().update(p0_cards)
        self.players[1].get_hand().update(p1_cards)
        self.players[1].exposed.update(p1_cards[:2])   # third card stays hidden
        deck.discard([deck.draw_face_down() for _ in range(3)])

        view = PlayerView("p0", self.context, self.players)
        pool = view.unknown_pool()

        # pool = full composition - face-up - discard - own hand - exposed
        # (mulligans during deck construction may also have discarded cards,
        # so compute the discard size instead of hardcoding 3)
        discard_size = len(deck.get_discard_pile())
        self.assertEqual(pool.total(), 110 - 5 - discard_size - 3 - 2)
        # equivalently: draw pile + p1's one hidden card
        self.assertEqual(pool.total(), len(deck) + 1)
        self.assertEqual(view.discard_pile.total(), discard_size)

    def test_draw_odds_sum_to_one(self):
        view = PlayerView("p0", self.context, self.players)
        odds = view.draw_odds()
        self.assertAlmostEqual(sum(odds.values()), 1.0)
        self.assertTrue(all(0 <= p <= 1 for p in odds.values()))

    def test_private_view_sees_true_deck_composition(self):
        from ticket_to_ride.engine.state.views import GlobalPrivateView

        deck = self.context.get_train_deck()
        composition = GlobalPrivateView(self.context, self.players).deck_composition()
        self.assertEqual(composition.total(), len(deck))
        drawn = deck.draw_face_down()
        after = GlobalPrivateView(self.context, self.players).deck_composition()
        self.assertEqual(after[drawn], composition[drawn] - 1)


if __name__ == "__main__":
    unittest.main()
