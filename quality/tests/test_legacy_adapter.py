import unittest
from collections import Counter
from types import SimpleNamespace

from ticket_to_ride.engine.actions import (
    ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets,
)
from ticket_to_ride.engine.legacy_adapter import LegacyBotAdapter


def _view(decision, **kwargs):
    defaults = {"decision": decision, "hand": Counter(), "ticket_offer": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class _LegacyBot:
    def __init__(self, turn=1, draw=-1, keep=None):
        self._turn, self._draw, self._keep = turn, draw, keep
    def set_player(self, player):
        self.player = player
    def choose_turn_action(self):
        return self._turn
    def choose_draw_train_action(self):
        return self._draw
    def choose_route_to_claim(self, claimable_routes):
        return claimable_routes[0]
    def choose_color_to_spend(self, route, color_options):
        return color_options[0]
    def select_ticket_offer(self, offer):
        return self._keep(offer) if self._keep else offer[:2]


class AdapterTests(unittest.TestCase):
    def test_draw_choice_maps_to_face_up(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=1, draw=2))
        legal = [DrawBlind(), DrawFaceUp(0, "R"), DrawFaceUp(2, "G"), DrawTickets()]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawFaceUp(2, "G"))

    def test_invalid_draw_index_falls_back_to_blind(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=1, draw=4))
        legal = [DrawBlind(), DrawFaceUp(0, "R")]
        self.assertEqual(adapter.act(_view("draw_second"), legal), DrawBlind())

    def test_claim_choice_resolves_color(self):
        route = SimpleNamespace(route_id="A-B-1", color="X", length=2)
        adapter = LegacyBotAdapter(_LegacyBot(turn=2))
        legal = [
            ClaimRoute("A-B-1", "R", 0),
            ClaimRoute("A-B-1", "G", 0),
            DrawBlind(),
        ]
        view = _view("turn", route_by_id=lambda rid: route, hand=Counter({"R": 2, "G": 2}))
        chosen = adapter.act(view, legal)
        self.assertIsInstance(chosen, ClaimRoute)
        self.assertEqual(chosen.color, "R")  # legacy bot picked color_options[0]

    def test_keep_maps_tickets_to_indices(self):
        t = [SimpleNamespace(value=i) for i in range(3)]
        adapter = LegacyBotAdapter(_LegacyBot(keep=lambda offer: [offer[0], offer[2]]))
        legal = [KeepTickets((0, 1)), KeepTickets((0, 2)), KeepTickets((1, 2)), KeepTickets((0, 1, 2))]
        self.assertEqual(adapter.act(_view("keep_tickets", ticket_offer=t), legal), KeepTickets((0, 2)))

    def test_keep_below_minimum_upgrades_to_superset(self):
        t = [SimpleNamespace(value=i) for i in range(3)]
        adapter = LegacyBotAdapter(_LegacyBot(keep=lambda offer: [offer[1]]))
        legal = [KeepTickets((0, 1)), KeepTickets((1, 2)), KeepTickets((0, 1, 2))]
        chosen = adapter.act(_view("keep_tickets", ticket_offer=t), legal)
        self.assertIn(1, chosen.indices)
        self.assertEqual(len(chosen.indices), 2)

    def test_ticket_turn_choice(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=3))
        legal = [DrawBlind(), DrawTickets()]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawTickets())

    def test_claim_wanted_but_unavailable_falls_to_draw(self):
        adapter = LegacyBotAdapter(_LegacyBot(turn=2, draw=-1))
        legal = [DrawBlind(), DrawFaceUp(0, "R")]
        self.assertEqual(adapter.act(_view("turn"), legal), DrawBlind())


if __name__ == "__main__":
    unittest.main()
