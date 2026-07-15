"""PlayerView exposures of engine-maintained public metrics: longest-path
standings, per-ticket remaining costs, and per-player claim components."""
import unittest

from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.decks import DestinationTicket
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _make_players(context, count=2):
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(count)]
    for player in players:
        player.attach(context, players)
    return players


def _claim(map_graph, route, player_id):
    """Claim as the engine does: board mutation plus longest-path tracking."""
    map_graph.claim_route(route, player_id)
    map_graph.update_longest_path(player_id, route)


def _adjacent_pair(map_graph, player_id):
    """Two claimable routes sharing a city (three distinct cities total)."""
    for first in map_graph.get_available_routes(player_id):
        for second in map_graph.get_available_routes(player_id):
            shared = first.get_cities() & second.get_cities()
            if second is not first and len(shared) == 1 \
                    and len(first.get_cities() | second.get_cities()) == 3:
                return first, second
    raise AssertionError("no adjacent claimable route pair found")


class LongestPathExposureTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=17)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_fresh_game_has_no_holder_and_zero_lengths(self):
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.longest_path_holder, "")
        self.assertEqual(view.longest_paths, {"p0": 0, "p1": 0})

    def test_standings_reflect_claims_for_every_seat(self):
        route = self.map.get_available_routes("p1")[0]
        _claim(self.map, route, "p1")
        for viewer in ("p0", "p1"):
            view = PlayerView(viewer, self.context, self.players)
            self.assertEqual(view.longest_path_holder, "p1")
            self.assertEqual(view.longest_paths["p1"], route.length)
            self.assertEqual(view.longest_paths["p0"], 0)


class TicketCostExposureTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=17)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_costs_align_with_tickets_and_connection_cost(self):
        route = self.map.get_available_routes("p0")[0]
        self.players[0].get_tickets().append(
            DestinationTicket(route.city1, route.city2, 5))
        view = PlayerView("p0", self.context, self.players)
        costs = view.ticket_costs()
        self.assertEqual(len(costs), len(view.tickets))
        self.assertEqual(costs[0], view.connection_cost(route.city1, route.city2))
        self.assertEqual(costs[0], route.length)  # direct route = its length

    def test_zero_cost_matches_engine_completion_judgment(self):
        route = self.map.get_available_routes("p0")[0]
        ticket = DestinationTicket(route.city1, route.city2, 5)
        self.players[0].get_tickets().append(ticket)
        _claim(self.map, route, "p0")
        view = PlayerView("p0", self.context, self.players)
        self.assertEqual(view.ticket_costs()[0], 0)
        self.players[0].check_ticket_completion()
        self.assertTrue(ticket.is_completed)

    def test_costs_memoized_and_copy_safe(self):
        route = self.map.get_available_routes("p0")[0]
        self.players[0].get_tickets().append(
            DestinationTicket(route.city1, route.city2, 5))
        view = PlayerView("p0", self.context, self.players)
        first = view.ticket_costs()
        first[0] = -99  # caller mutates their copy
        self.assertNotEqual(view.ticket_costs()[0], -99)


class ClaimComponentExposureTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=17)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_adjacent_claims_merge_into_one_component(self):
        first, second = _adjacent_pair(self.map, "p0")
        _claim(self.map, first, "p0")
        _claim(self.map, second, "p0")
        cities = sorted(first.get_cities() | second.get_cities())
        # claims are public: p0's network is visible from every seat
        for viewer in ("p0", "p1"):
            view = PlayerView(viewer, self.context, self.players)
            self.assertEqual(view.claim_components("p0"), [cities])
            self.assertEqual(view.claim_components("p1"), [])
        # default argument is the view's own seat
        own_view = PlayerView("p0", self.context, self.players)
        self.assertEqual(own_view.claim_components(), [cities])

    def test_components_come_from_the_view_snapshot(self):
        view = PlayerView("p0", self.context, self.players)
        route = self.map.get_available_routes("p0")[0]
        _claim(self.map, route, "p0")  # after the snapshot
        self.assertEqual(view.claim_components("p0"), [])
        fresh = PlayerView("p0", self.context, self.players)
        self.assertEqual(fresh.claim_components("p0"),
                         [sorted(route.get_cities())])


if __name__ == "__main__":
    unittest.main()
