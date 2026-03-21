from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Dict, List
from uuid import uuid4

from ticket_to_ride.backend.models import AverageScoreRecord, PlayerRecord, utc_now_iso


class MatchRepository(ABC):
    @abstractmethod
    def create_match(self, name: str, players: List[PlayerRecord], player_names: List[str] | None = None) -> str:
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


class InMemoryMatchRepository(MatchRepository):
    def __init__(self) -> None:
        self.matches: Dict[str, Dict[str, Any]] = {}
        self.rounds: Dict[str, Dict[str, Any]] = {}
        self.turns: Dict[str, Dict[str, Any]] = {}

    def create_match(self, name: str, players: List[PlayerRecord], player_names: List[str] | None = None) -> str:
        match_id = str(uuid4())
        resolved_player_names = list(player_names or [player.name for player in players])
        self.matches[match_id] = {
            "id": match_id,
            "name": name,
            "playerNames": resolved_player_names,
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

    def _require_match(self, match_id: str) -> None:
        if match_id not in self.matches:
            raise KeyError(f"Unknown match '{match_id}'")
