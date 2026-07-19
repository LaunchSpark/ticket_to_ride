from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ticket_to_ride.backend.bot_catalog import (
    BotCatalogClient,
    BotCatalogRecord,
    LocalApiBotCatalogClient,
    build_bot_catalog_client_from_env,
)
from ticket_to_ride.backend.repository import MatchRepository

logger = logging.getLogger(__name__)

REMOTE_TIMEOUT_SECONDS = 3
MAX_CONCURRENT_CONNECTION_FETCHES = 8


@dataclass(frozen=True)
class DirectoryBot:
    bot_id: str
    name: str
    version: str
    description: str
    author: str
    tags: List[str]
    source: str
    connection_id: Optional[str]
    base_url: Optional[str]
    module_path: str


@dataclass(frozen=True)
class ConnectionStatus:
    connection_id: str
    url: str
    status: str
    error: Optional[str]
    bot_count: int
    created_at: str


@dataclass(frozen=True)
class DirectoryListing:
    bots: List[DirectoryBot]
    connections: List[ConnectionStatus]


def default_remote_catalog_factory(url: str) -> BotCatalogClient:
    return LocalApiBotCatalogClient(url, require_loopback=False, timeout_seconds=REMOTE_TIMEOUT_SECONDS)


def _local_bot(record: BotCatalogRecord) -> DirectoryBot:
    return DirectoryBot(
        bot_id=record.bot_id,
        name=record.name,
        version=record.version,
        description=record.description,
        author=record.author,
        tags=list(record.tags),
        source="local",
        connection_id=None,
        base_url=None,
        module_path=record.module_path,
    )


def _remote_bot(record: BotCatalogRecord, connection: Dict[str, Any]) -> DirectoryBot:
    return DirectoryBot(
        bot_id=record.bot_id,
        name=record.name,
        version=record.version,
        description=record.description,
        author=record.author,
        tags=list(record.tags),
        source="remote",
        connection_id=connection["id"],
        base_url=connection["url"],
        module_path="",
    )


class BotDirectory:
    """Live merged view of locally discoverable bots and remote bot connections.

    Local bots are rediscovered on every call (fresh catalog client per call);
    connections are pinged concurrently so one dead host does not stall listing.
    """

    def __init__(
        self,
        repository: MatchRepository,
        *,
        local_catalog_factory: Optional[Callable[[], BotCatalogClient]] = None,
        remote_catalog_factory: Optional[Callable[[str], BotCatalogClient]] = None,
    ) -> None:
        self.repository = repository
        self.local_catalog_factory = local_catalog_factory or build_bot_catalog_client_from_env
        self.remote_catalog_factory = remote_catalog_factory or default_remote_catalog_factory

    def list_all(self) -> DirectoryListing:
        bots: Dict[str, DirectoryBot] = {}
        for record in self.local_catalog_factory().list_bots():
            bots[record.bot_id] = _local_bot(record)

        connection_records = self.repository.list_bot_connections()
        connections: List[ConnectionStatus] = []
        for connection, result in zip(connection_records, self._fetch_all(connection_records)):
            if isinstance(result, Exception):
                connections.append(
                    ConnectionStatus(
                        connection_id=connection["id"],
                        url=connection["url"],
                        status="offline",
                        error=str(result),
                        bot_count=0,
                        created_at=connection["createdAt"],
                    )
                )
                continue

            for record in result:
                if record.bot_id in bots:
                    logger.warning(
                        "Bot id '%s' from connection %s is shadowed by an earlier source.",
                        record.bot_id,
                        connection["url"],
                    )
                    continue
                bots[record.bot_id] = _remote_bot(record, connection)

            connections.append(
                ConnectionStatus(
                    connection_id=connection["id"],
                    url=connection["url"],
                    status="online",
                    error=None,
                    bot_count=len(result),
                    created_at=connection["createdAt"],
                )
            )

        sorted_bots = sorted(bots.values(), key=lambda bot: (bot.name.casefold(), bot.bot_id.casefold()))
        return DirectoryListing(bots=sorted_bots, connections=connections)

    def resolve(self, bot_id: str) -> DirectoryBot:
        requested = bot_id.strip()
        if not requested:
            raise KeyError("Bot ID is required.")
        requested_key = requested.casefold()
        for bot in self.list_all().bots:
            if bot.bot_id.casefold() == requested_key:
                return bot
        raise KeyError(f"Unknown bot '{requested}'.")

    def _fetch_all(self, connection_records: List[Dict[str, Any]]) -> List[Any]:
        if not connection_records:
            return []

        def fetch(record: Dict[str, Any]) -> List[BotCatalogRecord]:
            return self.remote_catalog_factory(record["url"]).list_bots()

        max_workers = min(len(connection_records), MAX_CONCURRENT_CONNECTION_FETCHES)
        results: List[Any] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(fetch, record) for record in connection_records]
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:  # offline connections must not break listing
                    results.append(exc)
        return results
