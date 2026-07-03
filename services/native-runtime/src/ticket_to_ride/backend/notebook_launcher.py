from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol


class ProcessSpawner(Protocol):
    def __call__(self, notebook_path: str, port: int) -> "subprocess.Popen[bytes]": ...


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def default_spawner(notebook_path: str, port: int) -> "subprocess.Popen[bytes]":
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "edit",
            notebook_path,
            "--port",
            str(port),
            "--headless",
        ],
        cwd=str(_repo_root()),
    )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class NotebookSession:
    bot_id: str
    port: int
    process: "subprocess.Popen[bytes]"

    def is_running(self) -> bool:
        return self.process.poll() is None


class NotebookLauncher:
    """Spawns (or reuses) one `marimo edit` server per bot notebook."""

    def __init__(
        self,
        spawner: Optional[ProcessSpawner] = None,
        port_allocator: Optional[Callable[[], int]] = None,
        host: str = "127.0.0.1",
    ) -> None:
        self._spawner = spawner or default_spawner
        self._port_allocator = port_allocator or _find_free_port
        self._host = host
        self._sessions: Dict[str, NotebookSession] = {}

    def launch(self, bot_id: str, notebook_path: str) -> str:
        existing = self._sessions.get(bot_id)
        if existing is not None and existing.is_running():
            return self._url_for(existing.port)

        port = self._port_allocator()
        process = self._spawner(notebook_path, port)
        self._sessions[bot_id] = NotebookSession(bot_id=bot_id, port=port, process=process)
        return self._url_for(port)

    def _url_for(self, port: int) -> str:
        return f"http://{self._host}:{port}"
