from __future__ import annotations

"""
Own round-scoped failover transitions for seat controllers.

This module is responsible for:
- deciding whether a primary controller may fail over
- switching active controller role from primary to fallback
- recording round-local failover state and reason

This module does not own:
- clock accounting
- controller transport details
- match-wide lifecycle
"""

from ticket_to_ride.backend.runtime.controllers import RoundControllerRegistry
from ticket_to_ride.backend.runtime.models import ExecutionResultStatus, RoundSeatRuntime, RoundTerminationError


class FailoverCoordinator:
    """Apply switch-to-fallback behavior within one round."""

    @staticmethod
    def can_fail_over(seat: RoundSeatRuntime, failure_status: ExecutionResultStatus) -> bool:
        """Return whether the seat may switch from primary to fallback for this failure."""

        return (
            failure_status != "clock_flagged"
            and seat.timeout_policy == "switch_to_fallback"
            and seat.active_role == "primary"
        )

    def maybe_activate_fallback(
        self,
        seat: RoundSeatRuntime,
        *,
        failure_status: ExecutionResultStatus,
        reason: str,
        controllers: RoundControllerRegistry,
    ) -> bool:
        """Switch to the fallback controller when the policy allows it."""

        if not self.can_fail_over(seat, failure_status):
            return False
        self.activate_fallback(seat, reason=reason, controllers=controllers)
        return True

    def activate_fallback(
        self,
        seat: RoundSeatRuntime,
        *,
        reason: str,
        controllers: RoundControllerRegistry,
    ) -> None:
        """Promote the seat's fallback controller for the rest of the current round."""

        seat.has_failed_over = True
        seat.failover_reason = reason
        seat.active_role = "fallback"
        seat.status = "failed_over"
        fallback = controllers.ensure_controller(seat, "fallback")
        if fallback.state == "failed":
            raise RoundTerminationError(seat.seat_id, "Fallback controller could not be created.", runtime_failure=True)
        fallback.state = "ready"
        seat.status = "fallback_active"
