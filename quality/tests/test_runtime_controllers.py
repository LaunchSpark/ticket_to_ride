import unittest
from collections import defaultdict

from ticket_to_ride.backend.models import ManagedMatchSeatConfig
from ticket_to_ride.backend.runtime.controllers import RoundControllerRegistry
from ticket_to_ride.backend.runtime.models import ExecutionResult


class FakeExecutor:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> ExecutionResult:
        self.closed = True
        return ExecutionResult(status="ok", elapsed_ms=0)


class FakeExecutorFactory:
    def __init__(self) -> None:
        self.creation_counts = defaultdict(int)
        self.executors: list[FakeExecutor] = []

    def __call__(self, bot_id: str) -> FakeExecutor:
        self.creation_counts[bot_id] += 1
        executor = FakeExecutor(bot_id)
        self.executors.append(executor)
        return executor


class RoundControllerRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FakeExecutorFactory()
        self.registry = RoundControllerRegistry.for_round(
            seats=[
                ManagedMatchSeatConfig(seatId="seat_1", primaryBotId="slow_bot"),
                ManagedMatchSeatConfig(seatId="seat_2", primaryBotId="steady_bot"),
            ],
            fallback_bot_id="random_bot",
            timeout_policy="switch_to_fallback",
            executor_factory=self.factory,
        )

    def test_initialize_primary_controllers_creates_primary_runtime_for_each_seat(self) -> None:
        self.registry.initialize_primary_controllers()
        self.assertEqual(self.factory.creation_counts["slow_bot"], 1)
        self.assertEqual(self.factory.creation_counts["steady_bot"], 1)
        self.assertEqual(self.registry.seat("seat_1").primary_controller.state, "ready")
        self.assertEqual(self.registry.seat("seat_2").primary_controller.state, "ready")

    def test_fallback_controller_is_created_lazily(self) -> None:
        seat = self.registry.seat("seat_1")
        self.assertIsNone(seat.fallback_controller)
        fallback = self.registry.ensure_controller(seat, "fallback")
        self.assertIsNotNone(fallback)
        self.assertEqual(self.factory.creation_counts["random_bot"], 1)

    def test_teardown_marks_created_controllers_terminated(self) -> None:
        self.registry.initialize_primary_controllers()
        seat = self.registry.seat("seat_1")
        self.registry.ensure_controller(seat, "fallback")
        self.registry.teardown()

        self.assertEqual(seat.primary_controller.state, "terminated")
        self.assertEqual(seat.fallback_controller.state, "terminated")
        self.assertTrue(all(executor.closed for executor in self.factory.executors))


if __name__ == "__main__":
    unittest.main()
