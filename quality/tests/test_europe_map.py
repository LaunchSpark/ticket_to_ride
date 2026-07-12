from __future__ import annotations

import unittest
from collections import Counter

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.state.decks import (
    TICKETS_CSV_PATH, TicketDeck, resolve_tickets_path,
)
from ticket_to_ride.engine.state.map import MapGraph, available_maps

from external.bots.fable_best_bot import FableBestBot
from external.bots.random_bot import RandomBot

from notebook_harness.game_runner import initialize_game


class EuropeMapDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.map_graph = MapGraph(player_count=2, map_name="europe")

    def test_europe_is_listed_and_loads_the_official_board(self) -> None:
        self.assertIn("europe", available_maps())
        self.assertEqual(len(self.map_graph.routes), 101)
        self.assertEqual(len(self.map_graph.cities()), 47)

    def test_colors_match_the_official_distribution(self) -> None:
        colors = Counter(route.color for route in self.map_graph.routes)
        self.assertEqual(colors["X"], 37)   # gray (ferries + tunnels included)
        for letter in ["R", "B", "U", "G", "O", "P", "W", "Y"]:
            self.assertEqual(colors[letter], 8, letter)

    def test_double_routes_survive_the_translation(self) -> None:
        edinburgh_london = [
            r for r in self.map_graph.routes
            if {r.city1, r.city2} == {"Edinburgh", "London"}
        ]
        self.assertEqual(sorted(r.color for r in edinburgh_london), ["B", "O"])

    def test_long_routes_are_scoreable(self) -> None:
        lengths = {route.length for route in self.map_graph.routes}
        self.assertIn(8, lengths)   # Petrograd–Stockholm
        for length in lengths:
            self.assertIn(length, Game.SCORE_TABLE)

    def test_every_ticket_city_is_on_the_board(self) -> None:
        deck = TicketDeck(resolve_tickets_path("europe"))
        cities = self.map_graph.cities()
        tickets = deck.deal_unique(len(deck))
        self.assertEqual(len(tickets), 46)   # 40 regular + 6 long
        for ticket in tickets:
            self.assertIn(ticket.city1, cities)
            self.assertIn(ticket.city2, cities)


class TicketResolutionTests(unittest.TestCase):
    def test_classic_and_unknown_maps_fall_back_to_the_shared_deck(self) -> None:
        self.assertEqual(resolve_tickets_path("classic"), TICKETS_CSV_PATH)
        self.assertEqual(resolve_tickets_path(None), TICKETS_CSV_PATH)

    def test_europe_gets_its_own_deck(self) -> None:
        path = resolve_tickets_path("europe")
        self.assertNotEqual(path, TICKETS_CSV_PATH)
        self.assertTrue(path.name == "europe.csv")


class EuropeGameTests(unittest.TestCase):
    def test_full_game_on_the_europe_map(self) -> None:
        harness_game = initialize_game(
            [FableBestBot(), RandomBot()], map_name="europe", seed=7,
        )
        harness_game.play()

        context = harness_game.game.context
        deck = context.get_train_deck()
        total = (
            len(deck) + len(deck.get_discard_pile()) + len(deck.get_face_up())
            + sum(p.get_card_count() for p in harness_game.players)
        )
        self.assertEqual(total, 110)
        claimed = [r for r in context.get_map().routes if r.claimed_by]
        self.assertGreater(len(claimed), 0)
        for player in harness_game.players:
            for ticket in player.get_tickets():
                self.assertIn(ticket.city1, context.get_map().cities())


if __name__ == "__main__":
    unittest.main()
