import csv
import tempfile
import unittest
from pathlib import Path

from ticket_to_ride.engine.state.costs import (
    CARD_COLORS, CostComponent, CostError, cost_to_str, parse_cost, synthesize_cost,
)
from ticket_to_ride.engine.state.map import MapGraph, Route, resolve_map_path


def write_map_csv(rows, header=("city1", "city2", "Distance", "Color", "Cost")):
    path = Path(tempfile.mkdtemp()) / "mixed_test.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(header); writer.writerows(rows)
    return path


MIXED_ROWS = [("Ax", "Bx", "5", "X", "3U+2R"),
              ("Bx", "Cx", "4", "X", "2(G|B)+2X"),
              ("Cx", "Dx", "3", "X", "3L"),
              ("Ax", "Dx", "5", "X", "2L+3U"),
              ("Ax", "Cx", "2", "R", "")]


class CostTests(unittest.TestCase):
    def test_parse_and_round_trip(self):
        for spec, length in (("3U+2R", 5), ("2(G|B)+2X", 4), ("2L+3U", 5)):
            self.assertEqual(cost_to_str(parse_cost(spec, length)), spec)

    def test_semantics(self):
        self.assertEqual(parse_cost(" 3U + 2R ", 5),
                         (CostComponent(3, ("U",)), CostComponent(2, ("R",))))
        self.assertEqual(CostComponent(2, ("X",)).concrete_options(), CARD_COLORS)
        self.assertEqual(synthesize_cost(3, "X"), (CostComponent(3, ("X",)),))

    def test_guards(self):
        for bad, length in (("", 3), ("0U+3R", 3), ("3Q", 3),
                            ("2(G|G)", 2), ("2(L|U)", 2),
                            ("2(X|U)", 2), ("3U+2R", 6)):
            with self.assertRaises(CostError, msg=bad):
                parse_cost(bad, length)
        with self.assertRaises(CostError):
            parse_cost("1U+1R+1Y+1(G|B)", 4)

    def test_route_and_loader_wiring(self):
        path = write_map_csv(MIXED_ROWS)
        self.assertEqual(resolve_map_path(str(path)), path)
        graph = MapGraph(2, str(path))
        route = graph.routes[0]
        self.assertIsNone(route.color)
        self.assertEqual(route.payment_colors(), frozenset({"U", "R"}))
        self.assertIn("3U+2R", route.route_label)
        self.assertEqual(graph.routes[-1].cost, (CostComponent(2, ("R",)),))

    def test_loader_error_names_row(self):
        path = write_map_csv([("Ax", "Bx", "5", "X", "3U+9R")])
        with self.assertRaisesRegex(CostError, "Ax-Bx"):
            MapGraph(2, str(path))


if __name__ == "__main__": unittest.main()
