from __future__ import annotations

import importlib
import unittest


class MarimoNotebookReuseTests(unittest.TestCase):
    def test_reusable_class_is_importable_without_running_other_cells(self) -> None:
        module = importlib.import_module("quality.tests.fixtures.marimo_reuse_fixture")

        probe_class = getattr(module, "ReusableProbe", None)
        self.assertIsNotNone(probe_class, "ReusableProbe was not exposed as a top-level module attribute.")

        probe = probe_class()
        self.assertEqual(probe.value, 42)

    def test_reusable_class_module_matches_the_notebook_module(self) -> None:
        # This is exactly the check BotLoader._extract_bot_class performs:
        # obj.__module__ == module.__name__
        module = importlib.import_module("quality.tests.fixtures.marimo_reuse_fixture")
        probe_class = module.ReusableProbe

        self.assertEqual(probe_class.__module__, module.__name__)


if __name__ == "__main__":
    unittest.main()
