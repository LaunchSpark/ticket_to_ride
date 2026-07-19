from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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
    mapName: Optional[str] = None
    seed: Optional[int] = None


class MatchCreateResponse(BaseModel):
    matchId: str


class BotEntry(BaseModel):
    botId: str
    name: str
    version: str
    description: str
    author: str = ""
    tags: List[str] = Field(default_factory=list)
    source: Literal["local", "remote"]
    connectionId: Optional[str] = None
    baseUrl: Optional[str] = None


class ConnectionSummary(BaseModel):
    connectionId: str
    url: str
    status: Literal["online", "offline"]
    error: Optional[str] = None
    botCount: int = 0
    createdAt: str = ""


class BotListResponse(BaseModel):
    bots: List[BotEntry] = Field(default_factory=list)
    connections: List[ConnectionSummary] = Field(default_factory=list)


class BotCreateRequest(BaseModel):
    name: str


class BotCreateResponse(BaseModel):
    botId: str
    url: str


class ConnectionCreateRequest(BaseModel):
    url: str


class ConnectionCreateResponse(BaseModel):
    connection: ConnectionSummary
    bots: List[BotEntry] = Field(default_factory=list)


class NotebookLaunchResponse(BaseModel):
    botId: str
    url: str


class TimeControlConfig(BaseModel):
    initialTimeMs: int = Field(gt=0)
    incrementMs: int = Field(default=0, ge=0)
    perCallSoftLimitMs: Optional[int] = Field(default=None, gt=0)
    perCallHardLimitMs: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_limits(self) -> "TimeControlConfig":
        if (
            self.perCallSoftLimitMs is not None
            and self.perCallHardLimitMs is not None
            and self.perCallHardLimitMs < self.perCallSoftLimitMs
        ):
            raise ValueError("perCallHardLimitMs must be greater than or equal to perCallSoftLimitMs.")
        return self


class ManagedMatchSeatConfig(BaseModel):
    seatId: str = Field(min_length=1)
    primaryBotId: str = Field(min_length=1)


class ManagedMatchCreateRequest(BaseModel):
    name: Optional[str] = None
    seats: List[ManagedMatchSeatConfig] = Field(min_length=2)
    fallbackBotId: str = Field(default="random_bot", min_length=1)
    roundCount: int = Field(gt=0)
    timeControl: TimeControlConfig
    timeoutPolicy: Literal["loss_on_time", "switch_to_fallback", "abort_match"] = "loss_on_time"
    executionMode: Literal["bot_api"] = "bot_api"


class ManagedSeatAggregateResult(BaseModel):
    seatId: str
    primaryBotId: str
    roundsWon: int = 0
    roundsLost: int = 0
    runtimeFailures: int = 0


class ManagedMatchSummary(BaseModel):
    matchId: str
    name: str
    status: Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
    seats: List[ManagedMatchSeatConfig]
    fallbackBotId: str
    roundCount: int
    timeControl: TimeControlConfig
    timeoutPolicy: Literal["loss_on_time", "switch_to_fallback", "abort_match"]
    executionMode: Literal["bot_api"]
    replayMatchId: Optional[str] = None
    currentRoundNumber: Optional[int] = None
    aggregateResults: List[ManagedSeatAggregateResult] = Field(default_factory=list)
    createdAt: str


class ManagedSeatRoundResult(BaseModel):
    seatId: str
    primaryBotId: str
    activeBotId: str
    outcome: Literal["won", "lost", "runtime_failure", "won_by_forfeit", "aborted"]
    finalScore: Optional[int] = None
    remainingTimeMs: int
    activeRole: Literal["primary", "fallback"]
    hasFailedOver: bool = False
    failoverReason: Optional[str] = None


class ManagedRoundSummary(BaseModel):
    roundId: str
    matchId: str
    roundNumber: int
    status: Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
    replayRoundId: Optional[str] = None
    seatResults: List[ManagedSeatRoundResult] = Field(default_factory=list)
    createdAt: str


class RoundClockSeatView(BaseModel):
    seatId: str
    activeRole: Literal["primary", "fallback"]
    initialTimeMs: int
    remainingTimeMs: int
    isFlagged: bool = False
    flagReason: Optional[str] = None


class RoundClockView(BaseModel):
    matchId: str
    roundNumber: int
    status: Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
    seats: List[RoundClockSeatView] = Field(default_factory=list)


class RoundRuntimeSeatView(BaseModel):
    seatId: str
    playerId: str
    primaryBotId: str
    fallbackBotId: str
    activeRole: Literal["primary", "fallback"]
    hasFailedOver: bool = False
    failoverReason: Optional[str] = None
    status: Literal["primary_active", "fallback_active", "failed_over", "eliminated", "completed"]
    primaryControllerState: str
    fallbackControllerState: Optional[str] = None


class RoundRuntimeView(BaseModel):
    matchId: str
    roundNumber: int
    status: Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
    replayRoundId: Optional[str] = None
    seats: List[RoundRuntimeSeatView] = Field(default_factory=list)


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
    mapName: Optional[str] = None
    seed: Optional[int] = None
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
    mapName: Optional[str] = None
    seed: Optional[int] = None
    players: List[PlayerRecord]
    rounds: List[RoundPayload]
    averageScores: List[AverageScoreRecord]


class CulledBoardResponse(BaseModel):
    """A player's contracted board view, in the RouteGraphWidget data shape."""

    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
