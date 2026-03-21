from __future__ import annotations

"""
Own internal runtime data structures and status literals.

This module is responsible for:
- the match-scoped execution context
- round-scoped seat/controller models
- normalized executor results
- round-local termination signals

This module does not own:
- HTTP request/response models
- round orchestration behavior
- replay persistence logic
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from ticket_to_ride.backend.models import ManagedMatchSeatConfig, RoundClockSeatView, TimeControlConfig

if TYPE_CHECKING:
    from ticket_to_ride.backend.runtime.executor import BotExecutor
    from ticket_to_ride.backend.runtime.round_runtime import RoundExecutionContext


ExecutionResultStatus = Literal[
    "ok",
    "bot_exception",
    "per_call_timeout",
    "clock_flagged",
    "invalid_response",
    "transport_error",
    "controller_teardown_failed",
]
ControllerState = Literal["created", "ready", "running", "timed_out", "failed", "completed", "terminated"]
SeatActiveRole = Literal["primary", "fallback"]
SeatRuntimeStatus = Literal["primary_active", "fallback_active", "failed_over", "eliminated", "completed"]
TimeoutPolicy = Literal["loss_on_time", "switch_to_fallback", "abort_match"]
RoundStatus = Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
MatchStatus = Literal["queued", "running", "completed", "failed", "aborted", "interrupted"]
ExecutionMode = Literal["bot_api"]


@dataclass
class ExecutionResult:
    """Normalized outcome of one executor action or teardown request."""

    status: ExecutionResultStatus
    elapsed_ms: int
    payload: Any = None
    detail: str = ""


@dataclass
class BotClockState:
    """Round-scoped chess clock state for one seat."""

    seat_id: str
    initial_time_ms: int
    remaining_time_ms: int
    last_call_started_at: Optional[float] = None
    is_flagged: bool = False
    flag_reason: Optional[str] = None

    def view(self, active_role: SeatActiveRole) -> RoundClockSeatView:
        """Build the public clock view for this seat."""

        return RoundClockSeatView(
            seatId=self.seat_id,
            activeRole=active_role,
            initialTimeMs=self.initial_time_ms,
            remainingTimeMs=self.remaining_time_ms,
            isFlagged=self.is_flagged,
            flagReason=self.flag_reason,
        )


@dataclass
class SeatControllerRuntime:
    """One live controller instance for one seat role in one round."""

    seat_id: str
    player_id: str
    role: SeatActiveRole
    bot_id: str
    executor: "BotExecutor"
    state: ControllerState = "created"
    creation_time: float = field(default_factory=time.monotonic)
    failure_reason: Optional[str] = None

    def to_state(self) -> str:
        """Return the public controller-state string for runtime views."""

        return self.state


@dataclass
class RoundSeatRuntime:
    """Round-scoped routing and failover state for one seat."""

    seat_id: str
    player_id: str
    primary_bot_id: str
    fallback_bot_id: str
    timeout_policy: TimeoutPolicy
    active_role: SeatActiveRole = "primary"
    primary_controller: Optional[SeatControllerRuntime] = None
    fallback_controller: Optional[SeatControllerRuntime] = None
    has_failed_over: bool = False
    failover_reason: Optional[str] = None
    status: SeatRuntimeStatus = "primary_active"

    def active_controller(self) -> Optional[SeatControllerRuntime]:
        """Return the currently active controller for this seat."""

        if self.active_role == "fallback":
            return self.fallback_controller
        return self.primary_controller


@dataclass
class MatchExecutionContext:
    """Live match-scoped state for one managed match series."""

    match_id: str
    name: str
    seats: list[ManagedMatchSeatConfig]
    fallback_bot_id: str
    round_count: int
    time_control: TimeControlConfig
    timeout_policy: TimeoutPolicy
    execution_mode: ExecutionMode
    bot_names: Dict[str, str]
    replay_match_id: Optional[str] = None
    status: MatchStatus = "queued"
    current_round_number: Optional[int] = None
    active_round: Optional["RoundExecutionContext"] = None


class RoundTerminationError(RuntimeError):
    """Signal that a round can no longer continue for the given seat."""

    def __init__(self, seat_id: str, reason: str, *, abort_match: bool = False, runtime_failure: bool = False) -> None:
        self.seat_id = seat_id
        self.reason = reason
        self.abort_match = abort_match
        self.runtime_failure = runtime_failure
        super().__init__(reason)
