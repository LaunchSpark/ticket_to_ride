from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any, Dict, List
from uuid import uuid4

import external.bots
from external.contracts.abstract_interface import Interface
from external.clients.bot_api.views import player_view_from_payload, route_from_payload, ticket_from_payload, ticket_key


class BotSessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Interface] = {}

    def create_session(self, bot_name: str) -> str:
        bot_class = self._load_bot_class(bot_name)
        session_id = str(uuid4())
        self.sessions[session_id] = bot_class()
        return session_id

    def get_session(self, session_id: str) -> Interface:
        if session_id not in self.sessions:
            raise KeyError(f"Unknown bot session '{session_id}'.")
        return self.sessions[session_id]

    def build_player(self, payload: Dict[str, Any]):
        return player_view_from_payload(payload)

    def choose_turn_action(self, session_id: str, player_payload: Dict[str, Any]) -> int:
        bot = self.get_session(session_id)
        bot.set_player(self.build_player(player_payload))
        return int(bot.choose_turn_action())

    def choose_draw_train_action(self, session_id: str, player_payload: Dict[str, Any]) -> int:
        bot = self.get_session(session_id)
        bot.set_player(self.build_player(player_payload))
        return int(bot.choose_draw_train_action())

    def choose_route_to_claim(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        claimable_routes_payload: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        bot = self.get_session(session_id)
        bot.set_player(self.build_player(player_payload))
        claimable_routes = [
            (route_from_payload(option["route"]), option["locomotives"])
            for option in claimable_routes_payload
        ]
        selection = bot.choose_route_to_claim(claimable_routes)

        if isinstance(selection, tuple):
            selected_route, locomotives = selection
        else:
            selected_route, locomotives = selection, None

        selected_index = next(
            (index for index, (route, _) in enumerate(claimable_routes) if repr(route) == repr(selected_route)),
            None,
        )
        if selected_index is None:
            raise ValueError("Bot selected a route that was not present in the provided options.")

        if locomotives is None:
            locomotives = claimable_routes[selected_index][1]

        return {"selectedIndex": selected_index, "locomotives": int(locomotives)}

    def choose_color_to_spend(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        route_payload: Dict[str, Any],
        color_options: List[str],
    ) -> Any:
        bot = self.get_session(session_id)
        bot.set_player(self.build_player(player_payload))
        route = route_from_payload(route_payload)
        return bot.choose_color_to_spend(route, color_options)

    def select_ticket_offer(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        offer_payload: List[Dict[str, Any]],
    ) -> List[int]:
        bot = self.get_session(session_id)
        bot.set_player(self.build_player(player_payload))
        offer = [ticket_from_payload(ticket_payload) for ticket_payload in offer_payload]
        selected_tickets = bot.select_ticket_offer(offer)
        selected_keys = [ticket_key(ticket) for ticket in selected_tickets]

        selected_indices: List[int] = []
        for index, ticket in enumerate(offer):
            if ticket_key(ticket) in selected_keys:
                selected_indices.append(index)
        return selected_indices

    @staticmethod
    def available_bot_names() -> List[str]:
        bot_names: List[str] = []
        for _, module_name, _ in pkgutil.iter_modules(external.bots.__path__):
            if module_name == "__init__":
                continue
            module = importlib.import_module(f"external.bots.{module_name}")
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Interface) and obj is not Interface:
                    bot_names.append(name)
        return sorted(set(bot_names))

    @staticmethod
    def _load_bot_class(bot_name: str):
        for _, module_name, _ in pkgutil.iter_modules(external.bots.__path__):
            if module_name == "__init__":
                continue
            module = importlib.import_module(f"external.bots.{module_name}")
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if name == bot_name and issubclass(obj, Interface) and obj is not Interface:
                    return obj
        raise KeyError(f"Unknown bot '{bot_name}'.")
