import unittest
from collections import Counter

from ticket_to_ride.engine.actions import ClaimRoute, claim_spend, enumerate_claim_actions
from ticket_to_ride.engine.state.costs import parse_cost
from ticket_to_ride.engine.state.map import Route


def actions(route, hand):
    return enumerate_claim_actions([route], {route.sibling_group_key(): [route]},
                                   lambda r: r.claimed_by, "p0", 2,
                                   Counter(hand), 45)


class PaymentTests(unittest.TestCase):
    def test_classic_spend(self):
        route = Route("A", "B", 4, "R", "r")
        self.assertEqual(+claim_spend(ClaimRoute("r", "R", 1), route),
                         Counter(R=3, L=1))

    def test_fixed_mixed_and_substitution(self):
        route = Route("A", "B", 5, "X", "r", cost=parse_cost("3U+2R", 5))
        self.assertFalse(actions(route, {"U": 3, "R": 1}))
        found = actions(route, {"U": 2, "R": 2, "L": 1})
        self.assertIn(Counter(U=2, R=2, L=1),
                      [+claim_spend(action, route) for action in found])

    def test_uniform_and_same_color_aggregation(self):
        route = Route("A", "B", 4, "X", "r", cost=parse_cost("2(G|B)+2X", 4))
        self.assertFalse(actions(route, {"G": 1, "B": 1, "W": 2}))
        spends = [+claim_spend(action, route) for action in actions(route, {"G": 4})]
        self.assertIn(Counter(G=4), spends)
        self.assertEqual(len({tuple(sorted(s.items())) for s in spends}), len(spends))

    def test_all_locomotives_pay_mixed_grey(self):
        route = Route("A", "B", 4, "X", "r", cost=parse_cost("2(G|B)+2X", 4))
        spends = [+claim_spend(action, route) for action in actions(route, {"L": 4})]
        self.assertEqual(spends, [Counter(L=4)])

    def test_locomotive_floor(self):
        route = Route("A", "B", 5, "X", "r", cost=parse_cost("2L+3U", 5))
        spends = [+claim_spend(action, route) for action in actions(route, {"L": 4, "U": 1})]
        self.assertIn(Counter(L=4, U=1), spends)


if __name__ == "__main__": unittest.main()
