import unittest
from ticket_to_ride.board_view import LOCOMOTIVE_GRADIENT_STOPS, build_segments, card_color_hex
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.map import Route


class SegmentTests(unittest.TestCase):
    def test_all_kinds(self):
        mixed = Route("A", "B", 4, "X", "r", cost=parse_cost("2(G|B)+1X+1L", 4))
        segments = build_segments(mixed)
        self.assertEqual([s["kind"] for s in segments],
                         ["options", "options", "solid", "loco"])
        self.assertEqual(segments[-1]["colors"], LOCOMOTIVE_GRADIENT_STOPS)

    def test_classic_and_card_gradient(self):
        self.assertEqual(build_segments(Route("A", "B", 2, "R", "r"))[0],
                         {"kind": "solid", "colors": ["#d62728"]})
        self.assertEqual(card_color_hex()["L"], {"stops": LOCOMOTIVE_GRADIENT_STOPS})


if __name__ == "__main__": unittest.main()
