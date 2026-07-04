from __future__ import annotations

import unittest

from external.contracts.base_bot import BaseBot
from ticket_to_ride.runtime.cli import BootstrapRandomBot

from notebook_harness.game_runner import available_bots, initialize_game, list_maps


class GameRunnerTests(unittest.TestCase):
    def test_list_maps_includes_the_classic_map(self) -> None:
        self.assertIn("classic", list_maps())

    def test_available_bots_maps_display_names_to_bot_classes(self) -> None:
        bots = available_bots()

        self.assertIn("Random Bot", bots)
        self.assertIn("Example Bot", bots)
        for bot_class in bots.values():
            self.assertTrue(issubclass(bot_class, BaseBot))

    def test_initialize_game_builds_one_player_per_bot(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        self.assertEqual(len(harness_game.players), 2)
        self.assertEqual(harness_game.players[0].player_id, "bot_0")
        self.assertEqual(harness_game.players[1].player_id, "bot_1")
        self.assertEqual(harness_game.players[0].color, "red")
        self.assertEqual(harness_game.players[1].color, "blue")

    def test_roster_lists_every_seat_with_id_name_and_color(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])

        roster = harness_game.roster()

        self.assertEqual(
            roster,
            [
                {"id": "bot_0", "name": harness_game.players[0].name, "color": "red"},
                {"id": "bot_1", "name": harness_game.players[1].name, "color": "blue"},
            ],
        )

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

    def test_board_at_with_viewpoint_returns_the_culled_view(self) -> None:
        harness_game = initialize_game([BootstrapRandomBot(), BootstrapRandomBot()])
        harness_game.play()

        last_step = harness_game.snapshot_count() - 1
        nodes, edges = harness_game.board_at(last_step, viewpoint="bot_0")

        # By game end bot_0 has claimed routes, so at least one merged node exists.
        self.assertTrue(any("+" in node["id"] for node in nodes))
        # The culled view never shows claims: every surviving edge is claimable.
        for edge in edges:
            self.assertIsNone(edge["claimedColor"])
            self.assertIsNone(edge["data"]["claimedBy"])

        # And it must be a historical reconstruction: the step-0 culled view
        # has no merged nodes yet (nobody has claimed anything on turn 0).
        first_nodes, _ = harness_game.board_at(0, viewpoint="bot_0")
        bot_0_claims_at_start = [
            r
            for r in harness_game.logger.snapshots[0]["turnState"]["player"]["claimedRoutes"]
        ]
        if not bot_0_claims_at_start:
            self.assertFalse(any("+" in node["id"] for node in first_nodes))


if __name__ == "__main__":
    unittest.main()
