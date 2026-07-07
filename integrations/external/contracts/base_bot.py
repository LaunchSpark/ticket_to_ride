from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .abstract_interface import Interface


class BaseBot(Interface, ABC):
    """Metadata-aware bot base that preserves the engine-facing decision contract."""

    META: Dict[str, Any] = {}

    def __init__(self) -> None:
        super().__init__()
        meta = dict(getattr(self, "META", {}) or {})
        self.bot_id = str(meta.get("id", "") or "")
        self.name = str(meta.get("name", "") or "")
        self.version = str(meta.get("version", "") or "")
        self.description = str(meta.get("description", "") or "")
        self.author = str(meta.get("author", "") or "")
        self.tags = [str(tag) for tag in meta.get("tags", []) if str(tag)]

    def info(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.META.get("schema_version"),
            "botId": self.bot_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": list(self.tags),
        }

    @abstractmethod
    def choose_turn_action(self):
        raise NotImplementedError

    @abstractmethod
    def choose_draw_train_action(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def choose_route_to_claim(self, claimable_routes):
        raise NotImplementedError

    @abstractmethod
    def choose_color_to_spend(self, route, color_options):
        raise NotImplementedError

    @abstractmethod
    def select_ticket_offer(self, offer) -> List[Any]:
        raise NotImplementedError


class ActionBot(BaseBot):
    """New-style bot: implement act(view, legal_actions) -> action.

    view is a ticket_to_ride PlayerView; legal_actions is a non-empty list
    of engine Action dataclasses. Returning anything outside the list makes
    the engine take legal_actions[0] instead. The legacy choose_* contract
    is stubbed out — the engine never calls it on a bot that defines act().
    """

    @abstractmethod
    def act(self, view: Any, legal_actions: List[Any]) -> Any:
        raise NotImplementedError

    def choose_turn_action(self):
        raise RuntimeError("action bots decide via act()")

    def choose_draw_train_action(self) -> int:
        raise RuntimeError("action bots decide via act()")

    def choose_route_to_claim(self, claimable_routes):
        raise RuntimeError("action bots decide via act()")

    def choose_color_to_spend(self, route, color_options):
        raise RuntimeError("action bots decide via act()")

    def select_ticket_offer(self, offer) -> List[Any]:
        raise RuntimeError("action bots decide via act()")
