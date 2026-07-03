from __future__ import annotations

import unittest

from ticket_to_ride.engine.state.map import MapGraph

from notebook_harness.rendering import (
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

    def test_build_edges_colors_claimed_routes_with_the_owning_players_color_and_others_by_route_color(self) -> None:
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
        self.assertEqual(claimed_edge["color"], "red")
        self.assertEqual(claimed_edge["data"]["claimedBy"], "bot_0")

        self.assertNotEqual(unclaimed_edge["color"], "red")
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


if __name__ == "__main__":
    unittest.main()
