from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

from external.contracts.base_bot import ActionBot


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "integrations"
    / "external"
    / "templates"
    / "bots"
    / "build_your_bot_here.py"
)


def load_template_module():
    spec = importlib.util.spec_from_file_location("bot_template", TEMPLATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BotTemplateTests(unittest.TestCase):
    def test_template_keeps_the_replaceable_placeholders(self) -> None:
        module = load_template_module()

        self.assertEqual(module.BOT_META["id"], "your_bot_id")
        self.assertEqual(module.BOT_META["name"], "Your Bot Name")
        self.assertTrue(hasattr(module, "YourBotName"))

    def test_template_bot_is_an_action_bot_that_picks_the_first_legal_action(self) -> None:
        module = load_template_module()

        self.assertTrue(issubclass(module.YourBotName, ActionBot))
        bot = module.YourBotName()
        sentinel = object()
        self.assertIs(bot.act(view=None, legal_actions=[sentinel, object()]), sentinel)

    def test_template_meta_matches_the_class_meta(self) -> None:
        module = load_template_module()

        self.assertIs(module.YourBotName.META, module.BOT_META)

    def test_template_is_a_marimo_notebook_with_three_shared_spectate_cells(self) -> None:
        source = TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn("import marimo", source)
        self.assertIn('app = marimo.App(width="medium")', source)
        self.assertEqual(source.count("@app.cell(hide_code=True)"), 3)
        self.assertIn("spectate_controls", source)
        self.assertIn("play_match", source)
        self.assertIn("spectate_view", source)

    def test_template_is_recognized_by_marimo(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "marimo", "check", str(TEMPLATE_PATH)],
            cwd=TEMPLATE_PATH.parents[4],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
