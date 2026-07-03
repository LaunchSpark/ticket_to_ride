import unittest

from ticket_to_ride.engine.state.map import (
    DEFAULT_MAP_NAME,
    MapGraph,
    available_maps,
    resolve_map_path,
)


class MapSelectionTests(unittest.TestCase):
    def test_available_maps_includes_the_default_map(self) -> None:
        self.assertIn(DEFAULT_MAP_NAME, available_maps())

    def test_resolve_map_path_rejects_unknown_map_names(self) -> None:
        with self.assertRaises(ValueError):
            resolve_map_path("not-a-real-map")

    def test_map_graph_defaults_to_the_classic_map(self) -> None:
        game_map = MapGraph(player_count=2)

        self.assertEqual(game_map.map_name, DEFAULT_MAP_NAME)
        self.assertTrue(len(game_map.routes) > 0)

    def test_map_graph_accepts_an_explicit_map_name(self) -> None:
        game_map = MapGraph(player_count=2, map_name=DEFAULT_MAP_NAME)

        self.assertEqual(game_map.map_name, DEFAULT_MAP_NAME)
        self.assertTrue(len(game_map.routes) > 0)

    def test_game_context_passes_map_name_through_to_the_map_graph(self) -> None:
        from ticket_to_ride.engine.state.game_context import GameContext

        context = GameContext(["bot_1", "bot_2"], map_name=DEFAULT_MAP_NAME)

        self.assertEqual(context.get_map().map_name, DEFAULT_MAP_NAME)


if __name__ == "__main__":
    unittest.main()
