from __future__ import annotations

import unittest

from external.clients.bot_api.loader import BotLoader, BotLoaderError


class BotLoaderTests(unittest.TestCase):
    def test_loader_discovers_built_in_bots_with_metadata(self) -> None:
        loader = BotLoader()

        descriptors = loader.load_bots()

        self.assertIn("random_bot", descriptors)
        self.assertIn("example_bot", descriptors)
        self.assertEqual(descriptors["random_bot"].metadata.name, "Random Bot")

    def test_loader_rejects_missing_bot_meta(self) -> None:
        loader = BotLoader()

        with self.assertRaises(BotLoaderError):
            loader._load_bot_descriptor(loader.bots_dir / "__init__.py")


if __name__ == "__main__":
    unittest.main()
