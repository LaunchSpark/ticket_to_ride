from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from external.clients.bot_api.app import create_app


class BotApiModulePathTests(unittest.TestCase):
    def test_get_bots_includes_a_module_path_for_each_bot(self) -> None:
        client = TestClient(create_app())

        response = client.get("/bots")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(len(payload) > 0)
        for bot in payload:
            self.assertIn("modulePath", bot)
            self.assertTrue(bot["modulePath"].endswith(f"{bot['botId']}.py"))


if __name__ == "__main__":
    unittest.main()
