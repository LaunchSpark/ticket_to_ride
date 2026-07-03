from __future__ import annotations

import unittest

from ticket_to_ride.runtime.cli import BootstrapRandomBot

from notebook_harness.game_runner import initialize_game, list_maps


class GameRunnerTests(unittest.TestCase):
    def test_list_maps_includes_the_classic_map(self) -> None:
        self.assertIn("classic", list_maps())

    def test_initialize_game_builds_one_player_per_bot(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        self.assertEqual(len(harness_game.players), 2)
        self.assertEqual(harness_game.players[0].player_id, "bot_0")
        self.assertEqual(harness_game.players[1].player_id, "bot_1")
        self.assertEqual(harness_game.players[0].color, "red")
        self.assertEqual(harness_game.players[1].color, "blue")

    def test_playing_a_game_records_snapshots_and_board_at_returns_nodes_and_edges(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        harness_game.play()

        self.assertGreater(harness_game.snapshot_count(), 0)

        nodes, edges = harness_game.board_at(0)
        self.assertTrue(len(nodes) > 0)
        self.assertTrue(len(edges) > 0)

        # Every claimed-by value in the first snapshot must be one of the two players.
        player_ids = {player.player_id for player in harness_game.players}
        for edge in edges:
            owner = edge["data"]["claimedBy"]
            if owner is not None:
                self.assertIn(owner, player_ids)


if __name__ == "__main__":
    unittest.main()
