"""Claim-version caching and affordability-consolidation parity tests.

The caches must be invisible: identical results to a cache-free engine,
invalidated exactly when a claim lands (the only board mutation).
"""
import random
import unittest
from collections import Counter

from ticket_to_ride.engine.actions import legal_claim_actions
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import _route_claimable_by
from ticket_to_ride.engine.state.views import PlayerView


class _StubInterface:
    def set_player(self, player):
        self.player = player


def _make_players(context, count=2):
    players = [Player(f"p{i}", _StubInterface(), f"p{i}", "red") for i in range(count)]
    for player in players:
        player.attach(context, players)
    return players


def _claim_some_routes(map_graph, player_ids, rng, claims=12):
    """Randomly claim up to `claims` legal routes across the given players."""
    for _ in range(claims):
        player_id = rng.choice(player_ids)
        candidates = map_graph.get_available_routes(player_id)
        if not candidates:
            return
        map_graph.claim_route(rng.choice(candidates), player_id)


class ClaimVersionCacheTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=11)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_version_bumps_only_on_claim(self):
        self.assertEqual(self.map.claim_version, 0)
        self.map.culled_map_for("p0")
        self.map.get_available_routes("p0")
        self.assertEqual(self.map.claim_version, 0)
        route = self.map.get_available_routes("p0")[0]
        self.map.claim_route(route, "p0")
        self.assertEqual(self.map.claim_version, 1)

    def test_culled_map_cached_between_claims(self):
        first = self.map.culled_map_for("p0")
        self.assertIs(self.map.culled_map_for("p0"), first)
        # another player's cache entry is independent
        self.assertIsNot(self.map.culled_map_for("p1"), first)
        route = self.map.get_available_routes("p1")[0]
        self.map.claim_route(route, "p1")
        rebuilt = self.map.culled_map_for("p0")
        self.assertIsNot(rebuilt, first)
        # any player's claim shrinks everyone's claimable-route view
        self.assertNotIn(route.route_id, [r.route_id for r in rebuilt.routes])

    def test_claim_snapshot_matches_route_scan(self):
        rng = random.Random(3)
        _claim_some_routes(self.map, ["p0", "p1"], rng)
        scanned = {r.route_id: r.claimed_by for r in self.map.routes if r.claimed_by}
        self.assertEqual(self.map.claim_snapshot(), scanned)
        # snapshot is a copy: mutating it must not corrupt the engine
        snapshot = self.map.claim_snapshot()
        snapshot["bogus"] = "p0"
        self.assertNotIn("bogus", self.map.claim_snapshot())

    def test_cached_culled_map_equals_uncached(self):
        rng = random.Random(7)
        _claim_some_routes(self.map, ["p0", "p1"], rng)
        warm = self.map.culled_map_for("p0")  # build cache
        fresh_context = GameContext(["p0", "p1"], seed=11)
        fresh_map = fresh_context.get_map()
        for route_id, player_id in self.map.claim_snapshot().items():
            fresh_map.claim_route(fresh_map.route_by_id(route_id), player_id)
        cold = fresh_map.culled_map_for("p0")
        self.assertEqual(warm.city_to_node, cold.city_to_node)
        self.assertEqual(warm.nodes, cold.nodes)
        self.assertEqual([r.route_id for r in warm.routes],
                         [r.route_id for r in cold.routes])


class CulledMapAdjacencyTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=19)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_adjacency_built_once_and_shared(self):
        culled = self.map.culled_map_for("p0")
        adjacency = culled.adjacency()
        self.assertIs(culled.adjacency(), adjacency)
        # the claim-version cache hands every consumer the same structure
        self.assertIs(self.map.culled_map_for("p0").adjacency(), adjacency)

    def test_adjacency_mirrors_surviving_routes(self):
        rng = random.Random(5)
        _claim_some_routes(self.map, ["p0", "p1"], rng)
        culled = self.map.culled_map_for("p0")
        adjacency = culled.adjacency()
        seen = sorted(
            (node, neighbor, route.route_id)
            for node, edges in adjacency.items()
            for neighbor, route in edges
        )
        expected = sorted(
            entry
            for route in culled.routes
            for entry in (
                (culled.endpoints(route)[0], culled.endpoints(route)[1], route.route_id),
                (culled.endpoints(route)[1], culled.endpoints(route)[0], route.route_id),
            )
        )
        self.assertEqual(seen, expected)

    def test_cheapest_connection_uses_route_lengths(self):
        culled = self.map.culled_map_for("p0")
        route = culled.routes[0]
        self.assertEqual(
            culled.cheapest_connection(route.city1, route.city2) <= route.length,
            True,
        )


class ViewMemoizationTests(unittest.TestCase):
    def setUp(self):
        self.context = GameContext(["p0", "p1"], seed=13)
        self.players = _make_players(self.context)
        self.map = self.context.get_map()

    def test_fresh_view_reuses_engine_cache(self):
        view = PlayerView("p0", self.context, self.players)
        self.assertIs(view.culled_map(), self.map.culled_map_for("p0"))
        self.assertIs(view.culled_map(), view.culled_map())

    def test_stale_view_falls_back_to_its_snapshot(self):
        view = PlayerView("p0", self.context, self.players)
        route = self.map.get_available_routes("p1")[0]
        self.map.claim_route(route, "p1")  # view is now stale
        stale = view.culled_map()
        # the snapshot predates the claim, so the route must still be claimable
        self.assertIn(route.route_id, [r.route_id for r in stale.routes])
        live = self.map.culled_map_for("p0")
        self.assertNotIn(route.route_id, [r.route_id for r in live.routes])
        self.assertIs(view.culled_map(), stale)  # still memoized

    def test_unknown_pool_memoized_and_copy_safe(self):
        view = PlayerView("p0", self.context, self.players)
        first = view.unknown_pool()
        first["R"] -= 999  # caller mutates their copy
        second = view.unknown_pool()
        self.assertGreaterEqual(second.get("R", 0), 0)
        self.assertEqual(second, view.unknown_pool())


def _reference_legal_claims(player):
    """legal_claim_actions as it was before consolidation (behavior oracle)."""
    from ticket_to_ride.engine.actions import ClaimRoute
    game = player.game_context
    hand = player.get_hand()
    locomotives = hand.get("L", 0)
    actions = []
    for route in game.get_map().get_available_routes(player.player_id):
        if route.length > player.trains_remaining:
            continue
        for spent_locos in range(min(locomotives, route.length) + 1):
            needed = route.length - spent_locos
            if needed == 0:
                actions.append(ClaimRoute(route.route_id, "L", spent_locos))
                continue
            colors = [route.color] if route.color != "X" else [c for c in hand if c != "L"]
            for color in colors:
                if hand.get(color, 0) >= needed:
                    actions.append(ClaimRoute(route.route_id, color, spent_locos))
    return actions


def _reference_affordable(view):
    """PlayerView.affordable_routes as it was before consolidation."""
    if not view.hand.total():
        return []
    locomotives = view.hand.get("L", 0)
    colors = Counter({c: n for c, n in view.hand.items() if c != "L" and n > 0})
    most_common = max(colors.values(), default=0)
    siblings_by_key = {}
    for route in view.routes:
        siblings_by_key.setdefault(route.sibling_group_key(), []).append(route)
    claim_of = lambda route: view.claimed_by.get(route.route_id)
    affordable = []
    for route in view.routes:
        siblings = [s for s in siblings_by_key[route.sibling_group_key()] if s is not route]
        if not _route_claimable_by(route, siblings, claim_of, view.player_id, view.player_count):
            continue
        if route.length > view.trains_remaining:
            continue
        for n in range(locomotives + 1):
            needed = route.length - n
            if colors.get(route.color, 0) >= needed or (route.color == "X" and most_common >= needed):
                affordable.append((route, n))
                break
    return affordable


class AffordabilityParityTests(unittest.TestCase):
    """The consolidated core must match the three old implementations
    exactly (contents and order) on randomized board states."""

    CARD_COLORS = ["R", "B", "G", "Y", "K", "W", "O", "P", "L"]

    def _randomized_state(self, rng, player_count):
        player_ids = [f"p{i}" for i in range(player_count)]
        context = GameContext(player_ids, seed=rng.randrange(2**16))
        players = _make_players(context, player_count)
        _claim_some_routes(context.get_map(), player_ids, rng,
                           claims=rng.randrange(0, 25))
        for player in players:
            player.get_hand().update(
                rng.choices(self.CARD_COLORS, k=rng.randrange(0, 12)))
            player.trains_remaining = rng.randrange(2, 46)
        return context, players

    def test_parity_on_randomized_states(self):
        rng = random.Random(42)
        for trial in range(20):
            # 2 players exercises the shared-double-route rule, 4 the other branch
            player_count = 2 if trial % 2 else 4
            context, players = self._randomized_state(rng, player_count)
            for player in players:
                with self.subTest(trial=trial, player=player.player_id):
                    self.assertEqual(
                        legal_claim_actions(player),
                        _reference_legal_claims(player),
                    )
                    view = PlayerView(player.player_id, context, players)
                    self.assertEqual(
                        view.affordable_routes(),
                        _reference_affordable(view),
                    )
                    # Player variant agrees with the view built from the same state
                    self.assertEqual(
                        [(r.route_id, n) for r, n in player.get_affordable_routes()],
                        [(r.route_id, n) for r, n in view.affordable_routes()],
                    )


if __name__ == "__main__":
    unittest.main()
