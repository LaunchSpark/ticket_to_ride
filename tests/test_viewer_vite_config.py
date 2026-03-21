from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ViewerViteConfigTests(unittest.TestCase):
    def test_viewer_vite_config_enables_polling(self) -> None:
        vite_config = (REPO_ROOT / "apps" / "viewer" / "vite.config.js").read_text(encoding="utf-8")
        package_json = (REPO_ROOT / "apps" / "viewer" / "package.json").read_text(encoding="utf-8")

        self.assertIn("usePolling: true", vite_config)
        self.assertIn("interval:", vite_config)
        self.assertIn('"dev": "vite"', package_json)


if __name__ == "__main__":
    unittest.main()
