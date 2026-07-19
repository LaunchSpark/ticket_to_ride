from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Dict, List
from uuid import uuid4

from ticket_to_ride.backend.models import AverageScoreRecord, PlayerRecord, utc_now_iso


class MatchRepository(ABC):
    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def list_bots(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_bot(self, bot_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_bot_connection(self, url: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_bot_connections(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def delete_bot_connection(self, connection_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_match(
        self,
        name: str,
        players: List[PlayerRecord],
        player_names: List[str] | None = None,
        map_name: str | None = None,
        seed: int | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def create_round(self, match_id: str, round_number: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def create_turn(self, match_id: str, round_id: str, turn_index: int, turn_state: Dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_matches(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_match_record(self, match_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_turn_records(self, round_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def update_match_progress(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def finalize_match(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def list_managed_match_records(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_managed_match_record(self, match_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_managed_match(self, match_id: str, **fields: Any) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_managed_round(self, match_id: str, round_number: int, status: str = "queued") -> str:
        raise NotImplementedError

    @abstractmethod
    def list_managed_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_managed_round_record(self, match_id: str, round_number: int) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_managed_round(self, round_id: str, **fields: Any) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def interrupt_incomplete_managed_matches(self) -> None:
        raise NotImplementedError


class InMemoryMatchRepository(MatchRepository):
    def __init__(self) -> None:
        self.bots: Dict[str, Dict[str, Any]] = {}
        self.matches: Dict[str, Dict[str, Any]] = {}
        self.rounds: Dict[str, Dict[str, Any]] = {}
        self.turns: Dict[str, Dict[str, Any]] = {}
        self.managed_matches: Dict[str, Dict[str, Any]] = {}
        self.managed_rounds: Dict[str, Dict[str, Any]] = {}
        self.bot_connections: Dict[str, Dict[str, Any]] = {}

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
        existing_record = next(
            (record for record in self.bots.values() if record["botId"] == bot_id),
            None,
        )
        if existing_record is None:
            record_id = str(uuid4())
            record = {
                "id": record_id,
                "schemaVersion": schema_version,
                "botId": bot_id,
                "name": name,
                "version": version,
                "description": description,
                "author": author,
                "tags": list(tags),
                "sourceKind": source_kind,
                "sourceBaseUrl": source_base_url,
                "discoveryPath": discovery_path,
                "createdAt": utc_now_iso(),
            }
            self.bots[record_id] = record
            return deepcopy(record)

        existing_record["schemaVersion"] = schema_version
        existing_record["name"] = name
        existing_record["version"] = version
        existing_record["description"] = description
        existing_record["author"] = author
        existing_record["tags"] = list(tags)
        existing_record["sourceKind"] = source_kind
        existing_record["sourceBaseUrl"] = source_base_url
        existing_record["discoveryPath"] = discovery_path
        return deepcopy(existing_record)

    def list_bots(self) -> List[Dict[str, Any]]:
        return sorted(
            (deepcopy(bot) for bot in self.bots.values()),
            key=lambda bot: (bot["name"].casefold(), bot["botId"].casefold()),
        )

    def get_bot(self, bot_id: str) -> Dict[str, Any]:
        for record in self.bots.values():
            if record["botId"] == bot_id:
                return deepcopy(record)
        raise KeyError(f"Unknown bot '{bot_id}'")

    def create_bot_connection(self, url: str) -> Dict[str, Any]:
        record = {"id": str(uuid4()), "url": url, "createdAt": utc_now_iso()}
        self.bot_connections[record["id"]] = record
        return deepcopy(record)

    def list_bot_connections(self) -> List[Dict[str, Any]]:
        return sorted(
            (deepcopy(record) for record in self.bot_connections.values()),
            key=lambda record: record["createdAt"],
        )

    def delete_bot_connection(self, connection_id: str) -> None:
        if connection_id not in self.bot_connections:
            raise KeyError(f"Unknown bot connection '{connection_id}'")
        del self.bot_connections[connection_id]

    def create_match(
        self,
        name: str,
        players: List[PlayerRecord],
        player_names: List[str] | None = None,
        map_name: str | None = None,
        seed: int | None = None,
    ) -> str:
        match_id = str(uuid4())
        resolved_player_names = list(player_names or [player.name for player in players])
        self.matches[match_id] = {
            "id": match_id,
            "name": name,
            "playerNames": resolved_player_names,
            "mapName": map_name,
            "seed": seed,
            "players": [player.model_dump() for player in players],
            "status": "in_progress",
            "averageScores": [
                AverageScoreRecord(playerId=player.playerId, scores=[]).model_dump()
                for player in players
            ],
            "createdAt": utc_now_iso(),
        }
        return match_id

    def create_round(self, match_id: str, round_number: int) -> str:
        self._require_match(match_id)
        round_id = str(uuid4())
        self.rounds[round_id] = {
            "id": round_id,
            "matchId": match_id,
            "roundNumber": round_number,
        }
        return round_id

    def create_turn(self, match_id: str, round_id: str, turn_index: int, turn_state: Dict[str, Any]) -> str:
        self._require_match(match_id)
        if round_id not in self.rounds:
            raise KeyError(f"Unknown round '{round_id}'")
        turn_id = str(uuid4())
        self.turns[turn_id] = {
            "id": turn_id,
            "matchId": match_id,
            "roundId": round_id,
            "turnIndex": turn_index,
            "turnState": deepcopy(turn_state),
        }
        return turn_id

    def list_matches(self) -> List[Dict[str, Any]]:
        return sorted(
            (deepcopy(match) for match in self.matches.values()),
            key=lambda match: match["createdAt"],
            reverse=True,
        )

    def get_match_record(self, match_id: str) -> Dict[str, Any]:
        self._require_match(match_id)
        return deepcopy(self.matches[match_id])

    def get_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        self._require_match(match_id)
        rounds = [deepcopy(round_record) for round_record in self.rounds.values() if round_record["matchId"] == match_id]
        return sorted(rounds, key=lambda round_record: round_record["roundNumber"])

    def get_turn_records(self, round_id: str) -> List[Dict[str, Any]]:
        turns = [deepcopy(turn) for turn in self.turns.values() if turn["roundId"] == round_id]
        return sorted(turns, key=lambda turn: turn["turnIndex"])

    def update_match_progress(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        self._require_match(match_id)
        self.matches[match_id]["averageScores"] = [record.model_dump() for record in average_scores]

    def finalize_match(self, match_id: str, average_scores: List[AverageScoreRecord]) -> None:
        self._require_match(match_id)
        self.matches[match_id]["status"] = "completed"
        self.matches[match_id]["averageScores"] = [record.model_dump() for record in average_scores]

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
        match_id = str(uuid4())
        self.managed_matches[match_id] = {
            "id": match_id,
            "name": name,
            "status": "queued",
            "seats": deepcopy(seats),
            "fallbackBotId": fallback_bot_id,
            "roundCount": round_count,
            "timeControl": deepcopy(time_control),
            "timeoutPolicy": timeout_policy,
            "executionMode": execution_mode,
            "replayMatchId": None,
            "currentRoundNumber": None,
            "aggregateResults": [
                {
                    "seatId": seat["seatId"],
                    "primaryBotId": seat["primaryBotId"],
                    "roundsWon": 0,
                    "roundsLost": 0,
                    "runtimeFailures": 0,
                }
                for seat in seats
            ],
            "createdAt": utc_now_iso(),
        }
        return match_id

    def list_managed_match_records(self) -> List[Dict[str, Any]]:
        return sorted(
            (deepcopy(match) for match in self.managed_matches.values()),
            key=lambda match: match["createdAt"],
            reverse=True,
        )

    def get_managed_match_record(self, match_id: str) -> Dict[str, Any]:
        self._require_managed_match(match_id)
        return deepcopy(self.managed_matches[match_id])

    def update_managed_match(self, match_id: str, **fields: Any) -> Dict[str, Any]:
        self._require_managed_match(match_id)
        for key, value in fields.items():
            self.managed_matches[match_id][key] = deepcopy(value)
        return deepcopy(self.managed_matches[match_id])

    def create_managed_round(self, match_id: str, round_number: int, status: str = "queued") -> str:
        self._require_managed_match(match_id)
        round_id = str(uuid4())
        self.managed_rounds[round_id] = {
            "id": round_id,
            "matchId": match_id,
            "roundNumber": round_number,
            "status": status,
            "replayRoundId": None,
            "seatResults": [],
            "clockState": [],
            "runtimeState": [],
            "createdAt": utc_now_iso(),
        }
        return round_id

    def list_managed_round_records(self, match_id: str) -> List[Dict[str, Any]]:
        self._require_managed_match(match_id)
        rounds = [
            deepcopy(round_record)
            for round_record in self.managed_rounds.values()
            if round_record["matchId"] == match_id
        ]
        return sorted(rounds, key=lambda round_record: round_record["roundNumber"])

    def get_managed_round_record(self, match_id: str, round_number: int) -> Dict[str, Any]:
        self._require_managed_match(match_id)
        for round_record in self.managed_rounds.values():
            if round_record["matchId"] == match_id and round_record["roundNumber"] == round_number:
                return deepcopy(round_record)
        raise KeyError(f"Unknown managed round '{round_number}' for match '{match_id}'")

    def update_managed_round(self, round_id: str, **fields: Any) -> Dict[str, Any]:
        if round_id not in self.managed_rounds:
            raise KeyError(f"Unknown managed round '{round_id}'")
        for key, value in fields.items():
            self.managed_rounds[round_id][key] = deepcopy(value)
        return deepcopy(self.managed_rounds[round_id])

    def interrupt_incomplete_managed_matches(self) -> None:
        for match_record in self.managed_matches.values():
            if match_record["status"] in {"queued", "running"}:
                match_record["status"] = "interrupted"
        for round_record in self.managed_rounds.values():
            if round_record["status"] in {"queued", "running"}:
                round_record["status"] = "interrupted"

    def _require_match(self, match_id: str) -> None:
        if match_id not in self.matches:
            raise KeyError(f"Unknown match '{match_id}'")

    def _require_managed_match(self, match_id: str) -> None:
        if match_id not in self.managed_matches:
            raise KeyError(f"Unknown managed match '{match_id}'")
