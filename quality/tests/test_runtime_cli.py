import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ticket_to_ride.runtime.cli import (
    bot_api_base_url,
    bot_api_enabled,
    bot_api_is_reachable,
    bootstrap_managed_random_match_via_api,
    seed_match_if_empty_via_api,
    ViewerRequestHandler,
    ViewerLaunchResult,
    BotApiLaunchResult,
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
    start_backend_process,
    start_bot_api_process,
    start_pocketbase_process,
)


class RuntimeCliTests(unittest.TestCase):
    def test_build_viewer_url_points_viewer_to_backend_api(self) -> None:
        url = build_viewer_url("127.0.0.1", 4173, "127.0.0.1", 8000)
        self.assertEqual(url, "http://127.0.0.1:4173/index.html?api_base=http%3A%2F%2F127.0.0.1%3A8000")

    def test_viewer_request_handler_serves_jsx_as_javascript(self) -> None:
        self.assertEqual(ViewerRequestHandler.extensions_map[".jsx"], "text/javascript")

    def test_viewer_request_handler_identifies_app_shell_routes(self) -> None:
        self.assertTrue(ViewerRequestHandler.should_serve_app_shell("/bots"))
        self.assertFalse(ViewerRequestHandler.should_serve_app_shell("/components/viewer-shell.css"))
        self.assertFalse(ViewerRequestHandler.should_serve_app_shell("/index.html"))

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

    def test_bot_api_base_url_defaults_to_local_service(self) -> None:
        self.assertEqual(bot_api_base_url(), "http://127.0.0.1:8001")

    def test_bot_api_is_disabled_by_default(self) -> None:
        self.assertFalse(bot_api_enabled())

    def test_bot_api_enabled_by_env_flag(self) -> None:
        with patch.dict("os.environ", {"TICKET_TO_RIDE_ENABLE_BOT_API": "1"}):
            self.assertTrue(bot_api_enabled())

    def test_bot_api_is_reachable_uses_socket_probe(self) -> None:
        with patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True) as wait_for_port:
            self.assertTrue(bot_api_is_reachable())
            wait_for_port.assert_called_once_with("127.0.0.1", 8001, timeout_seconds=1.0)

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
             patch("ticket_to_ride.runtime.cli.pocketbase_data_dir", return_value=Path("operations/data/pocketbase")), \
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
            ensured, message = ensure_pocketbase_superuser("pocketbase", Path("operations/data/pocketbase"))

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

    def test_start_bot_api_process_reuses_existing_instance_when_reachable(self) -> None:
        with patch("ticket_to_ride.runtime.cli.bot_api_is_reachable", return_value=True):
            result = start_bot_api_process()

        self.assertTrue(result.reachable)
        self.assertFalse(result.started)
        self.assertIsNone(result.process)
        self.assertIn("already running", result.message)

    def test_start_bot_api_process_launches_uvicorn_and_waits_for_port(self) -> None:
        fake_process = MagicMock()
        with patch("ticket_to_ride.runtime.cli.bot_api_is_reachable", return_value=False), \
             patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True) as wait_for_port, \
             patch("ticket_to_ride.runtime.cli.subprocess.Popen", return_value=fake_process) as popen:
            result = start_bot_api_process()

        self.assertTrue(result.reachable)
        self.assertTrue(result.started)
        self.assertIs(result.process, fake_process)
        command = popen.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "uvicorn"])
        self.assertIn("external.clients.bot_api.app:app", command)
        self.assertIn("--host", command)
        self.assertIn("--port", command)
        wait_for_port.assert_called_once_with("127.0.0.1", 8001, timeout_seconds=5.0)

    def test_start_bot_api_process_rejects_non_loopback_base_url(self) -> None:
        with patch.dict("os.environ", {"BOT_API_BASE_URL": "http://example.com:8001"}), \
             patch("ticket_to_ride.runtime.cli.bot_api_is_reachable", return_value=False):
            result = start_bot_api_process()

        self.assertFalse(result.reachable)
        self.assertFalse(result.started)
        self.assertIn("loopback", result.message)

    def test_seed_match_if_empty_via_api_returns_false_when_matches_exist(self) -> None:
        with patch.object(seed_match_if_empty_via_api.__globals__["JsonHttpTransport"], "request", side_effect=[[{"matchId": "match-1"}]]):
            seeded = seed_match_if_empty_via_api("http://127.0.0.1:8000", round_limit=1)

        self.assertFalse(seeded)

    def test_bootstrap_managed_random_match_via_api_returns_false_when_replay_matches_exist(self) -> None:
        with patch.object(
            bootstrap_managed_random_match_via_api.__globals__["JsonHttpTransport"],
            "request",
            side_effect=[
                [{"matchId": "match-1"}],
                [],
            ],
        ):
            bootstrapped = bootstrap_managed_random_match_via_api("http://127.0.0.1:8000")

        self.assertFalse(bootstrapped)

    def test_bootstrap_managed_random_match_via_api_returns_false_when_managed_matches_exist(self) -> None:
        with patch.object(
            bootstrap_managed_random_match_via_api.__globals__["JsonHttpTransport"],
            "request",
            side_effect=[
                [],
                [{"matchId": "managed-1"}],
            ],
        ):
            bootstrapped = bootstrap_managed_random_match_via_api("http://127.0.0.1:8000")

        self.assertFalse(bootstrapped)

    def test_bootstrap_managed_random_match_via_api_creates_expected_heads_up_payload(self) -> None:
        with patch.object(
            bootstrap_managed_random_match_via_api.__globals__["JsonHttpTransport"],
            "request",
            side_effect=[
                [],
                [],
                {"matchId": "managed-1"},
            ],
        ) as request:
            bootstrapped = bootstrap_managed_random_match_via_api("http://127.0.0.1:8000")

        self.assertTrue(bootstrapped)
        self.assertEqual(
            request.call_args_list,
            [
                unittest.mock.call("GET", "/matches"),
                unittest.mock.call("GET", "/managed-matches"),
                unittest.mock.call(
                    "POST",
                    "/managed-matches",
                    {
                        "name": "Random Bot vs Random Bot",
                        "seats": [
                            {"seatId": "seat_1", "primaryBotId": "random_bot"},
                            {"seatId": "seat_2", "primaryBotId": "random_bot"},
                        ],
                        "fallbackBotId": "random_bot",
                        "roundCount": 3,
                        "timeControl": {
                            "initialTimeMs": 60000,
                            "incrementMs": 0,
                            "perCallSoftLimitMs": None,
                            "perCallHardLimitMs": None,
                        },
                        "timeoutPolicy": "loss_on_time",
                        "executionMode": "bot_api",
                    },
                ),
            ],
        )

    def test_run_starts_backend_then_seeds_then_opens_browser(self) -> None:
        fake_viewer_server = MagicMock()
        fake_backend_process = MagicMock()
        fake_backend_process.poll.return_value = None
        fake_backend_process.wait.side_effect = [KeyboardInterrupt(), None]
        startup_order: list[str] = []
        backend_envs: list[dict[str, str]] = []

        with patch("ticket_to_ride.runtime.cli.start_pocketbase_process", return_value=MagicMock(message=None, reachable=False, process=None)), \
             patch(
                 "ticket_to_ride.runtime.cli._start_viewer_runtime",
                 return_value=ViewerLaunchResult(server=fake_viewer_server, message=None),
             ), \
             patch("ticket_to_ride.runtime.cli.start_bot_api_process") as start_bot_api, \
             patch(
                 "ticket_to_ride.runtime.cli.seed_match_if_empty_via_api",
                 side_effect=lambda api_base_url, round_limit=10: startup_order.append("seed") or True,
             ), \
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
        start_bot_api.assert_not_called()
        fake_viewer_server.shutdown.assert_called_once()
        fake_viewer_server.server_close.assert_called_once()
        fake_backend_process.terminate.assert_called_once()

    def test_run_with_flag_starts_backend_then_bot_api_then_bootstraps_then_opens_browser(self) -> None:
        fake_viewer_server = MagicMock()
        fake_backend_process = MagicMock()
        fake_backend_process.poll.return_value = None
        fake_backend_process.wait.side_effect = [KeyboardInterrupt(), None]
        startup_order: list[str] = []
        backend_envs: list[dict[str, str]] = []
        fake_bot_api_process = MagicMock()
        fake_bot_api_process.poll.return_value = None
        fake_bot_api_launch = BotApiLaunchResult(
            process=fake_bot_api_process,
            started=True,
            reachable=True,
            message=None,
            base_url="http://127.0.0.1:8001",
        )

        with patch.dict("os.environ", {"TICKET_TO_RIDE_ENABLE_BOT_API": "1"}), \
             patch("ticket_to_ride.runtime.cli.start_pocketbase_process", return_value=MagicMock(message=None, reachable=False, process=None)), \
             patch(
                 "ticket_to_ride.runtime.cli._start_viewer_runtime",
                 return_value=ViewerLaunchResult(server=fake_viewer_server, message=None),
             ), \
             patch("ticket_to_ride.runtime.cli.start_bot_api_process", side_effect=lambda: startup_order.append("bot_api") or fake_bot_api_launch), \
             patch(
                 "ticket_to_ride.runtime.cli.bootstrap_managed_random_match_via_api",
                 side_effect=lambda api_base_url: startup_order.append("bootstrap") or True,
             ), \
             patch(
                 "ticket_to_ride.runtime.cli.start_backend_process",
                 side_effect=lambda host, port, env=None: backend_envs.append(env or {}) or startup_order.append("backend") or fake_backend_process,
             ), \
             patch("ticket_to_ride.runtime.cli._wait_for_port", return_value=True), \
             patch("ticket_to_ride.runtime.cli._open_default_browser", side_effect=lambda url: startup_order.append("browser")), \
             patch("ticket_to_ride.runtime.cli.pocketbase_is_reachable", return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                run()

        self.assertEqual(startup_order[:4], ["backend", "bot_api", "bootstrap", "browser"])
        self.assertEqual(backend_envs[0]["MATCH_LOG_STORAGE_BACKEND"], "memory")
        fake_viewer_server.shutdown.assert_called_once()
        fake_viewer_server.server_close.assert_called_once()
        fake_backend_process.terminate.assert_called_once()
        fake_bot_api_process.terminate.assert_called_once()

    def test_run_raises_when_managed_match_bootstrap_fails(self) -> None:
        fake_viewer_server = MagicMock()
        fake_backend_process = MagicMock()
        fake_backend_process.poll.return_value = None
        fake_bot_api_process = MagicMock()
        fake_bot_api_process.poll.return_value = None
        fake_bot_api_launch = BotApiLaunchResult(
            process=fake_bot_api_process,
            started=True,
            reachable=True,
            message=None,
            base_url="http://127.0.0.1:8001",
        )

        with patch.dict("os.environ", {"TICKET_TO_RIDE_ENABLE_BOT_API": "1"}), \
             patch("ticket_to_ride.runtime.cli.start_pocketbase_process", return_value=MagicMock(message=None, reachable=False, process=None)), \
             patch(
                 "ticket_to_ride.runtime.cli._start_viewer_runtime",
                 return_value=ViewerLaunchResult(server=fake_viewer_server, message=None),
             ), \
             patch("ticket_to_ride.runtime.cli.start_backend_process", return_value=fake_backend_process), \
             patch("ticket_to_ride.runtime.cli.start_bot_api_process", return_value=fake_bot_api_launch), \
             patch(
                 "ticket_to_ride.runtime.cli.bootstrap_managed_random_match_via_api",
                 side_effect=RuntimeError(
                     "Unable to inspect existing backend matches at http://127.0.0.1:8000: boom"
                 ),
             ):
            with self.assertRaises(RuntimeError) as exc:
                run()

        self.assertIn("Unable to inspect existing backend matches", str(exc.exception))
        fake_viewer_server.shutdown.assert_called_once()
        fake_viewer_server.server_close.assert_called_once()
        fake_backend_process.terminate.assert_called_once()
        fake_bot_api_process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
