"""Map evaluation: the two optimization loops for generated maps.

Loop 1 — structural realism: handcrafted descriptors answering "does this
*look* like a Ticket to Ride map?" (a prior over plausible maps).
Loop 2 — gameplay quality: a QualifierBot mirror-match gauntlet answering
"does this map *play* balanced?" (self-play isolates the map: any seat bias
or degenerate metric is the map's fault, not a bot mismatch).

Both land in one MapProfile row (results/map_profiles.jsonl) — the archive
that later trains the surrogate critic and feeds the novelty distance.
Run the human maps first: their profiles are the calibration bands.

    uv run python operations/research/map_eval.py --maps classic,europe --games 40
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "applications"))
sys.path.insert(0, str(REPO / "integrations"))

from external.bots.qualifier_bot import QualifierBot          # noqa: E402
from notebook_harness.game_runner import initialize_game      # noqa: E402
from ticket_to_ride.engine.state.decks import TicketDeck, resolve_tickets_path  # noqa: E402
from ticket_to_ride.engine.state.map import MapGraph          # noqa: E402

RESULTS_DIR = REPO / "operations" / "research" / "results"
PROFILES_FILE = RESULTS_DIR / "map_profiles.jsonl"
PROFILE_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Loop 1: structural descriptors
# ---------------------------------------------------------------------------

def _simple_adjacency(map_graph) -> dict:
    """city -> set of neighboring cities (multi-edges collapsed)."""
    adjacency: dict = {}
    for route in map_graph.routes:
        adjacency.setdefault(route.city1, set()).add(route.city2)
        adjacency.setdefault(route.city2, set()).add(route.city1)
    return adjacency


def _hop_distances(adjacency, source) -> dict:
    distances = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency[node]:
            if neighbor not in distances:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    return distances


def _edge_betweenness(adjacency) -> dict:
    """Brandes' algorithm on the simple city graph (unweighted)."""
    betweenness = {}
    nodes = list(adjacency)
    for source in nodes:
        stack, predecessors = [], {v: [] for v in nodes}
        sigma = {v: 0 for v in nodes}
        sigma[source] = 1
        distance = {v: -1 for v in nodes}
        distance[source] = 0
        queue = deque([source])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adjacency[v]:
                if distance[w] < 0:
                    distance[w] = distance[v] + 1
                    queue.append(w)
                if distance[w] == distance[v] + 1:
                    sigma[w] += sigma[v]
                    predecessors[w].append(v)
        delta = {v: 0.0 for v in nodes}
        while stack:
            w = stack.pop()
            for v in predecessors[w]:
                share = (sigma[v] / sigma[w]) * (1 + delta[w])
                edge = tuple(sorted((v, w)))
                betweenness[edge] = betweenness.get(edge, 0.0) + share
                delta[v] += share
    return {edge: value / 2 for edge, value in betweenness.items()}


def _gini(values) -> float:
    values = sorted(values)
    n = len(values)
    total = sum(values)
    if not n or not total:
        return 0.0
    cumulative = sum((i + 1) * v for i, v in enumerate(values))
    return (2 * cumulative) / (n * total) - (n + 1) / n


def structural_profile(map_name: str) -> dict:
    """Loop-1 descriptors: pure functions of the map + ticket files."""
    map_graph = MapGraph(player_count=2, map_name=map_name)
    adjacency = _simple_adjacency(map_graph)
    cities = sorted(adjacency)

    degrees = [len(adjacency[c]) for c in cities]
    hops = []
    eccentricities = []
    for city in cities:
        distances = _hop_distances(adjacency, city)
        reachable = [d for d in distances.values() if d > 0]
        hops.extend(reachable)
        eccentricities.append(max(reachable, default=0))

    # clustering coefficient of the simple graph
    triangles = 0.0
    triples = 0
    for city in cities:
        neighbors = list(adjacency[city])
        k = len(neighbors)
        triples += k * (k - 1) // 2
        triangles += sum(
            1 for i in range(k) for j in range(i + 1, k)
            if neighbors[j] in adjacency[neighbors[i]]
        )

    betweenness = _edge_betweenness(adjacency)
    doubles = sum(
        1 for route in map_graph.routes
        if len(map_graph.get_sibling_routes(route)) > 0
    )
    color_length: Counter = Counter()
    for route in map_graph.routes:
        color_length[route.color] += route.length

    # tickets measured against the empty board
    culled = map_graph.culled_map_for("__probe__")
    deck = TicketDeck(resolve_tickets_path(map_name))
    tickets = deck.deal_unique(len(deck))
    ticket_distances = [
        culled.cheapest_connection(t.city1, t.city2) for t in tickets
    ]
    value_per_train = [
        t.value / d for t, d in zip(tickets, ticket_distances) if d
    ]

    return {
        "cities": len(cities),
        "routes": len(map_graph.routes),
        "double_route_fraction": round(doubles / len(map_graph.routes), 3),
        "degree_mean": round(statistics.mean(degrees), 2),
        "degree_max": max(degrees),
        "hop_diameter": max(eccentricities),
        "mean_hop_distance": round(statistics.mean(hops), 2),
        "clustering": round(triangles / triples, 3) if triples else 0.0,
        "betweenness_max": round(max(betweenness.values()), 1),
        "betweenness_gini": round(_gini(list(betweenness.values())), 3),
        "route_length_hist": dict(sorted(Counter(r.length for r in map_graph.routes).items())),
        "gray_length_fraction": round(color_length["X"] / sum(color_length.values()), 3),
        "colored_length_spread": max(v for c, v in color_length.items() if c != "X")
        - min(v for c, v in color_length.items() if c != "X"),
        "ferry_routes": sum(1 for r in map_graph.routes if r.locomotives > 0),
        "tunnel_routes": sum(1 for r in map_graph.routes if r.is_tunnel),
        "tickets": len(tickets),
        "ticket_value_mean": round(statistics.mean(t.value for t in tickets), 2),
        "ticket_distance_mean": round(statistics.mean(d for d in ticket_distances if d), 2),
        "ticket_value_per_train": round(statistics.mean(value_per_train), 3) if value_per_train else 0.0,
    }


# ---------------------------------------------------------------------------
# Loop 2: gameplay gauntlet (QualifierBot mirror matches)
# ---------------------------------------------------------------------------

def _ticket_bridges(player, claimed) -> int:
    """Claims that are load-bearing: removing them disconnects a completed ticket."""
    completed = [t for t in player.get_tickets() if t.is_completed]

    def connects(ticket, routes):
        parent: dict = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for r in routes:
            ra, rb = find(r.city1), find(r.city2)
            if ra != rb:
                parent[ra] = rb
        return find(ticket.city1) == find(ticket.city2)

    return sum(
        1 for route in claimed
        if any(not connects(t, [r for r in claimed if r is not route]) for t in completed)
    )


def gauntlet_profile(map_name: str, games: int = 40, seed_base: int = 20000) -> dict:
    """Loop-2 emergent metrics from QualifierBot self-play."""
    seat0_wins = margins = 0
    margin_list, scores, turns, trains_left = [], [], [], []
    kept = completed = impossible = 0
    claims_per_route: Counter = Counter()
    color_demand: Counter = Counter()
    bridge_claims = total_claims = 0

    for i in range(games):
        game = initialize_game(
            [QualifierBot(), QualifierBot()], map_name=map_name, seed=seed_base + i,
        )
        game.play()
        context = game.game.context
        s = context.scores
        margin = s["bot_0"] - s["bot_1"]
        margin_list.append(margin)
        seat0_wins += margin > 0
        turns.append(game.snapshot_count())
        for player in game.players:
            scores.append(s[player.player_id])
            trains_left.append(player.trains_remaining)
            tickets = player.get_tickets()
            kept += len(tickets)
            completed += sum(t.is_completed for t in tickets)
            impossible += sum(t.is_impossible for t in tickets)
            claimed = context.get_map().get_claimed_routes(player.player_id)
            total_claims += len(claimed)
            bridge_claims += _ticket_bridges(player, claimed)
            for route in claimed:
                claims_per_route[route.route_id] += 1
                color_demand[route.color] += route.length

    route_count = len(MapGraph(player_count=2, map_name=map_name).routes)
    total_route_claims = sum(claims_per_route.values())
    entropy = -sum(
        (c / total_route_claims) * math.log(c / total_route_claims)
        for c in claims_per_route.values()
    ) if total_route_claims else 0.0

    return {
        "games": games,
        "seat0_win_rate": round(seat0_wins / games, 3),
        "margin_mean": round(statistics.mean(margin_list), 1),
        "margin_abs_mean": round(statistics.mean(abs(m) for m in margin_list), 1),
        "margin_std": round(statistics.pstdev(margin_list), 1),
        "score_mean": round(statistics.mean(scores), 1),
        "score_std": round(statistics.pstdev(scores), 1),
        "game_length_mean": round(statistics.mean(turns), 1),
        "ticket_completion_rate": round(completed / kept, 3) if kept else 0.0,
        "ticket_impossible_rate": round(impossible / kept, 3) if kept else 0.0,
        "trains_left_mean": round(statistics.mean(trains_left), 1),
        "routes_used_fraction": round(len(claims_per_route) / route_count, 3),
        "dead_routes": route_count - len(claims_per_route),
        "claim_entropy": round(entropy / math.log(route_count), 3) if route_count > 1 else 0.0,
        "critical_claim_fraction": round(bridge_claims / total_claims, 3) if total_claims else 0.0,
        "color_demand": {c: color_demand[c] for c in sorted(color_demand)},
        "most_contested": [rid for rid, _ in claims_per_route.most_common(5)],
    }


def map_profile(map_name: str, games: int = 40, seed_base: int = 20000) -> dict:
    return {
        "map": map_name,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "structural": structural_profile(map_name),
        "gameplay": gauntlet_profile(map_name, games, seed_base),
    }


def descriptor_vector(profile: dict) -> 'list[float]':
    """Flat numeric descriptor for novelty distance / critic features."""
    s, g = profile["structural"], profile["gameplay"]
    keys_s = ["cities", "routes", "double_route_fraction", "degree_mean",
              "hop_diameter", "mean_hop_distance", "clustering",
              "betweenness_gini", "gray_length_fraction",
              "ticket_value_per_train", "ticket_distance_mean"]
    keys_g = ["seat0_win_rate", "margin_abs_mean", "score_mean",
              "ticket_completion_rate", "routes_used_fraction",
              "claim_entropy", "critical_claim_fraction"]
    return [float(s[k]) for k in keys_s] + [float(g[k]) for k in keys_g]


def append_profile(profile: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with PROFILES_FILE.open("a") as handle:
        handle.write(json.dumps(profile) + "\n")


def load_profiles() -> list:
    if not PROFILES_FILE.exists():
        return []
    return [json.loads(line) for line in PROFILES_FILE.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", default="classic,europe")
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--seed-base", type=int, default=20000)
    args = parser.parse_args()

    profiles = []
    for map_name in args.maps.split(","):
        started = time.perf_counter()
        profile = map_profile(map_name.strip(), args.games, args.seed_base)
        append_profile(profile)
        profiles.append(profile)
        print(f"\n=== {map_name} ({time.perf_counter() - started:.1f}s) ===")
        for section in ("structural", "gameplay"):
            for key, value in profile[section].items():
                print(f"  {section[:6]}.{key}: {value}")

    if len(profiles) > 1:
        print("\ndescriptor vectors (novelty space):")
        for profile in profiles:
            print(f"  {profile['map']}: "
                  + ", ".join(f"{v:.2f}" for v in descriptor_vector(profile)))


if __name__ == "__main__":
    main()
