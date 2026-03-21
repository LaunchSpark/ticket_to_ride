from __future__ import annotations

"""
Own controller execution transport for managed runtime controllers.

This module is responsible for:
- the executor interface used by round orchestration
- HTTP calls to the external bot API
- request/response normalization into ExecutionResult
- external bot-session creation and teardown

This module does not own:
- round failover policy
- clock accounting
- match persistence
"""

import json
import os
import socket
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from external.clients.bot_api.views import route_payload, ticket_payload
from ticket_to_ride.backend.runtime.models import ExecutionResult
from ticket_to_ride.engine.player import Player

DEFAULT_BOT_API_BASE_URL = "http://127.0.0.1:8001"


class BotExecutor:
    """Abstract executor for one seat controller runtime."""

    def start(self) -> None:
        """Create any underlying controller/session resources."""

        raise NotImplementedError

    def invoke(
        self,
        action_name: str,
        *,
        player: Player,
        timeout_ms: Optional[int],
        remaining_time_ms: int,
        initial_time_ms: int,
        increment_ms: int,
        args: tuple[Any, ...],
    ) -> ExecutionResult:
        """Invoke one engine-facing bot decision method."""

        raise NotImplementedError

    def close(self) -> ExecutionResult:
        """Tear down any controller/session resources for this executor."""

        raise NotImplementedError


class BotApiExecutor(BotExecutor):
    """HTTP executor that talks to the external bot API session endpoints."""

    def __init__(self, bot_id: str, base_url: str | None = None) -> None:
        self.bot_id = bot_id
        self.base_url = (base_url or os.getenv("BOT_API_BASE_URL", DEFAULT_BOT_API_BASE_URL)).rstrip("/")
        self.session_id: Optional[str] = None

    def start(self) -> None:
        response = self._request("POST", "/bot-sessions", {"botId": self.bot_id}, timeout_ms=None)
        self.session_id = response["sessionId"]

    def invoke(
        self,
        action_name: str,
        *,
        player: Player,
        timeout_ms: Optional[int],
        remaining_time_ms: int,
        initial_time_ms: int,
        increment_ms: int,
        args: tuple[Any, ...],
    ) -> ExecutionResult:
        if self.session_id is None:
            return ExecutionResult(status="transport_error", elapsed_ms=0, detail="Controller session has not been started.")

        payload = self._build_payload(
            action_name,
            player=player,
            remaining_time_ms=remaining_time_ms,
            initial_time_ms=initial_time_ms,
            increment_ms=increment_ms,
            args=args,
        )
        path = self._action_path(action_name, self.session_id)
        started_at = time.monotonic()
        try:
            response = self._request("POST", path, payload, timeout_ms=timeout_ms)
            elapsed_ms = _elapsed_ms_since(started_at)
        except socket.timeout:
            return ExecutionResult(status="per_call_timeout", elapsed_ms=_elapsed_ms_since(started_at), detail="Bot API request timed out.")
        except TimeoutError:
            return ExecutionResult(status="per_call_timeout", elapsed_ms=_elapsed_ms_since(started_at), detail="Bot API request timed out.")
        except HTTPError as exc:
            elapsed_ms = _elapsed_ms_since(started_at)
            parsed = _read_json_error(exc)
            error_type = parsed.get("errorType")
            if error_type == "invalid_response":
                return ExecutionResult(status="invalid_response", elapsed_ms=elapsed_ms, detail=parsed.get("detail", "Invalid bot response."))
            if error_type == "bot_exception":
                return ExecutionResult(status="bot_exception", elapsed_ms=elapsed_ms, detail=parsed.get("detail", "Bot execution failed."))
            return ExecutionResult(status="transport_error", elapsed_ms=elapsed_ms, detail=parsed.get("detail", "Bot API request failed."))
        except URLError as exc:
            elapsed_ms = _elapsed_ms_since(started_at)
            if isinstance(exc.reason, socket.timeout) or "timed out" in str(exc.reason).lower():
                return ExecutionResult(status="per_call_timeout", elapsed_ms=elapsed_ms, detail="Bot API request timed out.")
            return ExecutionResult(status="transport_error", elapsed_ms=elapsed_ms, detail=f"Bot API request failed: {exc.reason}")

        try:
            normalized_payload = self._parse_response(action_name, response, args)
        except ValueError as exc:
            return ExecutionResult(status="invalid_response", elapsed_ms=elapsed_ms, detail=str(exc))
        return ExecutionResult(status="ok", elapsed_ms=elapsed_ms, payload=normalized_payload)

    def close(self) -> ExecutionResult:
        if self.session_id is None:
            return ExecutionResult(status="ok", elapsed_ms=0)

        started_at = time.monotonic()
        try:
            self._request("DELETE", f"/bot-sessions/{self.session_id}", None, timeout_ms=None)
        except Exception as exc:
            return ExecutionResult(
                status="controller_teardown_failed",
                elapsed_ms=_elapsed_ms_since(started_at),
                detail=str(exc),
            )
        finally:
            self.session_id = None
        return ExecutionResult(status="ok", elapsed_ms=_elapsed_ms_since(started_at))

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]],
        *,
        timeout_ms: Optional[int],
    ) -> Dict[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        timeout_seconds = None if timeout_ms is None else max(timeout_ms / 1000.0, 0.001)
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def _build_payload(
        self,
        action_name: str,
        *,
        player: Player,
        remaining_time_ms: int,
        initial_time_ms: int,
        increment_ms: int,
        args: tuple[Any, ...],
    ) -> Dict[str, Any]:
        payload = {
            "playerState": _serialize_player_state(
                player,
                remaining_time_ms=remaining_time_ms,
                initial_time_ms=initial_time_ms,
                increment_ms=increment_ms,
            )
        }
        if action_name == "choose_route_to_claim":
            claimable_routes = args[0]
            payload["claimableRoutes"] = [
                {"route": route_payload(route), "locomotives": locomotives}
                for route, locomotives in claimable_routes
            ]
        elif action_name == "choose_color_to_spend":
            route, color_options = args
            payload["route"] = route_payload(route)
            payload["colorOptions"] = list(color_options)
        elif action_name == "select_ticket_offer":
            offer = args[0]
            payload["offer"] = [ticket_payload(ticket) for ticket in offer]
        return payload

    @staticmethod
    def _action_path(action_name: str, session_id: str) -> str:
        action_paths = {
            "choose_turn_action": "choose-turn-action",
            "choose_draw_train_action": "choose-draw-train-action",
            "choose_route_to_claim": "choose-route-to-claim",
            "choose_color_to_spend": "choose-color-to-spend",
            "select_ticket_offer": "select-ticket-offer",
        }
        return f"/bot-sessions/{session_id}/{action_paths[action_name]}"

    @staticmethod
    def _parse_response(action_name: str, response: Dict[str, Any], args: tuple[Any, ...]) -> Any:
        if action_name == "choose_turn_action":
            action = int(response["action"])
            if action not in {1, 2, 3}:
                raise ValueError("Bot API returned an invalid turn action.")
            return action
        if action_name == "choose_draw_train_action":
            draw_index = int(response["drawIndex"])
            if draw_index < -1 or draw_index > 4:
                raise ValueError("Bot API returned an invalid train-draw index.")
            return draw_index
        if action_name == "choose_route_to_claim":
            claimable_routes = args[0]
            selected_index = int(response["selectedIndex"])
            if selected_index < 0 or selected_index >= len(claimable_routes):
                raise ValueError("Bot API returned an invalid route selection index.")
            locomotives = int(response["locomotives"])
            route = claimable_routes[selected_index][0]
            return route, locomotives
        if action_name == "choose_color_to_spend":
            color = response.get("color")
            if color is not None and color not in args[1]:
                raise ValueError("Bot API returned an invalid color selection.")
            return color
        if action_name == "select_ticket_offer":
            offer = args[0]
            selected_indices = [int(index) for index in response.get("selectedIndices", [])]
            if not selected_indices:
                raise ValueError("Bot API returned an empty ticket selection.")
            if any(index < 0 or index >= len(offer) for index in selected_indices):
                raise ValueError("Bot API returned an invalid ticket index.")
            return [offer[index] for index in selected_indices]
        raise ValueError(f"Unsupported bot action '{action_name}'.")


def _serialize_player_state(
    player: Player,
    *,
    remaining_time_ms: int,
    initial_time_ms: int,
    increment_ms: int,
) -> Dict[str, Any]:
    context = player.context
    return {
        "playerId": player.player_id,
        "name": player.name,
        "color": player.color,
        "trainsRemaining": player.trains_remaining,
        "hand": dict(player.get_hand()),
        "exposedHand": dict(player.get_exposed()),
        "tickets": [ticket_payload(ticket) for ticket in player.get_tickets()],
        "context": {
            "faceUpCards": list(context.face_up_cards),
            "turnNumber": context.turn_number,
            "score": context.score,
            "trainDeckCount": len(context.train_deck),
            "ticketDeckCount": len(context.ticket_deck),
            "remainingTimeMs": remaining_time_ms,
            "initialTimeMs": initial_time_ms,
            "incrementMs": increment_ms,
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


def _read_json_error(exc: HTTPError) -> Dict[str, Any]:
    raw = exc.read().decode("utf-8", errors="replace")
    if not raw:
        return {"detail": str(exc)}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"detail": raw}


def _elapsed_ms_since(started_at: float) -> int:
    return max(1, int(round((time.monotonic() - started_at) * 1000)))
