import unittest

from ticket_to_ride.engine.state.map import MapGraph


class MapRuleTests(unittest.TestCase):
    def test_two_player_game_blocks_second_half_of_double_route_for_everyone(self) -> None:
        game_map = MapGraph(player_count=2)
        first = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-1")
        second = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-2")

        game_map.claim_route(first, "bot_1")

        self.assertFalse(game_map.is_route_claimable(second, "bot_1"))
        self.assertFalse(game_map.is_route_claimable(second, "bot_2"))
        self.assertNotIn(second, game_map.get_available_routes("bot_2"))
        with self.assertRaises(ValueError):
            game_map.claim_route(second, "bot_2")

    def test_four_player_game_allows_other_player_to_claim_parallel_route(self) -> None:
        game_map = MapGraph(player_count=4)
        first = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-1")
        second = next(route for route in game_map.routes if route.route_id == "Seattle-Portland-2")

        game_map.claim_route(first, "bot_1")

        self.assertFalse(game_map.is_route_claimable(second, "bot_1"))
        self.assertTrue(game_map.is_route_claimable(second, "bot_2"))
        game_map.claim_route(second, "bot_2")
        self.assertEqual(second.claimed_by, "bot_2")

    def test_same_player_cannot_claim_both_halves_of_double_route(self) -> None:
        game_map = MapGraph(player_count=4)
        first = next(route for route in game_map.routes if route.route_id == "Boston-Montreal-1")
        second = next(route for route in game_map.routes if route.route_id == "Boston-Montreal-2")

        game_map.claim_route(first, "bot_1")

        self.assertFalse(game_map.is_route_claimable(second, "bot_1"))
        with self.assertRaises(ValueError):
            game_map.claim_route(second, "bot_1")

