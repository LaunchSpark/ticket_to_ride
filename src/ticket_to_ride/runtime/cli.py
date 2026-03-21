from __future__ import annotations

import os
import re
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

from ticket_to_ride.backend.bootstrap_pocketbase import ensure_collections
from ticket_to_ride.backend.service import create_match, create_round, create_turn, finalize_match, get_match, list_matches
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.logging.game_logger import GameLogger, JsonHttpTransport, LoggerClientError

DEFAULT_POCKETBASE_ADMIN_EMAIL = "admin@example.com"
DEFAULT_POCKETBASE_ADMIN_PASSWORD = "12345678"


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


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".jsx": "text/javascript",
    }


class RepositoryLoggerTransport:
    def __init__(self, repository) -> None:
        self.repository = repository
        self._round_ids_by_match: dict[str, dict[str, str]] = {}

    def request(self, method: str, path: str, payload=None):
        payload = payload or {}

        if method == "POST" and path == "/matches":
            match_id = create_match(
                self.repository,
                name=payload["name"],
                players=[self._player_record(player) for player in payload["players"]],
                player_names=list(payload.get("playerNames", [])),
            )
            return {"matchId": match_id}

        if method == "POST" and path.endswith("/finalize"):
            match_id = path.split("/")[2]
            average_scores = finalize_match(self.repository, match_id)
            return {"matchId": match_id, "status": "completed", "averageScores": [score.model_dump() for score in average_scores]}

        if method == "GET" and path == "/matches":
            return [match.model_dump() for match in list_matches(self.repository)]

        if method == "GET" and path.startswith("/matches/"):
            match_id = path.split("/")[2]
            return get_match(self.repository, match_id).model_dump()

        round_match = re.fullmatch(r"/matches/([^/]+)/rounds", path)
        if method == "POST" and round_match:
            match_id = round_match.group(1)
            round_number = payload["roundNumber"]
            round_id = create_round(self.repository, match_id, round_number)
            self._round_ids_by_match.setdefault(match_id, {})[str(round_number)] = round_id
            return {"roundId": round_id}

        turn_match = re.fullmatch(r"/matches/([^/]+)/rounds/([^/]+)/turns", path)
        if method == "POST" and turn_match:
            match_id, round_id = turn_match.groups()
            turn_id = create_turn(
                self.repository,
                match_id=match_id,
                round_id=round_id,
                turn_index=payload["turnIndex"],
                turn_state=payload["turnState"],
            )
            return {"turnId": turn_id}

        raise ValueError(f"Unsupported repository transport request: {method} {path}")

    @staticmethod
    def _player_record(player_payload):
        from ticket_to_ride.backend.models import PlayerRecord

        return PlayerRecord.model_validate(player_payload)


class BootstrapRandomBot:
    def __init__(self) -> None:
        self.player = None

    def set_player(self, player) -> None:
        self.player = player

    def choose_turn_action(self):
        affordable_routes = self.player.get_affordable_routes() if self.player else None
        if not len([ticket for ticket in self.player.get_tickets() if not ticket.is_completed]):
            return 3
        if affordable_routes:
            return 2
        return 1

    def choose_draw_train_action(self) -> int:
        return random.randrange(-1, 5)

    def choose_route_to_claim(self, claimable_routes):
        return claimable_routes[random.randrange(0, len(claimable_routes))]

    def choose_color_to_spend(self, route, color_options):
        return None

    def select_ticket_offer(self, offer):
        if len(offer) >= 2:
            return [offer[0], offer[1]]
        return list(offer)


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


def pocketbase_is_reachable() -> bool:
    parsed = urlparse(pocketbase_api_url())
    host = parsed.hostname or "127.0.0.1"
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    return _wait_for_port(host, port, timeout_seconds=1.0)


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
    viewer_root = Path(__file__).resolve().parents[3] / "apps" / "viewer"
    handler = partial(ViewerRequestHandler, directory=str(viewer_root))
    server = ThreadingHTTPServer((viewer_host, viewer_port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_vite_viewer(viewer_host: str, viewer_port: int) -> subprocess.Popen[str] | None:
    viewer_root = _repo_root() / "apps" / "viewer"
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
        message=f"Viewer is running in static mode at http://{viewer_host}:{viewer_port} (install apps/viewer dependencies for Vite live reload)",
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
    return Path(__file__).resolve().parents[3]


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
        _repo_root() / "tools" / "pocketbase" / "pocketbase.exe",
        _repo_root() / "tools" / "pocketbase" / "pocketbase",
        _repo_root() / "bin" / "pocketbase.exe",
        _repo_root() / "bin" / "pocketbase",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return str(candidate)

    return None


def recommended_pocketbase_binary_path() -> Path:
    return _repo_root() / "tools" / "pocketbase" / "pocketbase.exe"


def pocketbase_data_dir() -> Path:
    configured_path = os.getenv("POCKETBASE_DATA_DIR")
    if configured_path:
        return Path(configured_path).expanduser()
    return _repo_root() / "data" / "pocketbase"


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


def _bootstrap_players() -> list[Player]:
    player_names = ["random_1", "random_2"]
    player_colors = ["red", "blue"]
    return [
        Player(f"bot_{index}", BootstrapRandomBot(), player_names[index], player_colors[index])
        for index in range(2)
    ]


def seed_match_if_empty(repository, round_limit: int = 10) -> bool:
    existing_matches = list_matches(repository)
    if existing_matches:
        return False

    players = _bootstrap_players()
    logger = GameLogger(players, transport=RepositoryLoggerTransport(repository))
    logger.start_match("-".join(player.name for player in players))

    for round_number in range(round_limit):
        logger.start_round(round_number)
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


def seed_match_if_empty_via_api(api_base_url: str, round_limit: int = 10) -> bool:
    transport = JsonHttpTransport(api_base_url)
    probe_logger = GameLogger([], transport=transport)
    if probe_logger.list_matches():
        return False

    players = _bootstrap_players()
    logger = GameLogger(players, transport=transport)
    logger.start_match("-".join(player.name for player in players))

    for round_number in range(round_limit):
        logger.start_round(round_number)
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
    backend_env = os.environ.copy()
    runtime_storage_backend = resolve_runtime_storage_backend(pocketbase_launch)
    backend_env["MATCH_LOG_STORAGE_BACKEND"] = runtime_storage_backend
    if runtime_storage_backend == "memory":
        print("PocketBase storage is unavailable for this run. Falling back to in-memory backend storage.")

    try:
        backend_process = start_backend_process(host, port, env=backend_env)
        print(f"Backend is ready at http://{host}:{port}")
    except RuntimeError as exc:
        _stop_viewer_runtime(viewer_launch)
        if pocketbase_launch.process is not None:
            pocketbase_launch.process.terminate()
            try:
                pocketbase_launch.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pocketbase_launch.process.kill()
        raise RuntimeError(str(exc)) from exc

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

    try:
        if backend_process is not None:
            backend_process.wait()
    finally:
        _stop_viewer_runtime(viewer_launch)
        if backend_process is not None:
            backend_process.terminate()
            try:
                backend_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                backend_process.kill()
        if pocketbase_launch.process is not None:
            pocketbase_launch.process.terminate()
            try:
                pocketbase_launch.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pocketbase_launch.process.kill()


def test() -> None:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], check=False)
    raise SystemExit(result.returncode)
