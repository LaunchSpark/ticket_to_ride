from __future__ import annotations

import ipaddress
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BOT_API_BASE_URL = "http://127.0.0.1:8001"
LOCAL_API_SOURCE_KIND = "local_api"
LOCAL_API_DISCOVERY_PATH = "/bots"
BOT_API_ENABLE_ENV = "TICKET_TO_RIDE_ENABLE_BOT_API"


class BotCatalogError(RuntimeError):
    """Raised when the configured bot catalog cannot be queried safely."""


@dataclass(frozen=True)
class BotCatalogRecord:
    schema_version: int
    bot_id: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    source_kind: str
    source_base_url: str
    discovery_path: str
    module_path: str


class BotCatalogClient(ABC):
    @abstractmethod
    def list_bots(self) -> list[BotCatalogRecord]:
        raise NotImplementedError

    @abstractmethod
    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        raise NotImplementedError


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False

    if hostname.lower() == "localhost":
        return True

    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class LocalApiBotCatalogClient(BotCatalogClient):
    def __init__(
        self,
        base_url: str | None = None,
        *,
        discovery_path: str = LOCAL_API_DISCOVERY_PATH,
        timeout_seconds: int = 5,
        require_loopback: bool = True,
    ) -> None:
        self.base_url = (base_url or os.getenv("BOT_API_BASE_URL", DEFAULT_BOT_API_BASE_URL)).rstrip("/")
        self.discovery_path = discovery_path if discovery_path.startswith("/") else f"/{discovery_path}"
        self.timeout_seconds = timeout_seconds
        self.require_loopback = require_loopback

    def list_bots(self) -> list[BotCatalogRecord]:
        self._ensure_local_base_url()
        payload = self._request_json("GET", self.discovery_path)
        if not isinstance(payload, list):
            raise BotCatalogError("Bot catalog discovery response must be a JSON array of bot metadata objects.")

        records: list[BotCatalogRecord] = []
        for item in payload:
            records.append(self._parse_bot_record(item))

        return sorted(records, key=lambda record: (record.name.casefold(), record.bot_id.casefold()))

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        requested_bot_id = bot_id.strip()
        if not requested_bot_id:
            raise BotCatalogError("Bot ID is required.")

        requested_key = requested_bot_id.casefold()
        for record in self.list_bots():
            if record.bot_id.casefold() == requested_key:
                return record

        raise KeyError(f"Unknown bot '{requested_bot_id}'.")

    def _parse_bot_record(self, payload: Any) -> BotCatalogRecord:
        if not isinstance(payload, dict):
            raise BotCatalogError("Bot catalog entries must be JSON objects.")

        schema_version = payload.get("schemaVersion")
        bot_id = payload.get("botId")
        name = payload.get("name")
        version = payload.get("version")
        description = payload.get("description")
        author = payload.get("author") or ""
        tags = payload.get("tags") or []
        module_path = payload.get("modulePath") or ""

        if schema_version != 1:
            raise BotCatalogError("Bot catalog entries must declare schemaVersion 1.")
        if not isinstance(bot_id, str) or not bot_id.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty botId.")
        if not isinstance(name, str) or not name.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty name.")
        if not isinstance(version, str) or not version.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty version.")
        if not isinstance(description, str) or not description.strip():
            raise BotCatalogError("Bot catalog entries must include a non-empty description.")
        if not isinstance(author, str):
            raise BotCatalogError("Bot catalog entry author must be a string.")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise BotCatalogError("Bot catalog entry tags must be a list of strings.")

        return BotCatalogRecord(
            schema_version=1,
            bot_id=bot_id.strip(),
            name=name.strip(),
            version=version.strip(),
            description=description.strip(),
            author=author.strip(),
            tags=[tag.strip() for tag in tags if tag.strip()],
            source_kind=LOCAL_API_SOURCE_KIND,
            source_base_url=self.base_url,
            discovery_path=self.discovery_path,
            module_path=str(module_path).strip(),
        )

    def _ensure_local_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise BotCatalogError("Configured BOT_API_BASE_URL must use http or https.")
        if self.require_loopback and not _is_loopback_host(parsed.hostname):
            raise BotCatalogError("Configured BOT_API_BASE_URL must point to a local loopback host in v1.")

    def _request_json(self, method: str, path: str) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method=method,
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BotCatalogError(f"Bot catalog request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise BotCatalogError(f"Bot catalog request failed: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BotCatalogError("Bot catalog returned invalid JSON.") from exc


class LocalModuleBotCatalogClient(BotCatalogClient):
    """Discover repository bots directly, without requiring an HTTP sidecar."""

    def __init__(self, loader=None) -> None:
        if loader is None:
            from external.clients.bot_api.loader import BotLoader

            loader = BotLoader()
        self.loader = loader

    def list_bots(self) -> list[BotCatalogRecord]:
        try:
            descriptors = self.loader.load_bots().values()
        except Exception as exc:
            raise BotCatalogError(f"Local bot discovery failed: {exc}") from exc

        records = [
            BotCatalogRecord(
                schema_version=descriptor.metadata.schemaVersion,
                bot_id=descriptor.metadata.botId,
                name=descriptor.metadata.name,
                version=descriptor.metadata.version,
                description=descriptor.metadata.description,
                author=descriptor.metadata.author,
                tags=list(descriptor.metadata.tags),
                # Keep the persisted v1 source schema stable. Local execution
                # uses module_path; the API URL remains useful if the opt-in
                # sidecar is enabled for a later run.
                source_kind=LOCAL_API_SOURCE_KIND,
                source_base_url=DEFAULT_BOT_API_BASE_URL,
                discovery_path=LOCAL_API_DISCOVERY_PATH,
                module_path=descriptor.module_path,
            )
            for descriptor in descriptors
        ]
        return sorted(records, key=lambda record: (record.name.casefold(), record.bot_id.casefold()))

    def resolve_bot(self, bot_id: str) -> BotCatalogRecord:
        requested_bot_id = bot_id.strip()
        if not requested_bot_id:
            raise BotCatalogError("Bot ID is required.")
        requested_key = requested_bot_id.casefold()
        for record in self.list_bots():
            if record.bot_id.casefold() == requested_key:
                return record
        raise KeyError(f"Unknown bot '{requested_bot_id}'.")


def build_bot_catalog_client_from_env() -> BotCatalogClient:
    if os.getenv(BOT_API_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return LocalApiBotCatalogClient()
    return LocalModuleBotCatalogClient()
