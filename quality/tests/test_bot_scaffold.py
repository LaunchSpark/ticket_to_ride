from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ticket_to_ride.backend.bot_scaffold import (
    BotScaffoldError,
    class_name_from_slug,
    scaffold_bot,
    slugify_bot_name,
)


class SlugifyTests(unittest.TestCase):
    def test_names_are_lowercased_and_joined_with_underscores(self) -> None:
        self.assertEqual(slugify_bot_name("My Cool Bot"), "my_cool_bot")
        self.assertEqual(slugify_bot_name("  spaced   out  "), "spaced_out")
        self.assertEqual(slugify_bot_name("Ticket-2-Ride!"), "ticket_2_ride")

    def test_leading_digit_gets_a_bot_prefix(self) -> None:
        self.assertEqual(slugify_bot_name("2fast"), "bot_2fast")

    def test_name_without_alphanumerics_is_rejected(self) -> None:
        with self.assertRaises(BotScaffoldError):
            slugify_bot_name("!!!")

    def test_class_name_is_camel_cased(self) -> None:
        self.assertEqual(class_name_from_slug("my_cool_bot"), "MyCoolBot")


class ScaffoldBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bots_dir = Path(self._tmp.name)

    def test_scaffold_writes_a_notebook_with_substituted_metadata(self) -> None:
        scaffolded = scaffold_bot("My Cool Bot", bots_dir=self.bots_dir)

        self.assertEqual(scaffolded.bot_id, "my_cool_bot")
        self.assertEqual(scaffolded.name, "My Cool Bot")
        target = self.bots_dir / "my_cool_bot.py"
        self.assertEqual(scaffolded.path, str(target))
        source = target.read_text(encoding="utf-8")
        self.assertIn('"id": "my_cool_bot"', source)
        self.assertIn('"name": "My Cool Bot"', source)
        self.assertIn("class MyCoolBot(ActionBot):", source)
        self.assertNotIn("your_bot_id", source)
        self.assertNotIn("YourBotName", source)

    def test_scaffold_rejects_an_existing_bot_file(self) -> None:
        scaffold_bot("My Cool Bot", bots_dir=self.bots_dir)

        with self.assertRaises(BotScaffoldError):
            scaffold_bot("my cool BOT", bots_dir=self.bots_dir)

    def test_scaffold_rejects_empty_and_quoted_names(self) -> None:
        with self.assertRaises(BotScaffoldError):
            scaffold_bot("   ", bots_dir=self.bots_dir)
        with self.assertRaises(BotScaffoldError):
            scaffold_bot('Nasty "Bot"', bots_dir=self.bots_dir)


if __name__ == "__main__":
    unittest.main()
