from __future__ import annotations

import unittest

from ticket_to_ride.engine.state.map import MapGraph, Route, contract_map

from notebook_harness.rendering import (
    build_culled_edges,
    build_culled_nodes,
    build_edges,
    build_nodes,
    claimed_by_from_snapshot,
)


def make_turn_state(player_id, player_claimed, opponents):
    return {
        "player": {
            "playerId": player_id,
            "claimedRoutes": [{"routeId": route_id, "routeLabel": route_id} for route_id in player_claimed],
        },
        "opponents": [
            {
                "playerId": opponent_id,
                "claimedRoutes": [{"routeId": route_id, "routeLabel": route_id} for route_id in claimed],
            }
            for opponent_id, claimed in opponents
        ],
    }


class RenderingTests(unittest.TestCase):
    def test_build_nodes_returns_one_node_per_city(self) -> None:
        game_map = MapGraph(player_count=2)

        nodes = build_nodes(game_map)

        node_ids = {node["id"] for node in nodes}
        self.assertEqual(node_ids, game_map.cities())
        self.assertTrue(all(node["name"] == node["id"] for node in nodes))
        self.assertTrue(
            all(node["data"]["members"] == [node["id"]] for node in nodes)
        )

    def test_claimed_by_from_snapshot_merges_player_and_opponent_claims(self) -> None:
        turn_state = make_turn_state(
            "bot_0",
            ["Seattle-Portland-1"],
            [("bot_1", ["Boston-Montreal-1"])],
        )

        claimed_by = claimed_by_from_snapshot(turn_state)

        self.assertEqual(
            claimed_by,
            {"Seattle-Portland-1": "bot_0", "Boston-Montreal-1": "bot_1"},
        )

    def test_build_edges_keeps_route_color_and_carries_the_claim_in_claimed_color(self) -> None:
        game_map = MapGraph(player_count=2)
        claimed_route = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-1")
        unclaimed_route = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-2")

        edges = build_edges(
            game_map,
            claimed_by={"Seattle-Portland-1": "bot_0"},
            player_colors={"bot_0": "red"},
        )

        edges_by_id = {edge["id"]: edge for edge in edges}
        claimed_edge = edges_by_id["Seattle-Portland-1"]
        unclaimed_edge = edges_by_id["Seattle-Portland-2"]

        self.assertEqual(claimed_edge["source"], claimed_route.city1)
        self.assertEqual(claimed_edge["target"], claimed_route.city2)
        self.assertEqual(claimed_edge["width"], claimed_route.length)
        # A claim never repaints the route's own color; it only adds the
        # owner's color as an inset marker so the base color stays visible.
        self.assertNotEqual(claimed_edge["color"], "red")
        self.assertEqual(claimed_edge["color"], unclaimed_edge["color"])
        self.assertEqual(claimed_edge["claimedColor"], "red")
        self.assertEqual(claimed_edge["data"]["claimedBy"], "bot_0")

        self.assertIsNone(unclaimed_edge["claimedColor"])
        self.assertIsNone(unclaimed_edge["data"]["claimedBy"])
        self.assertEqual(unclaimed_edge["width"], unclaimed_route.length)

    def test_build_edges_gives_parallel_routes_opposite_nonzero_curvature(self) -> None:
        game_map = MapGraph(player_count=4)

        edges = build_edges(game_map, claimed_by={}, player_colors={})

        edges_by_id = {edge["id"]: edge for edge in edges}
        first = edges_by_id["Seattle-Portland-1"]["curvature"]
        second = edges_by_id["Seattle-Portland-2"]["curvature"]

        self.assertNotEqual(first, 0)
        self.assertEqual(first, -second)

    def test_build_edges_gives_a_single_route_between_a_city_pair_zero_curvature(self) -> None:
        game_map = MapGraph(player_count=2)
        # Vancouver-Calgary has only one route in the classic map.
        solo_route = next(route for route in game_map.routes if {route.city1, route.city2} == {"Vancouver", "Calgary"})

        edges = build_edges(game_map, claimed_by={}, player_colors={})

        edges_by_id = {edge["id"]: edge for edge in edges}
        self.assertEqual(edges_by_id[solo_route.route_id]["curvature"], 0)


class CulledRenderingTests(unittest.TestCase):
    def make_culled(self):
        routes = [
            Route("A", "B", 1, "R", "A-B-1"),
            Route("B", "C", 2, "U", "B-C-1"),
            Route("A", "C", 5, "Y", "A-C-1"),
            Route("C", "D", 3, "X", "C-D-1"),
        ]
        return contract_map(routes, player_count=4, claimed_by={"A-B-1": "me"}, player_id="me")

    def test_build_culled_nodes_emits_merged_nodes_with_readable_names(self) -> None:
        nodes = build_culled_nodes(self.make_culled())

        nodes_by_id = {node["id"]: node for node in nodes}
        self.assertIn("A+B", nodes_by_id)
        self.assertEqual(nodes_by_id["A+B"]["name"], "A + B")
        self.assertEqual(nodes_by_id["A+B"]["data"]["members"], ["A", "B"])
        self.assertIn("C", nodes_by_id)
        self.assertEqual(nodes_by_id["C"]["data"]["members"], ["C"])

    def test_build_culled_edges_remaps_endpoints_and_shows_no_claims(self) -> None:
        edges = build_culled_edges(self.make_culled())

        edges_by_id = {edge["id"]: edge for edge in edges}
        # B-C and A-C now both connect A+B <-> C.
        self.assertEqual(
            {edges_by_id["B-C-1"]["source"], edges_by_id["B-C-1"]["target"]},
            {"A+B", "C"},
        )
        for edge in edges:
            self.assertIsNone(edge["claimedColor"])
            self.assertIsNone(edge["data"]["claimedBy"])

    def test_build_culled_edges_bows_routes_that_become_parallel_after_contraction(self) -> None:
        edges = build_culled_edges(self.make_culled())

        edges_by_id = {edge["id"]: edge for edge in edges}
        first = edges_by_id["B-C-1"]["curvature"]
        second = edges_by_id["A-C-1"]["curvature"]
        self.assertNotEqual(first, 0)
        self.assertEqual(first, -second)
        # C-D stays alone between its endpoints: straight.
        self.assertEqual(edges_by_id["C-D-1"]["curvature"], 0)


if __name__ == "__main__":
    unittest.main()
