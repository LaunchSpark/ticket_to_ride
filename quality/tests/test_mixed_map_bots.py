"""Supported bots stay legal and finish games on mixed-cost maps."""
import csv
import random
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "applications", REPO / "integrations"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from external.bots.example_bot import ExampleBot
from external.bots.qualifier_bot import QualifierBot
from external.bots.random_bot import RandomBot
from notebook_harness.game_runner import initialize_game


class MixedMapBotSmokeTests(unittest.TestCase):
    def test_supported_bots_finish_a_mixed_map_game(self):
        random.seed(90210)
        with tempfile.TemporaryDirectory() as tmp:
            map_path = Path(tmp) / "mixed.csv"
            with (REPO / "operations/data/maps/classic.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            # Preserve the classic topology/ticket cities while exercising
            # each mixed-cost shape in normal planner pathfinding.
            mixed_costs = {
                0: "1U+2R",
                3: "2(G|B)+2X",
                4: "2L+4Y",
            }
            with map_path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("city1", "city2", "Distance", "Color", "Cost"))
                for index, row in enumerate(rows):
                    writer.writerow((row["city1"], row["city2"], row["Distance"],
                                     row["Color"], mixed_costs.get(index, "")))
            harness = initialize_game(
                [QualifierBot(), ExampleBot(), RandomBot()],
                map_name=str(map_path), seed=90210)
            harness.play()

        self.assertGreater(harness.snapshot_count(), 0)


if __name__ == "__main__":
    unittest.main()
