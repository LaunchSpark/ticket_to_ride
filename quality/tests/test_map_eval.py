from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[2] / "operations" / "research" / "map_eval.py"
_spec = importlib.util.spec_from_file_location("map_eval", _MODULE)
map_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(map_eval)


class StructuralProfileTests(unittest.TestCase):
    def test_classic_descriptors(self):
        s = map_eval.structural_profile("classic")
        self.assertEqual(s["cities"], 36)
        self.assertEqual(s["routes"], 100)
        self.assertGreater(s["hop_diameter"], 3)
        self.assertEqual(s["ferry_routes"], 0)
        # official maps price tickets at ~1 point per train of distance
        self.assertAlmostEqual(s["ticket_value_per_train"], 1.0, delta=0.15)

    def test_europe_descriptors(self):
        s = map_eval.structural_profile("europe")
        self.assertEqual(s["cities"], 47)
        self.assertEqual(s["ferry_routes"], 13)
        self.assertEqual(s["tunnel_routes"], 18)
        self.assertAlmostEqual(s["ticket_value_per_train"], 1.0, delta=0.15)


class GauntletTests(unittest.TestCase):
    def test_small_gauntlet_produces_sane_metrics(self):
        g = map_eval.gauntlet_profile("classic", games=4, seed_base=31000)
        self.assertEqual(g["games"], 4)
        self.assertGreater(g["routes_used_fraction"], 0.3)
        self.assertLessEqual(g["seat0_win_rate"], 1.0)
        self.assertGreater(g["claim_entropy"], 0.5)

    def test_profile_and_descriptor_vector(self):
        profile = map_eval.map_profile("classic", games=2, seed_base=32000)
        vector = map_eval.descriptor_vector(profile)
        self.assertEqual(len(vector), 18)
        self.assertTrue(all(isinstance(v, float) for v in vector))


if __name__ == "__main__":
    unittest.main()
