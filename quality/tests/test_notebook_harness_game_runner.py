from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot
from external.contracts.base_bot import BaseBot

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
        harness_game = initialize_game([RandomBot(), RandomBot()])

        self.assertEqual(len(harness_game.players), 2)
        self.assertEqual(harness_game.players[0].player_id, "bot_0")
        self.assertEqual(harness_game.players[1].player_id, "bot_1")
        self.assertEqual(harness_game.players[0].color, "red")
        self.assertEqual(harness_game.players[1].color, "blue")

    def test_roster_lists_every_seat_with_id_name_and_color(self) -> None:
        harness_game = initialize_game([RandomBot(), RandomBot()])

        roster = harness_game.roster()

        self.assertEqual(
            roster,
            [
                {"id": "bot_0", "name": harness_game.players[0].name, "color": "red"},
                {"id": "bot_1", "name": harness_game.players[1].name, "color": "blue"},
            ],
        )

    def test_playing_a_game_records_snapshots_and_board_at_returns_nodes_and_edges(self) -> None:
        harness_game = initialize_game([RandomBot(), RandomBot()])

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
        harness_game = initialize_game([RandomBot(), RandomBot()])
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


class MarketAtTests(unittest.TestCase):
    def _played_game(self):
        harness_game = initialize_game([RandomBot(), RandomBot()], seed=41)
        harness_game.play()
        return harness_game

    def test_market_at_step_zero_shows_the_post_setup_market(self):
        harness_game = self._played_game()
        market = harness_game.market_at(0)
        self.assertEqual(len(market["face_up"]), 5)
        # 110 cards - 5 face-up - 4 dealt to each of 2 seats, split between
        # the draw pile and any cards the locomotive mulligan discarded
        # during deck construction.
        self.assertEqual(market["deck_count"] + market["discard_count"], 110 - 5 - 8)
        # spectator pie = true draw pile
        self.assertEqual(sum(seg["count"] for seg in market["pie"]), market["deck_count"])
        self.assertIn("L", market["colors"])
        self.assertIn("R", market["colors"])

    def test_market_at_with_viewpoint_uses_the_public_pool(self):
        harness_game = self._played_game()
        step = harness_game.snapshot_count() - 1
        spectator = harness_game.market_at(step)
        viewer = harness_game.market_at(step, "bot_0")
        pie_total = sum(seg["count"] for seg in viewer["pie"])
        # public pool = draw pile + opponents' hidden cards >= true draw pile
        self.assertGreaterEqual(pie_total, spectator["deck_count"])
        self.assertEqual(viewer["deck_count"], spectator["deck_count"])

    def test_market_at_is_cached_and_consistent(self):
        harness_game = self._played_game()
        first = harness_game.market_at(3)
        second = harness_game.market_at(3)
        self.assertEqual(first["face_up"], second["face_up"])
        self.assertEqual(first["deck_count"], second["deck_count"])

    def test_card_color_hex_covers_all_card_colors(self):
        from ticket_to_ride.board_view import card_color_hex

        colors = card_color_hex()
        for letter in ["R", "B", "U", "G", "O", "P", "W", "Y", "L"]:
            self.assertRegex(colors[letter], r"^#[0-9a-fA-F]{6}$")
        self.assertNotIn("X", colors)   # gray is a route color, not a card


if __name__ == "__main__":
    unittest.main()
