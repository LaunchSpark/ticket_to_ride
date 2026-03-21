from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from uuid import uuid4

from external.clients.bot_api.loader import BotDescriptor, BotLoader
from external.clients.bot_api.models import BotMetadata
from external.clients.bot_api.views import player_view_from_payload, route_from_payload, ticket_from_payload, ticket_key
from external.contracts.abstract_interface import Interface


@dataclass
class BotSession:
    session_id: str
    bot_id: str
    bot: Interface


class InvalidBotResponseError(ValueError):
    """Raised when a bot returns a payload outside the expected contract."""


class BotExecutionError(RuntimeError):
    """Raised when a bot crashes or returns invalid data during execution."""

    def __init__(self, session_id: str, bot_id: str, action: str, detail: str, error_type: str = "bot_exception") -> None:
        self.session_id = session_id
        self.bot_id = bot_id
        self.action = action
        self.error = detail or "Unknown bot execution error."
        self.error_type = error_type
        message = f"Bot '{bot_id}' failed during {action}: {self.error}"
        super().__init__(message)

    def to_response(self) -> Dict[str, str]:
        return {
            "detail": str(self),
            "botId": self.bot_id,
            "sessionId": self.session_id,
            "action": self.action,
            "error": self.error,
            "errorType": self.error_type,
        }


class BotSessionManager:
    def __init__(
        self,
        loader: BotLoader | None = None,
        descriptors: Dict[str, BotDescriptor] | None = None,
    ) -> None:
        self.loader = loader or BotLoader()
        self.descriptors = descriptors or self.loader.load_bots()
        self.sessions: Dict[str, BotSession] = {}

    def create_session(self, bot_id: str) -> str:
        descriptor = self.descriptors.get(bot_id)
        if descriptor is None:
            raise KeyError(f"Unknown bot '{bot_id}'.")

        session_id = str(uuid4())
        self.sessions[session_id] = BotSession(
            session_id=session_id,
            bot_id=descriptor.bot_id,
            bot=descriptor.bot_class(),
        )
        return session_id

    def get_session(self, session_id: str) -> BotSession:
        if session_id not in self.sessions:
            raise KeyError(f"Unknown bot session '{session_id}'.")
        return self.sessions[session_id]

    def delete_session(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise KeyError(f"Unknown bot session '{session_id}'.")
        del self.sessions[session_id]

    def list_bots(self) -> List[BotMetadata]:
        return BotLoader.sort_metadata([descriptor.metadata for descriptor in self.descriptors.values()])

    @staticmethod
    def build_player(payload: Dict[str, Any]):
        return player_view_from_payload(payload)

    def choose_turn_action(self, session_id: str, player_payload: Dict[str, Any]) -> int:
        return self._execute_bot_action(
            session_id,
            player_payload,
            "choose_turn_action",
            lambda bot: self._validate_turn_action(int(bot.choose_turn_action())),
        )

    def choose_draw_train_action(self, session_id: str, player_payload: Dict[str, Any]) -> int:
        return self._execute_bot_action(
            session_id,
            player_payload,
            "choose_draw_train_action",
            lambda bot: self._validate_draw_index(int(bot.choose_draw_train_action())),
        )

    def choose_route_to_claim(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        claimable_routes_payload: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        def choose(bot: Interface) -> Dict[str, int]:
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
                raise InvalidBotResponseError("Bot selected a route that was not present in the provided options.")

            if locomotives is None:
                locomotives = claimable_routes[selected_index][1]

            normalized_locomotives = int(locomotives)
            if normalized_locomotives < 0:
                raise InvalidBotResponseError("Bot selected a negative number of locomotives.")
            return {"selectedIndex": selected_index, "locomotives": normalized_locomotives}

        return self._execute_bot_action(session_id, player_payload, "choose_route_to_claim", choose)

    def choose_color_to_spend(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        route_payload: Dict[str, Any],
        color_options: List[str],
    ) -> Any:
        route = route_from_payload(route_payload)
        return self._execute_bot_action(
            session_id,
            player_payload,
            "choose_color_to_spend",
            lambda bot: self._validate_color_choice(bot.choose_color_to_spend(route, color_options), color_options),
        )

    def select_ticket_offer(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        offer_payload: List[Dict[str, Any]],
    ) -> List[int]:
        def choose(bot: Interface) -> List[int]:
            offer = [ticket_from_payload(ticket_payload) for ticket_payload in offer_payload]
            selected_tickets = bot.select_ticket_offer(offer)
            selected_keys = [ticket_key(ticket) for ticket in selected_tickets]
            if not selected_keys:
                raise InvalidBotResponseError("Bot must keep at least one destination ticket.")

            selected_indices: List[int] = []
            for index, ticket in enumerate(offer):
                if ticket_key(ticket) in selected_keys:
                    selected_indices.append(index)
            if len(selected_indices) != len(selected_keys):
                raise InvalidBotResponseError("Bot selected a destination ticket that was not present in the offer.")
            return selected_indices

        return self._execute_bot_action(session_id, player_payload, "select_ticket_offer", choose)

    def _execute_bot_action(
        self,
        session_id: str,
        player_payload: Dict[str, Any],
        action_name: str,
        callback,
    ):
        session = self.get_session(session_id)

        try:
            session.bot.set_player(self.build_player(player_payload))
            return callback(session.bot)
        except InvalidBotResponseError as exc:
            raise BotExecutionError(session_id, session.bot_id, action_name, str(exc), error_type="invalid_response") from exc
        except Exception as exc:
            raise BotExecutionError(session_id, session.bot_id, action_name, str(exc)) from exc

    @staticmethod
    def _validate_turn_action(action: int) -> int:
        if action not in {1, 2, 3}:
            raise InvalidBotResponseError("Bot chose an invalid turn action.")
        return action

    @staticmethod
    def _validate_draw_index(draw_index: int) -> int:
        if draw_index < -1 or draw_index > 4:
            raise InvalidBotResponseError("Bot chose an invalid train-draw index.")
        return draw_index

    @staticmethod
    def _validate_color_choice(color: Any, color_options: List[str]) -> Any:
        if color is None:
            return None
        if color not in color_options:
            raise InvalidBotResponseError("Bot chose a color that was not present in the provided options.")
        return color
