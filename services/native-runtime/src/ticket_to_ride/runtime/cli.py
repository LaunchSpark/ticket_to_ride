from __future__ import annotations

import ipaddress
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import create_connection
from urllib.parse import urlencode, urlparse

from ticket_to_ride.backend.bot_catalog import DEFAULT_BOT_API_BASE_URL
from ticket_to_ride.backend.bootstrap_pocketbase import ensure_collections
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.logging.game_logger import GameLogger, JsonHttpTransport, LoggerClientError

DEFAULT_POCKETBASE_ADMIN_EMAIL = "admin@example.com"
DEFAULT_POCKETBASE_ADMIN_PASSWORD = "12345678"
DEFAULT_BOOTSTRAP_BOT_ID = "random_bot"
DEFAULT_BOOTSTRAP_MATCH_NAME = "Random Bot vs Random Bot"
BOT_API_ENABLE_ENV = "TICKET_TO_RIDE_ENABLE_BOT_API"


@dataclass
class PocketBaseLaunchResult:
    process: subprocess.Popen[str] | None
    started: bool
    reachable: bool
    message: str | None = None
    binary_path: str | None = None


@dataclass
class ViewerLaunchResult:
    process: subprocess.Popen[str] | None = None
    server: ThreadingHTTPServer | None = None
    message: str | None = None


@dataclass
class BotApiLaunchResult:
    process: subprocess.Popen[str] | None
    started: bool
    reachable: bool
    message: str | None = None
    base_url: str | None = None


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".jsx": "text/javascript",
    }

    @staticmethod
    def should_serve_app_shell(request_path: str) -> bool:
        normalized_path = urlparse(request_path).path or "/"
        if normalized_path in {"/", "/index.html"}:
            return False

        return "." not in Path(normalized_path).name

    def do_GET(self) -> None:
        if self.should_serve_app_shell(self.path):
            original_path = self.path
            parsed = urlparse(self.path)
            self.path = f"/index.html{f'?{parsed.query}' if parsed.query else ''}"
            try:
                super().do_GET()
            finally:
                self.path = original_path
            return

        super().do_GET()


def build_viewer_url(viewer_host: str, viewer_port: int, backend_host: str, backend_port: int) -> str:
    query = urlencode({"api_base": f"http://{backend_host}:{backend_port}"})
    return f"http://{viewer_host}:{viewer_port}/index.html?{query}"


def pocketbase_url() -> str:
    return os.getenv("POCKETBASE_BROWSER_URL", "http://127.0.0.1:8090/_/")


def pocketbase_api_url() -> str:
    return os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090").rstrip("/")


def pocketbase_admin_email() -> str:
    return os.getenv("POCKETBASE_ADMIN_EMAIL", DEFAULT_POCKETBASE_ADMIN_EMAIL)


def pocketbase_admin_password() -> str:
    return os.getenv("POCKETBASE_ADMIN_PASSWORD", DEFAULT_POCKETBASE_ADMIN_PASSWORD)


def bot_api_base_url() -> str:
    return os.getenv("BOT_API_BASE_URL", DEFAULT_BOT_API_BASE_URL).rstrip("/")


def bot_api_enabled() -> bool:
    """Opt-in flag for the legacy external bot-api transport.

    Local repository bots are discovered and run in-process by default. The
    sidecar remains available for compatibility while its HTTP protocol still
    speaks the legacy choose_* contract.
    """
    return os.getenv(BOT_API_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def pocketbase_is_reachable() -> bool:
    parsed = urlparse(pocketbase_api_url())
    host = parsed.hostname or "127.0.0.1"
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    return _wait_for_port(host, port, timeout_seconds=1.0)


def bot_api_is_reachable() -> bool:
    parsed = urlparse(bot_api_base_url())
    host = parsed.hostname or "127.0.0.1"
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    return _wait_for_port(host, port, timeout_seconds=1.0)


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _wait_for_port(host: str, port: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_viewer_server(viewer_host: str, viewer_port: int) -> ThreadingHTTPServer:
    viewer_root = _repo_root() / "applications" / "viewer"
    handler = partial(ViewerRequestHandler, directory=str(viewer_root))
    server = ThreadingHTTPServer((viewer_host, viewer_port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_vite_viewer(viewer_host: str, viewer_port: int) -> subprocess.Popen[str] | None:
    viewer_root = _repo_root() / "applications" / "viewer"
    vite_bin = viewer_root / "node_modules" / "vite" / "bin" / "vite.js"
    env = os.environ.copy()
    env.setdefault("BROWSER", "none")
    env.setdefault("CHOKIDAR_USEPOLLING", "true")
    env.setdefault("CHOKIDAR_INTERVAL", env.get("VITE_POLLING_INTERVAL_MS", "300"))

    node_binary = shutil.which("node")
    if vite_bin.exists() and node_binary:
        return subprocess.Popen(
            [
                node_binary,
                str(vite_bin),
                "--host",
                viewer_host,
                "--port",
                str(viewer_port),
                "--strictPort",
            ],
            cwd=str(viewer_root),
            env=env,
            text=True,
        )

    npm_binary = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm_binary:
        return None

    return subprocess.Popen(
        [
            npm_binary,
            "run",
            "dev",
            "--",
            "--host",
            viewer_host,
            "--port",
            str(viewer_port),
            "--strictPort",
        ],
        cwd=str(viewer_root),
        env=env,
        text=True,
    )


def _start_viewer_runtime(viewer_host: str, viewer_port: int) -> ViewerLaunchResult:
    vite_process = _start_vite_viewer(viewer_host, viewer_port)
    if vite_process is not None:
        if _wait_for_port(viewer_host, viewer_port, timeout_seconds=10.0):
            return ViewerLaunchResult(
                process=vite_process,
                message=f"Viewer dev server is running with Vite at http://{viewer_host}:{viewer_port}",
            )

        vite_process.terminate()
        try:
            vite_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            vite_process.kill()
        raise RuntimeError(f"Vite viewer failed to start at http://{viewer_host}:{viewer_port}")

    return ViewerLaunchResult(
        server=_start_viewer_server(viewer_host, viewer_port),
        message=f"Viewer is running in static mode at http://{viewer_host}:{viewer_port} (install applications/viewer dependencies for Vite live reload)",
    )


def _stop_viewer_runtime(viewer_launch: ViewerLaunchResult) -> None:
    if viewer_launch.server is not None:
        viewer_launch.server.shutdown()
        viewer_launch.server.server_close()

    if viewer_launch.process is not None:
        viewer_launch.process.terminate()
        try:
            viewer_launch.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            viewer_launch.process.kill()


def _open_default_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def pocketbase_binary_path() -> str | None:
    configured_path = os.getenv("POCKETBASE_BINARY")
    if configured_path:
        expanded = Path(configured_path).expanduser()
        if expanded.exists():
            return str(expanded)

    discovered = shutil.which("pocketbase")
    if discovered:
        return discovered

    candidate_paths = [
        _repo_root() / "pocketbase.exe",
        _repo_root() / "pocketbase",
        _repo_root() / "operations" / "tools" / "pocketbase" / "pocketbase.exe",
        _repo_root() / "operations" / "tools" / "pocketbase" / "pocketbase",
        _repo_root() / "bin" / "pocketbase.exe",
        _repo_root() / "bin" / "pocketbase",
    ]
    for candidate in candidate_paths:
        if candidate.suffix == ".exe" and os.name != "nt":
            continue  # a Windows PE binary can't run here
        if candidate.exists():
            return str(candidate)

    return None


def recommended_pocketbase_binary_path() -> Path:
    binary_name = "pocketbase.exe" if os.name == "nt" else "pocketbase"
    return _repo_root() / "operations" / "tools" / "pocketbase" / binary_name


def pocketbase_data_dir() -> Path:
    configured_path = os.getenv("POCKETBASE_DATA_DIR")
    if configured_path:
        return Path(configured_path).expanduser()
    return _repo_root() / "operations" / "data" / "pocketbase"


def ensure_pocketbase_superuser(binary_path: str, data_dir: Path) -> tuple[bool, str]:
    email = pocketbase_admin_email()
    password = pocketbase_admin_password()
    result = subprocess.run(
        [
            binary_path,
            "superuser",
            "upsert",
            email,
            password,
            f"--dir={data_dir}",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, f"PocketBase superuser ensured for {email}"

    detail = (result.stderr or result.stdout or "unknown error").strip()
    return False, f"Unable to ensure PocketBase superuser {email}: {detail}"


def ensure_pocketbase_schema() -> tuple[bool, str]:
    try:
        result = ensure_collections(pocketbase_api_url(), pocketbase_admin_email(), pocketbase_admin_password())
    except Exception as exc:
        return False, f"Unable to ensure PocketBase schema: {exc}"
    return True, f"PocketBase Ticket to Ride schema ensured ({result})"


def _pocketbase_host_and_port() -> tuple[str, int]:
    parsed = urlparse(pocketbase_api_url())
    host = parsed.hostname or "127.0.0.1"
    default_port = 443 if parsed.scheme == "https" else 80
    return host, parsed.port or default_port


def start_bot_api_process() -> BotApiLaunchResult:
    base_url = bot_api_base_url()
    parsed = urlparse(base_url)
    scheme = parsed.scheme or "http"
    if scheme != "http":
        return BotApiLaunchResult(
            process=None,
            started=False,
            reachable=False,
            base_url=base_url,
            message=f"Automatic external bot API startup currently expects an http URL, received {base_url}",
        )
    if not _is_loopback_host(parsed.hostname):
        return BotApiLaunchResult(
            process=None,
            started=False,
            reachable=False,
            base_url=base_url,
            message=(
                "Automatic external bot API startup currently expects BOT_API_BASE_URL to use a local loopback host, "
                f"received {base_url}"
            ),
        )
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return BotApiLaunchResult(
            process=None,
            started=False,
            reachable=False,
            base_url=base_url,
            message=(
                "Automatic external bot API startup currently expects BOT_API_BASE_URL without a path or query, "
                f"received {base_url}"
            ),
        )

    if bot_api_is_reachable():
        return BotApiLaunchResult(
            process=None,
            started=False,
            reachable=True,
            base_url=base_url,
            message=f"External bot API is already running at {base_url}",
        )

    host = parsed.hostname or "127.0.0.1"
    default_port = 443 if scheme == "https" else 80
    port = parsed.port or default_port
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "external.clients.bot_api.app:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(_repo_root()),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if not _wait_for_port(host, port, timeout_seconds=5.0):
        _terminate_process(process)
        return BotApiLaunchResult(
            process=None,
            started=False,
            reachable=False,
            base_url=base_url,
            message=f"External bot API failed to start at {base_url}",
        )

    return BotApiLaunchResult(
        process=process,
        started=True,
        reachable=True,
        base_url=base_url,
        message=f"Started external bot API at {base_url}",
    )


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


def start_pocketbase_process() -> PocketBaseLaunchResult:
    if pocketbase_is_reachable():
        schema_ok, schema_message = ensure_pocketbase_schema()
        if not schema_ok:
            raise RuntimeError(schema_message)
        return PocketBaseLaunchResult(
            process=None,
            started=False,
            reachable=True,
            message=f"PocketBase is already running at {pocketbase_api_url()}. {schema_message}",
        )

    binary_path = pocketbase_binary_path()
    if not binary_path:
        return PocketBaseLaunchResult(
            process=None,
            started=False,
            reachable=False,
            binary_path=None,
            message=(
                "PocketBase binary was not found. Put it at "
                f"{recommended_pocketbase_binary_path()} "
                "or set POCKETBASE_BINARY to your pocketbase executable."
            ),
        )

    parsed = urlparse(pocketbase_api_url())
    host, port = _pocketbase_host_and_port()
    scheme = parsed.scheme or "http"
    if scheme != "http":
        return PocketBaseLaunchResult(
            process=None,
            started=False,
            reachable=False,
            binary_path=binary_path,
            message=f"Automatic PocketBase startup currently expects an http URL, received {pocketbase_api_url()}",
        )

    data_dir = pocketbase_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    ensured, ensure_message = ensure_pocketbase_superuser(binary_path, data_dir)
    if not ensured:
        return PocketBaseLaunchResult(
            process=None,
            started=False,
            reachable=False,
            binary_path=binary_path,
            message=ensure_message,
        )

    process = subprocess.Popen(
        [
            binary_path,
            "serve",
            f"--http={host}:{port}",
            f"--dir={data_dir}",
        ],
        cwd=str(_repo_root()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if not _wait_for_port(host, port, timeout_seconds=5.0):
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        return PocketBaseLaunchResult(
            process=None,
            started=False,
            reachable=False,
            binary_path=binary_path,
            message=f"PocketBase failed to start at {pocketbase_api_url()} using {binary_path}",
        )

    schema_ok, schema_message = ensure_pocketbase_schema()
    if not schema_ok:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        raise RuntimeError(schema_message)

    return PocketBaseLaunchResult(
        process=process,
        started=True,
        reachable=True,
        binary_path=binary_path,
        message=f"Started PocketBase with {binary_path} at {pocketbase_api_url()}. {ensure_message}. {schema_message}",
    )


class BootstrapRandomActionBot:
    """Minimal in-runtime random bot so seeding never imports integrations/external."""

    def set_player(self, player) -> None:
        self.player = player

    def act(self, view, legal_actions):
        return random.choice(legal_actions)


def _bootstrap_players() -> list[Player]:
    player_names = ["random_1", "random_2"]
    player_colors = ["red", "blue"]
    return [
        Player(f"bot_{index}", BootstrapRandomActionBot(), player_names[index], player_colors[index])
        for index in range(2)
    ]


def seed_match_if_empty_via_api(api_base_url: str, round_limit: int = 10) -> bool:
    transport = JsonHttpTransport(api_base_url)
    probe_logger = GameLogger([], transport=transport)
    if probe_logger.list_matches():
        return False

    players = _bootstrap_players()
    logger = GameLogger(players, transport=transport)
    context = GameContext([player.player_id for player in players])
    logger.start_match(
        "-".join(player.name for player in players),
        map_name=context.get_map().map_name,
        seed=context.seed,
    )

    for round_number in range(round_limit):
        logger.start_round(round_number)
        if round_number:
            context = GameContext([player.player_id for player in players])
        game = Game(context, players, logger, round_number)
        game.play()

        if round_number != round_limit - 1:
            players = [
                Player(player.player_id, player.get_interface(), player.name, player.color)
                for player in players
            ]
            logger.set_player_list(players)

    logger.finalize_match()
    return True


def resolve_runtime_storage_backend(pocketbase_launch: PocketBaseLaunchResult) -> str:
    configured_backend = os.getenv("MATCH_LOG_STORAGE_BACKEND")
    if configured_backend:
        return configured_backend.lower()

    if pocketbase_launch.reachable or pocketbase_is_reachable():
        return "pocketbase"

    return "memory"


def _bootstrap_managed_match_request() -> dict[str, object]:
    return {
        "name": DEFAULT_BOOTSTRAP_MATCH_NAME,
        "seats": [
            {"seatId": "seat_1", "primaryBotId": DEFAULT_BOOTSTRAP_BOT_ID},
            {"seatId": "seat_2", "primaryBotId": DEFAULT_BOOTSTRAP_BOT_ID},
        ],
        "fallbackBotId": DEFAULT_BOOTSTRAP_BOT_ID,
        "roundCount": 3,
        "timeControl": {
            "initialTimeMs": 60000,
            "incrementMs": 0,
            "perCallSoftLimitMs": None,
            "perCallHardLimitMs": None,
        },
        "timeoutPolicy": "loss_on_time",
        "executionMode": "bot_api",
    }


def bootstrap_managed_random_match_via_api(api_base_url: str) -> bool:
    transport = JsonHttpTransport(api_base_url)

    try:
        transport.request("POST", "/bots", {"botId": DEFAULT_BOOTSTRAP_BOT_ID})
    except LoggerClientError as exc:
        raise RuntimeError(
            "Backend /bots registration failed for "
            f"'{DEFAULT_BOOTSTRAP_BOT_ID}' while using BOT_API_BASE_URL {bot_api_base_url()}: {exc}"
        ) from exc

    try:
        replay_matches = transport.request("GET", "/matches")
        managed_matches = transport.request("GET", "/managed-matches")
    except LoggerClientError as exc:
        raise RuntimeError(f"Unable to inspect existing backend matches at {api_base_url}: {exc}") from exc

    if replay_matches or managed_matches:
        return False

    try:
        transport.request("POST", "/managed-matches", _bootstrap_managed_match_request())
    except LoggerClientError as exc:
        raise RuntimeError(f"Unable to create the startup managed match at {api_base_url}: {exc}") from exc

    return True


def start_backend_process(host: str, port: int, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ticket_to_ride.backend.app:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(_repo_root()),
        env=env,
        text=True,
    )

    if _wait_for_port(host, port, timeout_seconds=5.0):
        return process

    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    raise RuntimeError(f"Backend failed to start at http://{host}:{port}")


def run() -> None:
    host = os.getenv("TICKET_TO_RIDE_HOST", "127.0.0.1")
    port = int(os.getenv("TICKET_TO_RIDE_PORT", "8000"))
    viewer_host = os.getenv("TICKET_TO_RIDE_VIEWER_HOST", "127.0.0.1")
    viewer_port = int(os.getenv("TICKET_TO_RIDE_VIEWER_PORT", "4173"))
    os.environ.setdefault("POCKETBASE_ADMIN_EMAIL", pocketbase_admin_email())
    os.environ.setdefault("POCKETBASE_ADMIN_PASSWORD", pocketbase_admin_password())
    pocketbase_launch = start_pocketbase_process()
    if pocketbase_launch.message:
        print(pocketbase_launch.message)
    viewer_launch = _start_viewer_runtime(viewer_host, viewer_port)
    if viewer_launch.message:
        print(viewer_launch.message)
    backend_process: subprocess.Popen[str] | None = None
    bot_api_launch = BotApiLaunchResult(process=None, started=False, reachable=False)
    backend_env = os.environ.copy()
    runtime_storage_backend = resolve_runtime_storage_backend(pocketbase_launch)
    backend_env["MATCH_LOG_STORAGE_BACKEND"] = runtime_storage_backend
    if runtime_storage_backend == "memory":
        print("PocketBase storage is unavailable for this run. Falling back to in-memory backend storage.")

    try:
        backend_process = start_backend_process(host, port, env=backend_env)
        print(f"Backend is ready at http://{host}:{port}")
        if bot_api_enabled():
            bot_api_launch = start_bot_api_process()
            if bot_api_launch.message:
                print(bot_api_launch.message)
            if not bot_api_launch.reachable:
                raise RuntimeError(
                    bot_api_launch.message
                    or f"External bot API is unavailable at {bot_api_base_url()}."
                )

            bootstrapped = bootstrap_managed_random_match_via_api(f"http://{host}:{port}")
            if bootstrapped:
                print(
                    "Registered random_bot and created a 3-round managed match with a 1-minute clock."
                )
            else:
                print(
                    "Registered random_bot. Existing replay or managed matches found, so the startup managed match was skipped."
                )
        else:
            try:
                seeded = seed_match_if_empty_via_api(
                    f"http://{host}:{port}",
                    round_limit=int(os.getenv("TICKET_TO_RIDE_BOOTSTRAP_ROUNDS", "10")),
                )
                if seeded:
                    print("No matches found. Seeded a bootstrap match with 2 random bots.")
            except LoggerClientError as exc:
                print(f"Skipping bootstrap match creation because the backend API is unavailable: {exc}")

        viewer_url = build_viewer_url(viewer_host, viewer_port, host, port)
        _wait_for_port(viewer_host, viewer_port)
        _open_default_browser(viewer_url)
        if pocketbase_launch.reachable or pocketbase_is_reachable():
            print(f"PocketBase admin UI available at {pocketbase_url()}")
        else:
            print(
                f"PocketBase is unavailable. Admin UI expected at {pocketbase_url()}. "
                f"Recommended local install path: {recommended_pocketbase_binary_path()}. "
                "If PocketBase is installed elsewhere, set POCKETBASE_BINARY to the full executable path."
            )

        if backend_process is not None:
            backend_process.wait()
    finally:
        _stop_viewer_runtime(viewer_launch)
        _terminate_process(backend_process)
        _terminate_process(bot_api_launch.process)
        _terminate_process(pocketbase_launch.process)


def test() -> None:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "quality/tests"], check=False)
    raise SystemExit(result.returncode)
