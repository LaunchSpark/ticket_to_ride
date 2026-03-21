from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ticket_to_ride.backend.bootstrap_pocketbase import ensure_collections
from ticket_to_ride.backend.models import AverageScoreRecord, PlayerRecord
from ticket_to_ride.backend.repository import MatchRepository


class PocketBaseError(RuntimeError):
    """Raised when PocketBase returns an unexpected response."""


class PocketBaseMatchRepository(MatchRepository):
    RECORDS_PAGE_SIZE = 200

    def __init__(self, base_url: str, admin_email: Optional[str] = None, admin_password: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token: Optional[str] = None
        if admin_email and admin_password:
            self.admin_token = self._authenticate_admin(admin_email, admin_password)

    def create_match(self, name: str, players: List[PlayerRecord], player_names: List[str] | None = None) -> str:
        resolved_player_names = list(player_names or [player.name for player in players])
        payload = {
            "name": name,
            "player_names": resolved_player_names,
            "players": [player.model_dump() for player in players],
            "player_count": len(players),
            "status": "in_progress",
            "averageScores": [
                AverageScoreRecord(playerId=player.playerId, scores=[]).model_dump()
                for player in players
            ],
        }
        record = self._request_json("POST", "/api/collections/matches/records", payload)
        return record["id"]

    def create_round(self, match_id: str, round_number: int) -> str:
        payload = {
            "match_id": match_id,
            "round_number": self._encode_required_number(round_number),
            "turn_count": 0,
        }
        record = self._request_json("POST", "/api/collections/rounds/records", payload)
        return record["id"]

    def create_turn(self, match_id: str, round_id: str, turn_index: int, turn_state: Dict[str, Any]) -> str:
        player_state = turn_state.get("player", {})
        market_cards = turn_state.get("gameObjects", {}).get("decks", {}).get("marketCards", [])
        payload = {
            "match_id": match_id,
            "round_id": round_id,
            "turn_index": self._encode_required_number(turn_index),
            "active_player_id": player_state.get("playerId"),
            "active_player_score": player_state.get("score"),
            "active_player_remaining_trains": player_state.get("remainingTrains"),
            "active_player_claimed_routes": player_state.get("claimedRoutes", []),
            "active_player_destination_tickets": player_state.get("destinationTickets", []),
            "active_player_hand": player_state.get("hand", {}),
            "opponents": turn_state.get("opponents", []),
            "market_cards": market_cards,
            "turn_state": turn_state,
        }
        record = self._request_json("POST", "/api/collections/turns/records", payload)
        self._request_json("PATCH", f"/api/collections/rounds/records/{round_id}", {"turn_count": turn_index + 1})
        return record["id"]

    def list_matches(self) -> List[Dict[str, Any]]:
        records = self._request_all_items("/api/collections/matches/records")
        matches = [self._normalize_match(record) for record in records]
        return sorted(matches, key=lambda match: match["createdAt"], reverse=True)

    def get_match_record(self, match_id: str) -> Dict[str, Any]:
        record = self._request_json("GET", f"/api/collections/matches/records/{match_id}")
        return self._normalize_match(record)

    def get_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        filter_expr = f'match_id="{match_id}"'
        records = self._request_all_items(
            "/api/collections/rounds/records",
            query={"filter": filter_expr, "sort": "round_number"},
        )
        return [self._normalize_round(record) for record in records]

    def get_turn_records(self, round_id: str) -> List[Dict[str, Any]]:
        filter_expr = f'round_id="{round_id}"'
        records = self._request_all_items(
            "/api/collections/turns/records",
            query={"filter": filter_expr, "sort": "turn_index"},
        )
        return [self._normalize_turn(record) for record in records]

    def update_match_progress(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        payload = {
            "averageScores": [record.model_dump() for record in average_scores],
        }
        self._request_json("PATCH", f"/api/collections/matches/records/{match_id}", payload)

    def finalize_match(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        payload = {
            "status": "completed",
            "averageScores": [record.model_dump() for record in average_scores],
        }
        self._request_json("PATCH", f"/api/collections/matches/records/{match_id}", payload)

    def _authenticate_admin(self, admin_email: str, admin_password: str) -> str:
        response = self._request_json(
            "POST",
            "/api/collections/_superusers/auth-with-password",
            {"identity": admin_email, "password": admin_password},
            authenticated=False,
        )
        token = response.get("token")
        if not token:
            raise PocketBaseError("PocketBase admin authentication succeeded without returning a token.")
        return token

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        body = None
        headers = {"Content-Type": "application/json"}
        if authenticated and self.admin_token:
            headers["Authorization"] = self.admin_token
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PocketBaseError(f"PocketBase request failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise PocketBaseError(f"PocketBase request failed: {exc.reason}") from exc

        if not raw:
            return {}
        return json.loads(raw)

    def _request_all_items(self, path: str, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        combined_items: List[Dict[str, Any]] = []
        base_query = dict(query or {})
        page = 1
        total_pages = 1

        while page <= total_pages:
            paged_query = {
                **base_query,
                "page": page,
                "perPage": self.RECORDS_PAGE_SIZE,
            }
            response = self._request_json("GET", path, query=paged_query)
            page_items = response.get("items", [])
            combined_items.extend(page_items)

            response_total_pages = response.get("totalPages")
            if response_total_pages is not None:
                total_pages = int(response_total_pages)
            else:
                total_items = response.get("totalItems")
                if total_items is None:
                    total_pages = 1
                else:
                    response_per_page = int(response.get("perPage") or self.RECORDS_PAGE_SIZE)
                    total_pages = max(1, (int(total_items) + response_per_page - 1) // response_per_page)

            page += 1

        return combined_items

    @staticmethod
    def _normalize_match(record: Dict[str, Any]) -> Dict[str, Any]:
        players = record.get("players", [])
        return {
            "id": record["id"],
            "name": record.get("name") or record["id"],
            "playerNames": record.get("player_names") or [player.get("name") for player in players if player.get("name")],
            "players": players,
            "status": record.get("status", "in_progress"),
            "averageScores": record.get("averageScores", []),
            "createdAt": record.get("created") or record.get("createdAt") or "",
        }

    @staticmethod
    def _normalize_round(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "matchId": record.get("match_id"),
            "roundNumber": PocketBaseMatchRepository._decode_required_number(record.get("round_number")),
        }

    @staticmethod
    def _normalize_turn(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "matchId": record.get("match_id"),
            "roundId": record.get("round_id"),
            "turnIndex": PocketBaseMatchRepository._decode_required_number(record.get("turn_index")),
            "turnState": record.get("turn_state", {}),
        }

    @staticmethod
    def _encode_required_number(value: int) -> int:
        return value + 1

    @staticmethod
    def _decode_required_number(value: Any) -> int:
        if value is None:
            return 0
        return int(value) - 1


def build_repository_from_env() -> MatchRepository:
    backend = os.getenv("MATCH_LOG_STORAGE_BACKEND", "pocketbase").lower()
    if backend == "memory":
        from ticket_to_ride.backend.repository import InMemoryMatchRepository

        return InMemoryMatchRepository()

    base_url = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")
    admin_email = os.getenv("POCKETBASE_ADMIN_EMAIL")
    admin_password = os.getenv("POCKETBASE_ADMIN_PASSWORD")
    if admin_email and admin_password:
        ensure_collections(base_url, admin_email, admin_password)
    return PocketBaseMatchRepository(base_url, admin_email=admin_email, admin_password=admin_password)
