from types import SimpleNamespace
import unittest
from unittest.mock import patch

from external.bots.random_bot import RandomBot
from ticket_to_ride.engine.actions import DrawBlind, DrawTickets


class RandomBotTests(unittest.TestCase):
    def test_random_bot_metadata_is_exposed(self) -> None:
        bot = RandomBot()

        self.assertEqual(bot.info()["botId"], "random_bot")
        self.assertEqual(bot.info()["name"], "Random Bot")

    def test_act_selects_from_legal_actions(self) -> None:
        bot = RandomBot()
        legal_actions = [DrawBlind(), DrawTickets()]

        with patch("external.bots.random_bot.random.choice", return_value=DrawTickets()) as choice:
            selected = bot.act(SimpleNamespace(decision="turn"), legal_actions)

        self.assertEqual(selected, DrawTickets())
        choice.assert_called_once_with(legal_actions)

    def test_path_finder_is_a_placeholder(self) -> None:
        self.assertIsNone(RandomBot().path_finder("Seattle", "Portland"))


if __name__ == "__main__":
    unittest.main()
