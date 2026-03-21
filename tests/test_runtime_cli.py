import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ticket_to_ride.runtime.cli import (
    ViewerRequestHandler,
    build_viewer_url,
    ensure_pocketbase_schema,
    ensure_pocketbase_superuser,
    pocketbase_admin_email,
    pocketbase_admin_password,
    pocketbase_binary_path,
    pocketbase_data_dir,
    pocketbase_is_reachable,
    pocketbase_url,
    PocketBaseLaunchResult,
    resolve_runtime_storage_backend,
    run,
    seed_match_if_empty_via_api,
    start_backend_process,
    start_pocketbase_process,
)


class RuntimeCliTests(unittest.TestCase):
    def test_build_viewer_url_points_viewer_to_backend_api(self) -> None:
        url = build_viewer_url("127.0.0.1", 4173, "127.0.0.1", 8000)
        self.assertEqual(url, "http://127.0.0.1:4173/index.html?api_base=http%3A%2F%2F127.0.0.1%3A8000")

    def test_viewer_request_handler_serves_jsx_as_javascript(self) -> None:
        self.assertEqual(ViewerRequestHandler.extensions_map[".jsx"], "text/javascript")

    def test_pocketbase_url_defaults_to_admin_ui(self) -> None:
        self.assertEqual(pocketbase_url(), "http://127.0.0.1:8090/_/")

    def test_pocketbase_is_reachable_uses_socket_probe(self) -> None:
        with patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True) as wait_for_port:
            self.assertTrue(pocketbase_is_reachable())
            wait_for_port.assert_called_once_with("127.0.0.1", 8090, timeout_seconds=1.0)

    def test_pocketbase_binary_path_uses_env_override(self) -> None:
        fake_binary = Path("tests") / "fake-pocketbase.exe"
        with patch.dict("os.environ", {"POCKETBASE_BINARY": str(fake_binary)}):
            with patch.object(Path, "exists", return_value=True):
                self.assertEqual(pocketbase_binary_path(), str(fake_binary))

    def test_pocketbase_data_dir_defaults_inside_repo_data_directory(self) -> None:
        self.assertEqual(pocketbase_data_dir().name, "pocketbase")
        self.assertEqual(pocketbase_data_dir().parent.name, "data")

    def test_pocketbase_admin_defaults_are_stable(self) -> None:
        self.assertEqual(pocketbase_admin_email(), "admin@example.com")
        self.assertEqual(pocketbase_admin_password(), "12345678")

    def test_start_pocketbase_process_returns_none_when_already_running(self) -> None:
        with patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=True), \
             patch("ticket_to_ride.runtime.cli.ensure_pocketbase_schema", return_value=(True, "schema ok")) as ensure_schema:
            result = start_pocketbase_process()
        self.assertTrue(result.reachable)
        self.assertFalse(result.started)
        self.assertIsNone(result.process)
        self.assertIn("schema ok", result.message)
        ensure_schema.assert_called_once()

    def test_start_pocketbase_process_launches_binary_and_waits_for_port(self) -> None:
        fake_process = MagicMock()
        with patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=False), \
             patch("ticket_to_ride.runtime.cli.pocketbase_binary_path", return_value="pocketbase"), \
             patch("ticket_to_ride.runtime.cli.pocketbase_data_dir", return_value=Path("data/pocketbase")), \
             patch("ticket_to_ride.runtime.cli.ensure_pocketbase_superuser", return_value=(True, "ok")), \
             patch("ticket_to_ride.runtime.cli.ensure_pocketbase_schema", return_value=(True, "schema ok")), \
             patch.object(Path, "mkdir") as mkdir, \
             patch("ticket_to_ride.runtime.cli._wait_for_port", side_effect=[True, True]) as wait_for_port, \
             patch("ticket_to_ride.runtime.cli.subprocess.Popen", return_value=fake_process) as popen:
            result = start_pocketbase_process()

        self.assertIs(result.process, fake_process)
        self.assertTrue(result.started)
        self.assertTrue(result.reachable)
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "pocketbase")
        self.assertIn("serve", command)
        self.assertIn("--http=127.0.0.1:8090", command)
        wait_for_port.assert_any_call("127.0.0.1", 8090, timeout_seconds=5.0)

    def test_start_pocketbase_process_reports_missing_binary(self) -> None:
        with patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=False), \
             patch("ticket_to_ride.runtime.cli.pocketbase_binary_path", return_value=None):
            result = start_pocketbase_process()

        self.assertFalse(result.reachable)
        self.assertFalse(result.started)
        self.assertIsNone(result.process)
        self.assertIn("POCKETBASE_BINARY", result.message)

    def test_ensure_pocketbase_superuser_uses_upsert_with_defaults(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("ticket_to_ride.runtime.cli.subprocess.run", return_value=completed) as run_command:
            ensured, message = ensure_pocketbase_superuser("pocketbase", Path("data/pocketbase"))

        self.assertTrue(ensured)
        self.assertIn("admin@example.com", message)
        command = run_command.call_args.args[0]
        self.assertEqual(command[:4], ["pocketbase", "superuser", "upsert", "admin@example.com"])
        self.assertIn("12345678", command)

    def test_ensure_pocketbase_schema_returns_success_message(self) -> None:
        with patch("ticket_to_ride.runtime.cli.ensure_collections", return_value="reset and recreated collections: matches, rounds, turns") as ensure_collections_mock:
            ok, message = ensure_pocketbase_schema()

        self.assertTrue(ok)
        self.assertIn("Ticket to Ride schema ensured", message)
        self.assertIn("reset and recreated collections", message)
        ensure_collections_mock.assert_called_once()

    def test_start_pocketbase_process_raises_when_schema_repair_fails_for_running_instance(self) -> None:
        with patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=True), \
             patch("ticket_to_ride.runtime.cli.ensure_pocketbase_schema", return_value=(False, "schema repair failed")):
            with self.assertRaises(RuntimeError):
                start_pocketbase_process()

    def test_resolve_runtime_storage_backend_falls_back_to_memory_when_pocketbase_is_unavailable(self) -> None:
        launch_result = PocketBaseLaunchResult(process=None, started=False, reachable=False, message=None)

        with patch.dict("os.environ", {}, clear=True), \
             patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=False):
            backend = resolve_runtime_storage_backend(launch_result)

        self.assertEqual(backend, "memory")

    def test_start_backend_process_launches_uvicorn_and_waits_for_port(self) -> None:
        fake_process = MagicMock()
        with patch("ticket_to_ride.runtime.cli.subprocess.Popen", return_value=fake_process) as popen, \
             patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True) as wait_for_port:
            result = start_backend_process("127.0.0.1", 8000)

        self.assertIs(result, fake_process)
        command = popen.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "uvicorn"])
        self.assertIn("ticket_to_ride.backend.app:app", command)
        self.assertIn("--host", command)
        self.assertIn("--port", command)
        wait_for_port.assert_called_once_with("127.0.0.1", 8000, timeout_seconds=5.0)

    def test_seed_match_if_empty_via_api_returns_false_when_matches_exist(self) -> None:
        with patch.object(seed_match_if_empty_via_api.__globals__["JsonHttpTransport"], "request", side_effect=[[{"matchId": "match-1"}]]):
            seeded = seed_match_if_empty_via_api("http://127.0.0.1:8000", round_limit=1)

        self.assertFalse(seeded)

    def test_run_starts_backend_then_seeds_then_opens_browser(self) -> None:
        fake_viewer_server = MagicMock()
        fake_backend_process = MagicMock()
        fake_backend_process.wait.side_effect = KeyboardInterrupt()
        startup_order: list[str] = []
        backend_envs: list[dict[str, str]] = []

        with patch("ticket_to_ride.runtime.cli.start_pocketbase_process", return_value=MagicMock(message=None, reachable=False, process=None)), \
             patch("ticket_to_ride.runtime.cli._start_viewer_server", return_value=fake_viewer_server), \
             patch("ticket_to_ride.runtime.cli.seed_match_if_empty_via_api", side_effect=lambda api_base_url, round_limit=10: startup_order.append("seed") or True), \
             patch(
                 "ticket_to_ride.runtime.cli.start_backend_process",
                 side_effect=lambda host, port, env=None: backend_envs.append(env or {}) or startup_order.append("backend") or fake_backend_process,
             ), \
             patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True), \
             patch("ticket_to_ride.runtime.cli._open_default_browser", side_effect=lambda url: startup_order.append("browser")), \
             patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                run()

        self.assertEqual(startup_order[:3], ["backend", "seed", "browser"])
        self.assertEqual(backend_envs[0]["MATCH_LOG_STORAGE_BACKEND"], "memory")
        fake_viewer_server.shutdown.assert_called_once()
        fake_viewer_server.server_close.assert_called_once()
        fake_backend_process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
