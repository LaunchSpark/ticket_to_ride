from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from external.bots.random_bot import RandomBot
from external.bots.xg_bot import XGBot

from notebook_harness.game_runner import available_bots, initialize_game
from ticket_to_ride.engine.actions import legal_turn_actions
from ticket_to_ride.engine.state.views import PlayerView


class XGBotRegistrationTests(unittest.TestCase):
    def test_xg_bot_is_discovered_by_the_loader(self) -> None:
        bots = available_bots()

        self.assertIn("XG Bot", bots)
        self.assertEqual(bots["XG Bot"].__name__, "XGBot")


class XGBotFallbackTests(unittest.TestCase):
    def test_missing_model_falls_back_to_a_legal_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            bot = XGBot(model_path=missing, features_path=missing)
            harness_game = initialize_game([bot, RandomBot()], seed=31)
            with self.assertLogs("external.bots.xg_bot", level="WARNING") as logs:
                harness_game.game.setup()
            player = harness_game.players[0]
            view = PlayerView(player.player_id, harness_game.game.context, harness_game.players)
            legal = legal_turn_actions(player)

            action = bot.act(view, legal)

        self.assertIn(action, legal)
        self.assertIn("falling back to QualifierBot", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
