from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ticket_to_ride.engine.state.views import PlayerView
from ticket_to_ride.engine.player import Player


class LoggerClientError(RuntimeError):
    """Raised when the logger API cannot be reached or returns an error."""


class JsonHttpTransport:
    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LoggerClientError(f"Logger API request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise LoggerClientError(f"Logger API request failed: {exc.reason}") from exc

        if not raw:
            return {}
        return json.loads(raw)


class GameLogSerializer:
    @staticmethod
    def serialize_claimed_routes(routes: List[Any]) -> List[Dict[str, str]]:
        serialized_routes: List[Dict[str, str]] = []
        for route in routes:
            route_id = getattr(route, "route_id", str(route))
            route_label = getattr(route, "route_label", str(route))
            serialized_routes.append(
                {
                    "routeId": route_id,
                    "routeLabel": route_label,
                }
            )
        return serialized_routes

    def serialize_players(self, players: List[Player]) -> List[Dict[str, Any]]:
        return [
            {
                "playerId": player.player_id,
                "name": player.name,
                "color": player.color,
            }
            for player in players
        ]

    @staticmethod
    def _routes_claimed_by(view: PlayerView, player_id: str) -> List[Any]:
        return [route for route in view.routes if view.claimed_by.get(route.route_id) == player_id]

    def serialize_turn_state(self, player_list: List[Player], context: PlayerView) -> Dict[str, Any]:
        player = next((candidate for candidate in player_list if candidate.player_id == context.player_id), None)
        if player is None:
            raise ValueError(f"Player '{context.player_id}' was not found in the active player list.")

        player_data = {
            "playerId": context.player_id,
            "score": context.score,
            "remainingTrains": player.trains_remaining,
            "claimedRoutes": self.serialize_claimed_routes(self._routes_claimed_by(context, player.player_id)),
            "destinationTickets": [
                {
                    "from": ticket.city1,
                    "to": ticket.city2,
                    "points": ticket.value,
                    "completed": ticket.is_completed,
                }
                for ticket in player.get_tickets()
            ],
            "hand": self._serialize_hand(player.get_hand()),
        }

        opponents_data = [
            {
                "playerId": opponent.player_id,
                "score": opponent.score,
                "remainingTrains": opponent.remaining_trains,
                "claimedRoutes": self.serialize_claimed_routes(self._routes_claimed_by(context, opponent.player_id)),
                "destinationTicketCount": opponent.destination_ticket_count,
                "hand": {
                    "public": self._serialize_hand(opponent.exposed_hand),
                    "hidden": opponent.num_cards_in_hand - opponent.exposed_hand.total(),  # type: ignore[arg-type]
                },
            }
            for opponent in context.opponents
        ]

        return {
            "player": player_data,
            "opponents": opponents_data,
            "gameObjects": {
                "decks": {
                    "marketCards": list(context.face_up_cards),
                }
            },
        }

    @staticmethod
    def _serialize_hand(hand: Dict[str, int]) -> Dict[str, int]:
        return {
            "black": hand.get("B", 0),
            "blue": hand.get("U", 0),
            "green": hand.get("G", 0),
            "locomotive": hand.get("L", 0),
            "orange": hand.get("O", 0),
            "purple": hand.get("P", 0),
            "red": hand.get("R", 0),
            "white": hand.get("W", 0),
            "yellow": hand.get("Y", 0),
        }


class GameLogger:
    def __init__(
        self,
        players: List[Player],
        api_base_url: Optional[str] = None,
        transport: Optional[JsonHttpTransport] = None,
        serializer: Optional[GameLogSerializer] = None,
    ) -> None:
        self.player_list = players
        self.serializer = serializer or GameLogSerializer()
        resolved_api_base_url = api_base_url or os.getenv("LOGGER_API_BASE_URL", "http://127.0.0.1:8000")
        self.transport = transport or JsonHttpTransport(resolved_api_base_url)
        self.match_id: Optional[str] = None
        self.round_ids: Dict[int, str] = {}
        self.turn_counts: Dict[int, int] = {}

    def set_player_list(self, players: List[Player]) -> None:
        self.player_list = players

    def start_match(self, match_name: Optional[str] = None) -> str:
        payload = {
            "name": match_name or "-".join(player.name for player in self.player_list),
            "playerNames": [player.name for player in self.player_list],
            "players": self.serializer.serialize_players(self.player_list),
        }
        response = self.transport.request("POST", "/matches", payload)
        self.match_id = response["matchId"]
        self.round_ids.clear()
        self.turn_counts.clear()
        return self.match_id

    def start_round(self, round_number: int) -> str:
        match_id = self._require_match_id()
        response = self.transport.request(
            "POST",
            f"/matches/{match_id}/rounds",
            {"roundNumber": round_number},
        )
        round_id = response["roundId"]
        self.round_ids[round_number] = round_id
        self.turn_counts[round_number] = 0
        return round_id

    def record_turn(self, round_number: int, context: PlayerView) -> str:
        match_id = self._require_match_id()
        round_id = self.round_ids.get(round_number)
        if round_id is None:
            raise ValueError(f"Round {round_number} has not been started.")

        turn_index = self.turn_counts.get(round_number, 0)
        turn_state = self.serializer.serialize_turn_state(self.player_list, context)
        response = self.transport.request(
            "POST",
            f"/matches/{match_id}/rounds/{round_id}/turns",
            {"turnIndex": turn_index, "turnState": turn_state},
        )
        self.turn_counts[round_number] = turn_index + 1
        return response["turnId"]

    def finalize_match(self) -> Dict[str, Any]:
        match_id = self._require_match_id()
        return self.transport.request("POST", f"/matches/{match_id}/finalize", {})

    def fetch_match(self, match_id: Optional[str] = None) -> Dict[str, Any]:
        target_match_id = match_id or self._require_match_id()
        return self.transport.request("GET", f"/matches/{target_match_id}")

    def list_matches(self) -> List[Dict[str, Any]]:
        response = self.transport.request("GET", "/matches")
        return response if isinstance(response, list) else []

    def add_round(self) -> str:
        return self.start_round(len(self.round_ids))

    def add_turn(self, round_number: int, context: PlayerView) -> str:
        return self.record_turn(round_number, context)

    def log_match_stats(self) -> Dict[str, Any]:
        return self.finalize_match()

    def export_log(self, file_name: str) -> Dict[str, Any]:
        return self.fetch_match()

    def _require_match_id(self) -> str:
        if self.match_id is None:
            raise ValueError("Match has not been started.")
        return self.match_id
