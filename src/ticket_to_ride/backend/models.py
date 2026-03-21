from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PlayerRecord(BaseModel):
    playerId: str
    name: str
    color: str


class AverageScoreRecord(BaseModel):
    playerId: str
    scores: List[int] = Field(default_factory=list)


class MatchCreateRequest(BaseModel):
    name: Optional[str] = None
    players: List[PlayerRecord]
    playerNames: List[str] = Field(default_factory=list)


class MatchCreateResponse(BaseModel):
    matchId: str


class RoundCreateRequest(BaseModel):
    roundNumber: int


class RoundCreateResponse(BaseModel):
    roundId: str


class TurnCreateRequest(BaseModel):
    turnIndex: int
    turnState: Dict[str, Any]


class TurnCreateResponse(BaseModel):
    turnId: str


class MatchFinalizeResponse(BaseModel):
    matchId: str
    status: Literal["completed"]
    averageScores: List[AverageScoreRecord]


class MatchSummary(BaseModel):
    matchId: str
    name: str
    status: str
    playerCount: int
    playerNames: List[str] = Field(default_factory=list)
    createdAt: str


class RoundPayload(BaseModel):
    roundId: str
    roundNumber: int
    turns: List[Dict[str, Any]]


class MatchPayload(BaseModel):
    matchId: str
    name: str
    status: str
    createdAt: str
    playerNames: List[str] = Field(default_factory=list)
    players: List[PlayerRecord]
    rounds: List[RoundPayload]
    averageScores: List[AverageScoreRecord]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
