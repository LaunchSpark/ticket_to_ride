import unittest

from ticket_to_ride.backend.models import TimeControlConfig
from ticket_to_ride.backend.runtime.clock import RoundClockTracker


class RoundClockTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = RoundClockTracker(
            seat_ids=["seat_1", "seat_2"],
            time_control=TimeControlConfig(
                initialTimeMs=200,
                incrementMs=20,
                perCallHardLimitMs=100,
            ),
        )

    def test_deduct_elapsed_reduces_remaining_time(self) -> None:
        self.tracker.deduct_elapsed("seat_1", 40)
        self.assertEqual(self.tracker.remaining_time("seat_1"), 160)

    def test_apply_turn_increment_restores_time_for_completed_turn(self) -> None:
        self.tracker.deduct_elapsed("seat_1", 50)
        self.tracker.apply_turn_increment("seat_1")
        self.assertEqual(self.tracker.remaining_time("seat_1"), 170)

    def test_effective_timeout_caps_to_hard_limit(self) -> None:
        self.assertEqual(self.tracker.effective_timeout_ms("seat_1"), 100)
        self.tracker.deduct_elapsed("seat_1", 150)
        self.assertEqual(self.tracker.effective_timeout_ms("seat_1"), 50)

    def test_flag_clock_marks_exhaustion_in_view(self) -> None:
        self.tracker.deduct_elapsed("seat_1", 250)
        clock_view = self.tracker.build_clock_view(
            match_id="match-1",
            round_number=0,
            status="running",
            active_roles={"seat_1": "primary", "seat_2": "primary"},
        )
        seat_view = next(seat for seat in clock_view.seats if seat.seatId == "seat_1")
        self.assertTrue(seat_view.isFlagged)
        self.assertEqual(seat_view.flagReason, "Seat clock exhausted.")


if __name__ == "__main__":
    unittest.main()
