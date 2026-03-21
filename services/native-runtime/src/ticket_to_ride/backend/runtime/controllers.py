from __future__ import annotations

"""
Own round-scoped controller and seat routing state.

This module is responsible for:
- creating primary and fallback controller instances
- storing per-seat primary/fallback controller handles
- exposing the active controller for each seat
- tearing controllers down at round end

This module does not own:
- clock accounting
- failover policy decisions
- engine/game execution
"""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable

from ticket_to_ride.backend.models import ManagedMatchSeatConfig, RoundRuntimeSeatView, RoundRuntimeView
from ticket_to_ride.backend.runtime.executor import BotExecutor
from ticket_to_ride.backend.runtime.models import (
    ExecutionResultStatus,
    RoundSeatRuntime,
    RoundStatus,
    SeatActiveRole,
    SeatControllerRuntime,
    TimeoutPolicy,
)


@dataclass
class RoundControllerRegistry:
    """Own all seat/controller runtimes for one managed round."""

    seats: Dict[str, RoundSeatRuntime]
    executor_factory: Callable[[str], BotExecutor]

    @classmethod
    def for_round(
        cls,
        *,
        seats: Iterable[ManagedMatchSeatConfig],
        fallback_bot_id: str,
        timeout_policy: TimeoutPolicy,
        executor_factory: Callable[[str], BotExecutor],
    ) -> "RoundControllerRegistry":
        """Create the round seat/controller registry from match-scoped seat config."""

        return cls(
            seats={
                seat.seatId: RoundSeatRuntime(
                    seat_id=seat.seatId,
                    player_id=seat.seatId,
                    primary_bot_id=seat.primaryBotId,
                    fallback_bot_id=fallback_bot_id,
                    timeout_policy=timeout_policy,
                )
                for seat in seats
            },
            executor_factory=executor_factory,
        )

    def seat(self, seat_id: str) -> RoundSeatRuntime:
        """Return the round runtime state for one seat."""

        return self.seats[seat_id]

    def active_roles(self) -> Dict[str, SeatActiveRole]:
        """Return the active controller role for each seat."""

        return {seat_id: seat.active_role for seat_id, seat in self.seats.items()}

    def initialize_primary_controllers(self) -> None:
        """Create primary controllers for all seats at the start of a round."""

        for seat in self.seats.values():
            self.ensure_controller(seat, "primary")

    def active_controller(self, seat: RoundSeatRuntime) -> SeatControllerRuntime | None:
        """Return the active controller handle for a seat."""

        return seat.active_controller()

    def ensure_controller(self, seat: RoundSeatRuntime, role: SeatActiveRole) -> SeatControllerRuntime:
        """Create the requested controller lazily and return its runtime handle."""

        controller = seat.primary_controller if role == "primary" else seat.fallback_controller
        if controller is not None:
            return controller

        bot_id = seat.primary_bot_id if role == "primary" else seat.fallback_bot_id
        executor = self.executor_factory(bot_id)
        controller = SeatControllerRuntime(
            seat_id=seat.seat_id,
            player_id=seat.player_id,
            role=role,
            bot_id=bot_id,
            executor=executor,
        )
        try:
            executor.start()
        except Exception as exc:
            controller.state = "failed"
            controller.failure_reason = str(exc)
        else:
            controller.state = "ready"

        if role == "primary":
            seat.primary_controller = controller
        else:
            seat.fallback_controller = controller
        return controller

    @staticmethod
    def mark_ready(controller: SeatControllerRuntime) -> None:
        """Mark a controller as ready after a successful decision call."""

        controller.state = "ready"
        controller.failure_reason = None

    @staticmethod
    def mark_failed(controller: SeatControllerRuntime, status: ExecutionResultStatus, detail: str) -> None:
        """Mark a controller after a failed decision call."""

        controller.state = "timed_out" if status == "per_call_timeout" else "failed"
        controller.failure_reason = detail

    def teardown(self) -> None:
        """Close all controllers that were created for the round."""

        controllers: list[SeatControllerRuntime] = []
        for seat in self.seats.values():
            if seat.primary_controller is not None:
                controllers.append(seat.primary_controller)
            if seat.fallback_controller is not None:
                controllers.append(seat.fallback_controller)
        for controller in controllers:
            result = controller.executor.close()
            controller.state = "terminated" if result.status == "ok" else "failed"
            controller.failure_reason = result.detail or controller.failure_reason

    def build_runtime_view(
        self,
        *,
        match_id: str,
        round_number: int,
        status: RoundStatus,
        replay_round_id: str,
    ) -> RoundRuntimeView:
        """Build the public runtime view for the current round."""

        return RoundRuntimeView(
            matchId=match_id,
            roundNumber=round_number,
            status=status,
            replayRoundId=replay_round_id,
            seats=[
                RoundRuntimeSeatView(
                    seatId=seat.seat_id,
                    playerId=seat.player_id,
                    primaryBotId=seat.primary_bot_id,
                    fallbackBotId=seat.fallback_bot_id,
                    activeRole=seat.active_role,
                    hasFailedOver=seat.has_failed_over,
                    failoverReason=seat.failover_reason,
                    status=seat.status,
                    primaryControllerState=seat.primary_controller.to_state() if seat.primary_controller else "created",
                    fallbackControllerState=seat.fallback_controller.to_state() if seat.fallback_controller else None,
                )
                for seat in sorted(self.seats.values(), key=lambda item: item.seat_id)
            ],
        )
