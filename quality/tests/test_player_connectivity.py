from __future__ import annotations

import unittest
from types import SimpleNamespace

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import Route, contract_map


class StubInterface:
    def set_player(self, player):
        self.player = player


def make_routes() -> list[Route]:
    return [
        Route("A", "B", 1, "R", "A-B-1"),
        Route("B", "C", 2, "U", "B-C-1"),
        Route("A", "C", 5, "Y", "A-C-1"),
        Route("C", "D", 3, "X", "C-D-1"),
    ]


class FakeMap:
    """Minimal stand-in for MapGraph exposing just culled_map_for."""

    def __init__(self, routes, claimed_by=None, player_count=4):
        self.routes = routes
        self.player_count = player_count
        self.claimed_by = dict(claimed_by or {})

    def culled_map_for(self, player_id):
        return contract_map(self.routes, self.player_count, self.claimed_by, player_id)


def make_player(fake_map, tickets=(), player_id="me") -> Player:
    player = Player(player_id, StubInterface(), player_id, "red")
    player.context = SimpleNamespace(map=fake_map)
    # Tickets are normally drawn from the deck; inject directly for the test.
    player._Player__tickets.extend(tickets)
    return player


class PlayerConnectivityQueryTests(unittest.TestCase):
    def test_is_connected_and_connection_cost_reflect_the_culled_map(self) -> None:
        player = make_player(FakeMap(make_routes(), claimed_by={"A-B-1": "me"}))

        self.assertTrue(player.is_connected("A", "B"))
        self.assertFalse(player.is_connected("A", "C"))
        # Travel through the owned A-B network is free; B-C costs 2.
        self.assertEqual(player.connection_cost("A", "C"), 2)
        self.assertEqual(player.connection_cost("A", "D"), 5)

    def test_connection_cost_is_none_when_cut_off(self) -> None:
        player = make_player(
            FakeMap(make_routes(), claimed_by={"B-C-1": "them", "A-C-1": "them"})
        )

        self.assertIsNone(player.connection_cost("A", "D"))


class TicketCompletionTests(unittest.TestCase):
    def test_ticket_completes_when_the_players_network_joins_its_cities(self) -> None:
        ticket = DestinationTicket("A", "B", 4)
        player = make_player(FakeMap(make_routes(), claimed_by={"A-B-1": "me"}), tickets=[ticket])

        player.check_ticket_completion()

        self.assertTrue(ticket.is_completed)
        self.assertFalse(ticket.is_impossible)

    def test_ticket_becomes_impossible_when_cut_off_by_other_players(self) -> None:
        ticket = DestinationTicket("A", "D", 6)
        player = make_player(
            FakeMap(make_routes(), claimed_by={"B-C-1": "them", "A-C-1": "them"}),
            tickets=[ticket],
        )

        player.check_ticket_completion()

        self.assertTrue(ticket.is_impossible)
        self.assertFalse(ticket.is_completed)

    def test_ticket_becomes_impossible_when_it_costs_more_trains_than_remain(self) -> None:
        ticket = DestinationTicket("A", "D", 6)  # cheapest path costs 1+2+3 = 6 trains
        player = make_player(FakeMap(make_routes()), tickets=[ticket])
        player.trains_remaining = 5

        player.check_ticket_completion()

        self.assertTrue(ticket.is_impossible)

    def test_ticket_stays_pending_while_still_affordable(self) -> None:
        ticket = DestinationTicket("A", "D", 6)
        player = make_player(FakeMap(make_routes()), tickets=[ticket])
        player.trains_remaining = 6

        player.check_ticket_completion()

        self.assertFalse(ticket.is_completed)
        self.assertFalse(ticket.is_impossible)


class ImpossibleTicketScoringTests(unittest.TestCase):
    def make_game(self):
        context = GameContext(["me", "them"])
        players = [
            Player("me", StubInterface(), "me", "red"),
            Player("them", StubInterface(), "them", "blue"),
        ]
        game = Game(context, players, logger=None, round_number=0)
        return game, players

    def test_impossible_tickets_are_deducted_immediately(self) -> None:
        game, players = self.make_game()
        impossible = DestinationTicket("A", "B", 8)
        impossible.is_impossible = True
        pending = DestinationTicket("C", "D", 5)
        players[0]._Player__tickets.extend([impossible, pending])

        game._score_game(penalize_incomplete_tickets=False)

        # Impossible ticket counts against the score right away; the still
        # pending ticket does not until final scoring.
        self.assertEqual(game.context.get_score("me"), -8)

    def test_final_scoring_penalizes_pending_and_impossible_without_double_counting(self) -> None:
        game, players = self.make_game()
        impossible = DestinationTicket("A", "B", 8)
        impossible.is_impossible = True
        pending = DestinationTicket("C", "D", 5)
        completed = DestinationTicket("E", "F", 10)
        completed.is_completed = True
        players[0]._Player__tickets.extend([impossible, pending, completed])

        game._score_game(penalize_incomplete_tickets=True)

        self.assertEqual(game.context.get_score("me"), 10 - 8 - 5)


if __name__ == "__main__":
    unittest.main()
