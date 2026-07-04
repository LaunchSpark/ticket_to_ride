from __future__ import annotations

import unittest

from ticket_to_ride.engine.state.map import CulledMap, MapGraph, Route, contract_map


def route(city1: str, city2: str, length: int, color: str, route_id: str) -> Route:
    return Route(city1, city2, length, color, route_id)


def triangle_routes() -> list[Route]:
    """A-B double route (parallel siblings), B-C, A-C, and a C-D spur."""
    return [
        route("A", "B", 1, "R", "A-B-1"),
        route("A", "B", 1, "G", "A-B-2"),
        route("B", "C", 2, "U", "B-C-1"),
        route("A", "C", 5, "Y", "A-C-1"),
        route("C", "D", 3, "X", "C-D-1"),
    ]


class ContractMapTests(unittest.TestCase):
    def test_no_claims_leaves_every_city_its_own_node_and_all_routes(self) -> None:
        culled = contract_map(triangle_routes(), player_count=4, claimed_by={}, player_id="me")

        self.assertEqual(sorted(culled.nodes), ["A", "B", "C", "D"])
        self.assertEqual(culled.city_to_node["A"], "A")
        self.assertEqual(len(culled.routes), 5)
        self.assertFalse(culled.connected("A", "B"))

    def test_own_claim_merges_endpoints_into_one_node(self) -> None:
        culled = contract_map(
            triangle_routes(), player_count=4, claimed_by={"A-B-1": "me"}, player_id="me"
        )

        self.assertEqual(culled.city_to_node["A"], "A+B")
        self.assertEqual(culled.city_to_node["B"], "A+B")
        self.assertEqual(culled.city_to_node["C"], "C")
        self.assertTrue(culled.connected("A", "B"))
        self.assertIn("A+B", culled.nodes)

    def test_routes_claimed_by_other_players_are_removed(self) -> None:
        culled = contract_map(
            triangle_routes(), player_count=4, claimed_by={"B-C-1": "them"}, player_id="me"
        )

        route_ids = {r.route_id for r in culled.routes}
        self.assertNotIn("B-C-1", route_ids)
        # No merging happened for "me": B and C stay separate nodes.
        self.assertFalse(culled.connected("B", "C"))

    def test_unclaimed_routes_inside_a_merged_component_are_dropped_as_self_loops(self) -> None:
        culled = contract_map(
            triangle_routes(),
            player_count=4,
            claimed_by={"A-B-1": "me", "B-C-1": "me"},
            player_id="me",
        )

        # A, B, C are one node, so the unclaimed A-C route adds no connectivity.
        route_ids = {r.route_id for r in culled.routes}
        self.assertNotIn("A-C-1", route_ids)
        self.assertIn("C-D-1", route_ids)
        self.assertEqual(culled.endpoints(next(r for r in culled.routes if r.route_id == "C-D-1")), ("A+B+C", "D"))

    def test_sibling_of_own_claim_is_removed(self) -> None:
        culled = contract_map(
            triangle_routes(), player_count=4, claimed_by={"A-B-1": "me"}, player_id="me"
        )

        route_ids = {r.route_id for r in culled.routes}
        self.assertNotIn("A-B-2", route_ids)

    def test_sibling_of_opponent_claim_is_removed_in_small_games_but_kept_in_big_ones(self) -> None:
        claimed_by = {"A-B-1": "them"}

        small = contract_map(triangle_routes(), player_count=3, claimed_by=claimed_by, player_id="me")
        big = contract_map(triangle_routes(), player_count=4, claimed_by=claimed_by, player_id="me")

        self.assertNotIn("A-B-2", {r.route_id for r in small.routes})
        self.assertIn("A-B-2", {r.route_id for r in big.routes})


class CheapestConnectionTests(unittest.TestCase):
    def test_cheapest_connection_finds_the_shortest_train_cost(self) -> None:
        culled = contract_map(triangle_routes(), player_count=4, claimed_by={}, player_id="me")

        # A-B (1) + B-C (2) beats the direct A-C (5).
        self.assertEqual(culled.cheapest_connection("A", "C"), 3)

    def test_cheapest_connection_is_zero_for_already_connected_cities(self) -> None:
        culled = contract_map(
            triangle_routes(), player_count=4, claimed_by={"A-B-1": "me"}, player_id="me"
        )

        self.assertEqual(culled.cheapest_connection("A", "B"), 0)
        # Own network is free to travel through: reaching C now costs just B-C.
        self.assertEqual(culled.cheapest_connection("A", "C"), 2)

    def test_cheapest_connection_returns_none_when_cut_off(self) -> None:
        culled = contract_map(
            triangle_routes(),
            player_count=4,
            claimed_by={"B-C-1": "them", "A-C-1": "them"},
            player_id="me",
        )

        self.assertIsNone(culled.cheapest_connection("A", "C"))
        self.assertIsNone(culled.cheapest_connection("A", "D"))


class MapGraphIntegrationTests(unittest.TestCase):
    def test_claim_route_updates_per_player_components_and_culled_map(self) -> None:
        game_map = MapGraph(player_count=4)
        claimed = next(r for r in game_map.routes if r.route_id == "Seattle-Portland-1")

        game_map.claim_route(claimed, "bot_0")

        self.assertTrue(game_map.are_connected("bot_0", "Seattle", "Portland"))
        self.assertFalse(game_map.are_connected("bot_1", "Seattle", "Portland"))

        culled = game_map.culled_map_for("bot_0")
        self.assertIsInstance(culled, CulledMap)
        self.assertTrue(culled.connected("Seattle", "Portland"))
        self.assertNotIn("Seattle-Portland-1", {r.route_id for r in culled.routes})

    def test_are_connected_is_false_for_players_with_no_claims(self) -> None:
        game_map = MapGraph(player_count=4)

        self.assertFalse(game_map.are_connected("bot_0", "Seattle", "Portland"))


if __name__ == "__main__":
    unittest.main()
