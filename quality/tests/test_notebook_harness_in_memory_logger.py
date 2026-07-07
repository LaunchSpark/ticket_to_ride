from __future__ import annotations

import unittest

from external.bots.random_bot import RandomBot
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.views import PlayerView

from notebook_harness.in_memory_logger import InMemoryGameLogger


class InMemoryGameLoggerTests(unittest.TestCase):
    def test_record_turn_appends_a_snapshot_with_the_serialized_turn_state(self) -> None:
        players = [
            Player("bot_0", RandomBot(), "random_1", "red"),
            Player("bot_1", RandomBot(), "random_2", "blue"),
        ]
        logger = InMemoryGameLogger(players)
        context = GameContext([player.player_id for player in players])

        for p in players:
            p.attach(context, players)
        players[0].set_context(PlayerView(players[0].player_id, context, players), True)
        players[1].set_context(PlayerView(players[1].player_id, context, players), True)

        snapshot = logger.record_turn(0, players[0].context)

        self.assertEqual(len(logger.snapshots), 1)
        self.assertEqual(snapshot["roundNumber"], 0)
        self.assertEqual(snapshot["turnIndex"], 0)
        self.assertEqual(snapshot["turnState"]["player"]["playerId"], "bot_0")
        self.assertEqual(len(snapshot["turnState"]["opponents"]), 1)
        self.assertEqual(snapshot["turnState"]["opponents"][0]["playerId"], "bot_1")

    def test_record_turn_increments_turn_index_across_calls(self) -> None:
        players = [
            Player("bot_0", RandomBot(), "random_1", "red"),
            Player("bot_1", RandomBot(), "random_2", "blue"),
        ]
        logger = InMemoryGameLogger(players)
        context = GameContext([player.player_id for player in players])

        for p in players:
            p.attach(context, players)
        players[0].set_context(PlayerView(players[0].player_id, context, players), True)

        logger.record_turn(0, players[0].context)
        second_snapshot = logger.record_turn(0, players[0].context)

        self.assertEqual(second_snapshot["turnIndex"], 1)


if __name__ == "__main__":
    unittest.main()
