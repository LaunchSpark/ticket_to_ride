from __future__ import annotations

import unittest
from unittest.mock import patch

from ticket_to_ride.backend.notebook_launcher import NotebookLauncher, default_spawner


class FakeProcess:
    def __init__(self) -> None:
        self.exit_code: 'int | None' = None

    def poll(self) -> 'int | None':
        return self.exit_code


class NotebookLauncherTests(unittest.TestCase):
    def test_default_spawner_disables_token_for_bare_loopback_url(self) -> None:
        with patch("ticket_to_ride.backend.notebook_launcher.subprocess.Popen") as popen:
            default_spawner("/repo/bots/random_bot.py", 12345)

        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["--headless", "--no-token"])
        self.assertIn("edit", command)
        self.assertIn("/repo/bots/random_bot.py", command)

    def test_launch_spawns_a_process_and_returns_its_url(self) -> None:
        spawn_calls = []

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            spawn_calls.append((notebook_path, port))
            return FakeProcess()

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: 12345)

        url = launcher.launch("random_bot", "/repo/integrations/external/bots/random_bot.py")

        self.assertEqual(url, "http://127.0.0.1:12345")
        self.assertEqual(spawn_calls, [("/repo/integrations/external/bots/random_bot.py", 12345)])

    def test_launch_reuses_a_still_running_session_for_the_same_bot(self) -> None:
        spawn_calls = []
        ports = iter([12345, 54321])

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            spawn_calls.append((notebook_path, port))
            return FakeProcess()

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: next(ports))

        first_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")
        second_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(spawn_calls), 1)

    def test_launch_spawns_a_new_session_when_the_previous_process_exited(self) -> None:
        processes = [FakeProcess(), FakeProcess()]
        ports = iter([12345, 54321])

        def fake_spawner(notebook_path: str, port: int) -> FakeProcess:
            return processes.pop(0)

        launcher = NotebookLauncher(spawner=fake_spawner, port_allocator=lambda: next(ports))

        first_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")
        launcher._sessions["random_bot"].process.exit_code = 0  # simulate the marimo server having exited
        second_url = launcher.launch("random_bot", "/repo/bots/random_bot.py")

        self.assertNotEqual(first_url, second_url)


if __name__ == "__main__":
    unittest.main()
