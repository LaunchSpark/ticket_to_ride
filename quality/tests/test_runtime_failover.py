import unittest

from ticket_to_ride.backend.models import ManagedMatchSeatConfig
from ticket_to_ride.backend.runtime.controllers import RoundControllerRegistry
from ticket_to_ride.backend.runtime.failover import FailoverCoordinator
from ticket_to_ride.backend.runtime.models import ExecutionResult


class FakeExecutor:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id

    def start(self) -> None:
        return None

    def close(self) -> ExecutionResult:
        return ExecutionResult(status="ok", elapsed_ms=0)


class FailoverCoordinatorTests(unittest.TestCase):
    def _build_registry(self) -> RoundControllerRegistry:
        return RoundControllerRegistry.for_round(
            seats=[ManagedMatchSeatConfig(seatId="seat_1", primaryBotId="slow_bot")],
            fallback_bot_id="random_bot",
            timeout_policy="switch_to_fallback",
            executor_factory=lambda bot_id: FakeExecutor(bot_id),
        )

    def test_switch_to_fallback_updates_active_role_and_reason(self) -> None:
        registry = self._build_registry()
        seat = registry.seat("seat_1")
        coordinator = FailoverCoordinator()

        activated = coordinator.maybe_activate_fallback(
            seat,
            failure_status="bot_exception",
            reason="primary failed",
            controllers=registry,
        )

        self.assertTrue(activated)
        self.assertEqual(seat.active_role, "fallback")
        self.assertTrue(seat.has_failed_over)
        self.assertEqual(seat.failover_reason, "primary failed")
        self.assertEqual(seat.status, "fallback_active")

    def test_second_failover_chain_is_not_created(self) -> None:
        registry = self._build_registry()
        seat = registry.seat("seat_1")
        coordinator = FailoverCoordinator()
        coordinator.activate_fallback(seat, reason="primary failed", controllers=registry)

        activated = coordinator.maybe_activate_fallback(
            seat,
            failure_status="bot_exception",
            reason="fallback failed",
            controllers=registry,
        )

        self.assertFalse(activated)
        self.assertEqual(seat.active_role, "fallback")

    def test_new_round_registry_starts_back_on_primary(self) -> None:
        registry = self._build_registry()
        seat = registry.seat("seat_1")
        FailoverCoordinator().activate_fallback(seat, reason="primary failed", controllers=registry)

        next_round_registry = self._build_registry()
        next_round_seat = next_round_registry.seat("seat_1")
        self.assertEqual(next_round_seat.active_role, "primary")
        self.assertFalse(next_round_seat.has_failed_over)


if __name__ == "__main__":
    unittest.main()
