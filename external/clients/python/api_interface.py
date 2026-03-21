from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from external.contracts.abstract_interface import Interface
from external.clients.bot_api.views import route_payload, ticket_payload
from ticket_to_ride.engine.state.map import Route
from ticket_to_ride.engine.state.decks import DestinationTicket


class BotApiError(RuntimeError):
    """Raised when the bot API fails."""


class BotApiTransport:
    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BotApiError(f"Bot API request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise BotApiError(f"Bot API request failed: {exc.reason}") from exc

        if not raw:
            return {}
        return json.loads(raw)


class ApiBotInterface(Interface):
    def __init__(
        self,
        bot_name: str,
        api_base_url: Optional[str] = None,
        transport: Optional[BotApiTransport] = None,
    ) -> None:
        super().__init__()
        self.bot_name = bot_name
        resolved_api_base_url = api_base_url or os.getenv("BOT_API_BASE_URL", "http://127.0.0.1:8001")
        self.transport = transport or BotApiTransport(resolved_api_base_url)
        self.session_id: Optional[str] = None

    def set_player(self, player) -> None:
        super().set_player(player)
        if self.session_id is None:
            response = self.transport.request("POST", "/bot-sessions", {"botName": self.bot_name})
            self.session_id = response["sessionId"]

    def choose_turn_action(self):
        response = self.transport.request(
            "POST",
            f"/bot-sessions/{self._require_session_id()}/choose-turn-action",
            {"playerState": self._serialize_player_state()},
        )
        return response["action"]

    def choose_draw_train_action(self) -> int:
        response = self.transport.request(
            "POST",
            f"/bot-sessions/{self._require_session_id()}/choose-draw-train-action",
            {"playerState": self._serialize_player_state()},
        )
        return response["drawIndex"]

    def choose_route_to_claim(self, claimable_routes: 'List[tuple[Route,int]]') -> 'tuple[Route,int]':
        response = self.transport.request(
            "POST",
            f"/bot-sessions/{self._require_session_id()}/choose-route-to-claim",
            {
                "playerState": self._serialize_player_state(),
                "claimableRoutes": [
                    {"route": route_payload(route), "locomotives": locomotives}
                    for route, locomotives in claimable_routes
                ],
            },
        )
        selected_index = response["selectedIndex"]
        return claimable_routes[selected_index][0], response["locomotives"]

    def choose_color_to_spend(self, route: Route, color_options: List[str]) -> "str | None":
        response = self.transport.request(
            "POST",
            f"/bot-sessions/{self._require_session_id()}/choose-color-to-spend",
            {
                "playerState": self._serialize_player_state(),
                "route": route_payload(route),
                "colorOptions": color_options,
            },
        )
        return response.get("color")

    def select_ticket_offer(self, offer) -> List[DestinationTicket]:
        response = self.transport.request(
            "POST",
            f"/bot-sessions/{self._require_session_id()}/select-ticket-offer",
            {
                "playerState": self._serialize_player_state(),
                "offer": [ticket_payload(ticket) for ticket in offer],
            },
        )
        return [offer[index] for index in response["selectedIndices"]]

    def _serialize_player_state(self) -> Dict[str, Any]:
        context = self.player.context
        return {
            "playerId": self.player.player_id,
            "name": self.player.name,
            "color": self.player.color,
            "trainsRemaining": self.player.trains_remaining,
            "hand": dict(self.player.get_hand()),
            "exposedHand": dict(self.player.get_exposed()),
            "tickets": [ticket_payload(ticket) for ticket in self.player.get_tickets()],
            "context": {
                "faceUpCards": list(context.face_up_cards),
                "turnNumber": context.turn_number,
                "score": context.score,
                "trainDeckCount": len(context.train_deck),
                "ticketDeckCount": len(context.ticket_deck),
                "opponents": [
                    {
                        "playerId": opponent.player_id,
                        "exposedHand": dict(opponent.exposed_hand),
                        "numCardsInHand": opponent.num_cards_in_hand,
                        "remainingTrains": opponent.remaining_trains,
                        "score": opponent.score,
                        "destinationTicketCount": opponent.destination_ticket_count,
                    }
                    for opponent in context.opponents
                ],
                "map": {
                    "routes": [route_payload(route) for route in context.map.routes],
                },
            },
        }

    def _require_session_id(self) -> str:
        if self.session_id is None:
            raise ValueError("Bot session has not been created.")
        return self.session_id
