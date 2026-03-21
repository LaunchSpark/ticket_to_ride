from __future__ import annotations

"""
Own round-scoped time accounting for one managed round.

This module is responsible for:
- storing BotClockState for each seat in the round
- computing effective call budgets
- deducting elapsed time from a seat clock
- applying turn increments and clock flags

This module does not own:
- failover decisions
- controller lifecycle
- match aggregation
"""

from typing import Dict, Iterable

from ticket_to_ride.backend.models import RoundClockView, TimeControlConfig
from ticket_to_ride.backend.runtime.models import BotClockState, RoundStatus, SeatActiveRole


class RoundClockTracker:
    """Track round-local clock state for all seats in one round."""

    def __init__(self, *, seat_ids: Iterable[str], time_control: TimeControlConfig) -> None:
        self.time_control = time_control
        self._clocks: Dict[str, BotClockState] = {
            seat_id: BotClockState(
                seat_id=seat_id,
                initial_time_ms=time_control.initialTimeMs,
                remaining_time_ms=time_control.initialTimeMs,
            )
            for seat_id in seat_ids
        }

    def clock(self, seat_id: str) -> BotClockState:
        """Return the mutable clock model for one seat."""

        return self._clocks[seat_id]

    def remaining_time(self, seat_id: str) -> int:
        """Return the remaining round time for one seat."""

        return self.clock(seat_id).remaining_time_ms

    def effective_timeout_ms(self, seat_id: str) -> int:
        """Return the effective hard timeout budget for the next controller call."""

        remaining_time_ms = self.remaining_time(seat_id)
        hard_limit = self.time_control.perCallHardLimitMs
        if hard_limit is None:
            return max(remaining_time_ms, 1)
        return max(min(remaining_time_ms, hard_limit), 1)

    def deduct_elapsed(self, seat_id: str, elapsed_ms: int) -> None:
        """Deduct elapsed time from the seat clock and flag on exhaustion."""

        if elapsed_ms <= 0:
            return
        clock = self.clock(seat_id)
        clock.remaining_time_ms = max(0, clock.remaining_time_ms - elapsed_ms)
        if clock.remaining_time_ms <= 0:
            self.flag_clock(seat_id, "Seat clock exhausted.")

    def apply_turn_increment(self, seat_id: str) -> None:
        """Apply the configured increment after a completed player turn."""

        increment_ms = self.time_control.incrementMs
        if not increment_ms:
            return
        clock = self.clock(seat_id)
        if clock.is_flagged:
            return
        clock.remaining_time_ms += increment_ms

    def flag_clock(self, seat_id: str, reason: str) -> None:
        """Mark a seat clock as exhausted for the current round."""

        clock = self.clock(seat_id)
        clock.is_flagged = True
        clock.flag_reason = reason

    def build_clock_view(
        self,
        *,
        match_id: str,
        round_number: int,
        status: RoundStatus,
        active_roles: Dict[str, SeatActiveRole],
    ) -> RoundClockView:
        """Build the public round clock view from internal clock state."""

        return RoundClockView(
            matchId=match_id,
            roundNumber=round_number,
            status=status,
            seats=[
                self.clock(seat_id).view(active_roles[seat_id])
                for seat_id in sorted(self._clocks)
            ],
        )
