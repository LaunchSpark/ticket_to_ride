from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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

    def upsert_bot(
        self,
        *,
        schema_version: int,
        bot_id: str,
        name: str,
        version: str,
        description: str,
        author: str,
        tags: List[str],
        source_kind: str,
        source_base_url: str,
        discovery_path: str,
    ) -> Dict[str, Any]:
        existing_record = next((bot for bot in self.list_bots() if bot["botId"] == bot_id), None)
        payload = {
            "schema_version": schema_version,
            "bot_id": bot_id,
            "name": name,
            "version": version,
            "description": description,
            "author": author,
            "tags": list(tags),
            "source_kind": source_kind,
            "source_base_url": source_base_url,
            "discovery_path": discovery_path,
        }

        if existing_record is None:
            record = self._request_json("POST", "/api/collections/bots/records", payload)
        else:
            record = self._request_json("PATCH", f"/api/collections/bots/records/{existing_record['id']}", payload)

        return self._normalize_bot(record)

    def list_bots(self) -> List[Dict[str, Any]]:
        records = self._request_all_items("/api/collections/bots/records")
        bots = [self._normalize_bot(record) for record in records]
        return sorted(bots, key=lambda bot: (bot["name"].casefold(), bot["botId"].casefold()))

    def get_bot(self, bot_id: str) -> Dict[str, Any]:
        filter_expr = f'bot_id="{bot_id}"'
        records = self._request_all_items(
            "/api/collections/bots/records",
            query={"filter": filter_expr},
        )
        if not records:
            raise KeyError(f"Unknown bot '{bot_id}'")
        return self._normalize_bot(records[0])

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

    def create_managed_match(
        self,
        *,
        name: str,
        seats: List[Dict[str, Any]],
        fallback_bot_id: str,
        round_count: int,
        time_control: Dict[str, Any],
        timeout_policy: str,
        execution_mode: str,
    ) -> str:
        payload = {
            "name": name,
            "status": "queued",
            "seats": seats,
            "fallback_bot_id": fallback_bot_id,
            "round_count": round_count,
            "time_control": time_control,
            "timeout_policy": timeout_policy,
            "execution_mode": execution_mode,
            "aggregate_results": [
                {
                    "seatId": seat["seatId"],
                    "primaryBotId": seat["primaryBotId"],
                    "roundsWon": 0,
                    "roundsLost": 0,
                    "runtimeFailures": 0,
                }
                for seat in seats
            ],
        }
        record = self._request_json("POST", "/api/collections/managed_matches/records", payload)
        return record["id"]

    def list_managed_match_records(self) -> List[Dict[str, Any]]:
        records = self._request_all_items("/api/collections/managed_matches/records")
        managed_matches = [self._normalize_managed_match(record) for record in records]
        return sorted(managed_matches, key=lambda match: match["createdAt"], reverse=True)

    def get_managed_match_record(self, match_id: str) -> Dict[str, Any]:
        record = self._request_json("GET", f"/api/collections/managed_matches/records/{match_id}")
        return self._normalize_managed_match(record)

    def update_managed_match(self, match_id: str, **fields: Any) -> Dict[str, Any]:
        payload = {}
        for key, value in fields.items():
            if key == "currentRoundNumber" and value is not None:
                payload["current_round_number"] = self._encode_required_number(int(value))
            elif key == "currentRoundNumber":
                payload["current_round_number"] = None
            elif key == "roundCount":
                payload["round_count"] = int(value)
            elif key == "fallbackBotId":
                payload["fallback_bot_id"] = value
            elif key == "timeControl":
                payload["time_control"] = value
            elif key == "timeoutPolicy":
                payload["timeout_policy"] = value
            elif key == "executionMode":
                payload["execution_mode"] = value
            elif key == "replayMatchId":
                payload["replay_match_id"] = value
            elif key == "aggregateResults":
                payload["aggregate_results"] = value
            elif key == "seats":
                payload["seats"] = value
            else:
                payload[self._camel_to_snake(key)] = value
        record = self._request_json("PATCH", f"/api/collections/managed_matches/records/{match_id}", payload)
        return self._normalize_managed_match(record)

    def create_managed_round(self, match_id: str, round_number: int, status: str = "queued") -> str:
        payload = {
            "managed_match_id": match_id,
            "round_number": self._encode_required_number(round_number),
            "status": status,
            "seat_results": [],
            "clock_state": [],
            "runtime_state": [],
        }
        record = self._request_json("POST", "/api/collections/managed_rounds/records", payload)
        return record["id"]

    def list_managed_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        filter_expr = f'managed_match_id="{match_id}"'
        records = self._request_all_items(
            "/api/collections/managed_rounds/records",
            query={"filter": filter_expr, "sort": "round_number"},
        )
        return [self._normalize_managed_round(record) for record in records]

    def get_managed_round_record(self, match_id: str, round_number: int) -> Dict[str, Any]:
        filter_expr = f'(managed_match_id="{match_id}")&&(round_number={self._encode_required_number(round_number)})'
        records = self._request_all_items(
            "/api/collections/managed_rounds/records",
            query={"filter": filter_expr, "sort": "round_number"},
        )
        if not records:
            raise KeyError(f"Unknown managed round '{round_number}' for match '{match_id}'")
        return self._normalize_managed_round(records[0])

    def update_managed_round(self, round_id: str, **fields: Any) -> Dict[str, Any]:
        payload = {}
        for key, value in fields.items():
            if key == "roundNumber":
                payload["round_number"] = self._encode_required_number(int(value))
            elif key == "replayRoundId":
                payload["replay_round_id"] = value
            elif key == "seatResults":
                payload["seat_results"] = value
            elif key == "clockState":
                payload["clock_state"] = value
            elif key == "runtimeState":
                payload["runtime_state"] = value
            else:
                payload[self._camel_to_snake(key)] = value
        record = self._request_json("PATCH", f"/api/collections/managed_rounds/records/{round_id}", payload)
        return self._normalize_managed_round(record)

    def interrupt_incomplete_managed_matches(self) -> None:
        for record in self._request_all_items("/api/collections/managed_matches/records"):
            normalized = self._normalize_managed_match(record)
            if normalized["status"] not in {"completed", "failed", "aborted", "interrupted"}:
                self._request_json(
                    "PATCH",
                    f"/api/collections/managed_matches/records/{normalized['id']}",
                    {"status": "interrupted"},
                )
        for record in self._request_all_items("/api/collections/managed_rounds/records"):
            normalized = self._normalize_managed_round(record)
            if normalized["status"] not in {"completed", "failed", "aborted", "interrupted"}:
                self._request_json(
                    "PATCH",
                    f"/api/collections/managed_rounds/records/{normalized['id']}",
                    {"status": "interrupted"},
                )

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
    def _normalize_bot(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "schemaVersion": int(record.get("schema_version") or 1),
            "botId": record.get("bot_id") or record["id"],
            "name": record.get("name") or record.get("bot_id") or record["id"],
            "version": record.get("version") or "",
            "description": record.get("description") or "",
            "author": record.get("author") or "",
            "tags": list(record.get("tags") or []),
            "sourceKind": record.get("source_kind") or "local_api",
            "sourceBaseUrl": (record.get("source_base_url") or "").rstrip("/"),
            "discoveryPath": record.get("discovery_path") or "/bots",
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
    def _normalize_managed_match(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "name": record.get("name") or record["id"],
            "status": record.get("status", "queued"),
            "seats": list(record.get("seats") or []),
            "fallbackBotId": record.get("fallback_bot_id") or "random_bot",
            "roundCount": int(record.get("round_count") or 0),
            "timeControl": dict(record.get("time_control") or {}),
            "timeoutPolicy": record.get("timeout_policy") or "loss_on_time",
            "executionMode": record.get("execution_mode") or "bot_api",
            "replayMatchId": record.get("replay_match_id"),
            "currentRoundNumber": (
                None
                if record.get("current_round_number") is None
                else PocketBaseMatchRepository._decode_required_number(record.get("current_round_number"))
            ),
            "aggregateResults": list(record.get("aggregate_results") or []),
            "createdAt": record.get("created") or record.get("createdAt") or "",
        }

    @staticmethod
    def _normalize_managed_round(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": record["id"],
            "matchId": record.get("managed_match_id"),
            "roundNumber": PocketBaseMatchRepository._decode_required_number(record.get("round_number")),
            "status": record.get("status", "queued"),
            "replayRoundId": record.get("replay_round_id"),
            "seatResults": list(record.get("seat_results") or []),
            "clockState": list(record.get("clock_state") or []),
            "runtimeState": list(record.get("runtime_state") or []),
            "createdAt": record.get("created") or record.get("createdAt") or "",
        }

    @staticmethod
    def _encode_required_number(value: int) -> int:
        return value + 1

    @staticmethod
    def _decode_required_number(value: Any) -> int:
        if value is None:
            return 0
        return int(value) - 1

    @staticmethod
    def _camel_to_snake(value: str) -> str:
        result = []
        for character in value:
            if character.isupper():
                result.append("_")
                result.append(character.lower())
            else:
                result.append(character)
        return "".join(result).lstrip("_")


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
