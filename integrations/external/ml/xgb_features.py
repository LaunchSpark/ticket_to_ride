"""Tabular state-action features for the explainable XG Bot.

The module is intentionally stdlib-only on import. Runtime code may import it
from bot discovery, notebook tests, or research scripts without installing the
``xgb`` optional extra. ``vectorize`` is the only function that imports NumPy.
"""
from __future__ import annotations

import csv
import heapq
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from ticket_to_ride.engine.state.costs import CostComponent, parse_cost, synthesize_cost

REPO = Path(__file__).resolve().parents[3]
MAPS_DIR = REPO / "operations" / "data" / "maps"

CARD_COLORS = ("W", "B", "U", "G", "Y", "O", "R", "P", "L")
TRAIN_COLORS = ("W", "B", "U", "G", "Y", "O", "R", "P")
ROUTE_COLORS = (*TRAIN_COLORS, "X")
ACTION_TYPES = ("ClaimRoute", "DrawBlind", "DrawFaceUp", "DrawTickets", "KeepTickets", "Pass")
DECISION_TYPES = ("turn", "draw_second", "keep_tickets")

FULL_DECK_COUNTS = {
    "W": 12,
    "B": 12,
    "U": 12,
    "G": 12,
    "Y": 12,
    "O": 12,
    "R": 12,
    "P": 12,
    "L": 14,
}
ROUTE_POINTS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 10, 6: 15, 7: 18, 8: 21}


_GLOBAL_FEATURES = (
    "bias",
    "turn_number_norm",
    "score_norm",
    "score_diff_vs_leader_norm",
    "trains_remaining_norm",
    "hand_total_norm",
    "locomotives_norm",
    "train_deck_norm",
    "ticket_deck_norm",
    "pending_ticket_count_norm",
    "pending_ticket_value_norm",
    "completed_ticket_count_norm",
    "completed_ticket_value_norm",
    "impossible_ticket_count_norm",
    "impossible_ticket_value_norm",
    "opponent_best_score_gap_norm",
    "opponent_min_trains_norm",
    "opponent_max_hand_norm",
    "phase_early",
    "phase_mid",
    "phase_late",
)

_CLAIM_FEATURES = (
    "claim_route_length_norm",
    "claim_route_points_norm",
    "claim_locomotives_spent_norm",
    "claim_cards_spent_norm",
    "claim_hand_surplus_norm",
    "claim_hand_deficit_norm",
    "claim_is_gray",
    "claim_is_double",
    "claim_is_ferry",
    "claim_is_tunnel",
    "claim_touches_own_network",
    "claim_connects_own_components",
    "claim_completes_ticket_count_norm",
    "claim_completes_ticket_value_norm",
    "claim_ticket_distance_reduction_norm",
    "claim_route_pressure_norm",
    "claim_opponent_endpoint_touch",
    "claim_cost_component_count_norm",
    "claim_cost_option_set_count_norm",
    "claim_cost_grey_spaces_norm",
    "claim_cost_required_locomotive_spaces_norm",
    "claim_cost_distinct_real_colors_norm",
    "claim_cost_declared_real_color_options_norm",
)

_DRAW_FEATURES = (
    "draw_is_blind",
    "draw_is_face_up",
    "draw_is_locomotive",
    "draw_matches_needed_color",
    "draw_visible_color_count_norm",
    "draw_hand_color_count_norm",
    "draw_estimated_useful_probability",
    "draw_unknown_color_probability",
)

_DRAW_TICKET_FEATURES = (
    "draw_tickets_deck_norm",
    "draw_tickets_pending_count_norm",
    "draw_tickets_pending_value_norm",
    "draw_tickets_all_current_complete",
    "draw_tickets_trains_remaining_norm",
    "draw_tickets_score_position_norm",
)

_KEEP_FEATURES = (
    "keep_count_norm",
    "keep_total_value_norm",
    "keep_min_distance_norm",
    "keep_mean_distance_norm",
    "keep_max_distance_norm",
    "keep_value_per_distance_norm",
    "keep_endpoint_overlap_norm",
    "keep_pair_overlap_norm",
    "keep_already_connected_norm",
    "keep_impossible_by_trains_norm",
)

_FEATURE_NAMES = (
    _GLOBAL_FEATURES
    + tuple(f"decision_{name}" for name in DECISION_TYPES)
    + tuple(f"action_{name}" for name in ACTION_TYPES)
    + tuple(f"hand_{color}_norm" for color in CARD_COLORS)
    + tuple(f"market_{color}_norm" for color in CARD_COLORS)
    + tuple(f"discard_{color}_norm" for color in CARD_COLORS)
    + tuple(f"claim_route_color_{color}" for color in ROUTE_COLORS)
    + _CLAIM_FEATURES
    + tuple(f"claim_cost_eligible_{color}_spaces_norm" for color in TRAIN_COLORS)
    + tuple(f"draw_card_color_{color}" for color in CARD_COLORS)
    + _DRAW_FEATURES
    + _DRAW_TICKET_FEATURES
    + _KEEP_FEATURES
)


def feature_names() -> list[str]:
    """Return the stable feature schema used by training and live inference."""
    return list(_FEATURE_NAMES)


@dataclass(frozen=True)
class RouteInfo:
    city1: str
    city2: str
    length: int
    color: str
    route_id: str
    locomotives: int = 0
    is_tunnel: bool = False
    is_double: bool = False
    cost: tuple[CostComponent, ...] = ()

    @property
    def points(self) -> int:
        return ROUTE_POINTS.get(self.length, self.length)

    @property
    def sibling_key(self) -> tuple[tuple[str, str], int]:
        return (tuple(sorted((self.city1, self.city2))), self.length)


class _UnionFind:
    def __init__(self, items: Iterable[str] = ()) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        parent = self._parent[item]
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self._parent[root_left] = root_right

    def connected(self, left: str, right: str) -> bool:
        return self.find(left) == self.find(right)


class MapTopology:
    def __init__(self, routes: list[RouteInfo]) -> None:
        self.routes = routes
        self.routes_by_id = {route.route_id: route for route in routes}
        self.cities = sorted({city for route in routes for city in (route.city1, route.city2)})
        self.siblings_by_key: dict[tuple[tuple[str, str], int], list[RouteInfo]] = defaultdict(list)
        for route in routes:
            self.siblings_by_key[route.sibling_key].append(route)

    def siblings(self, route: RouteInfo) -> list[RouteInfo]:
        return [candidate for candidate in self.siblings_by_key[route.sibling_key] if candidate.route_id != route.route_id]

    def route_claimable_by(self, route: RouteInfo, claimed_by: dict[str, str | None],
                           player_id: str | None, player_count: int) -> bool:
        owner = claimed_by.get(route.route_id)
        if owner is not None:
            return False
        siblings = self.siblings(route)
        if player_id is not None and any(claimed_by.get(sibling.route_id) == player_id for sibling in siblings):
            return False
        if player_count <= 3 and any(claimed_by.get(sibling.route_id) is not None for sibling in siblings):
            return False
        return True

    def components_for(self, claimed_by: dict[str, str | None], player_id: str | None) -> tuple[_UnionFind, set[str]]:
        components = _UnionFind(self.cities)
        owned_cities: set[str] = set()
        if not player_id:
            return components, owned_cities
        for route in self.routes:
            if claimed_by.get(route.route_id) == player_id:
                components.union(route.city1, route.city2)
                owned_cities.update((route.city1, route.city2))
        return components, owned_cities

    def shortest_cost(
        self,
        claimed_by: dict[str, str | None],
        player_id: str | None,
        city1: str,
        city2: str,
        *,
        player_count: int,
        forced_owned: set[str] | None = None,
        blocked: set[str] | None = None,
    ) -> int | None:
        if city1 not in self.cities or city2 not in self.cities:
            return None
        forced_owned = forced_owned or set()
        blocked = blocked or set()
        components, _ = self.components_for(claimed_by, player_id)
        if city1 == city2 or components.connected(city1, city2):
            return 0

        adjacency: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for route in self.routes:
            if route.route_id in blocked and route.route_id not in forced_owned:
                continue
            owner = claimed_by.get(route.route_id)
            if route.route_id in forced_owned or owner == player_id:
                weight = 0
            elif owner is not None:
                continue
            else:
                if not self.route_claimable_by(route, claimed_by, player_id, player_count):
                    continue
                weight = route.length
            adjacency[route.city1].append((route.city2, weight))
            adjacency[route.city2].append((route.city1, weight))

        best = {city1: 0}
        frontier = [(0, city1)]
        while frontier:
            cost, city = heapq.heappop(frontier)
            if city == city2:
                return cost
            if cost > best.get(city, cost):
                continue
            for neighbor, length in adjacency.get(city, ()):
                next_cost = cost + length
                if next_cost < best.get(neighbor, next_cost + 1):
                    best[neighbor] = next_cost
                    heapq.heappush(frontier, (next_cost, neighbor))
        return None


@lru_cache(maxsize=None)
def _load_topology(map_name: str) -> MapTopology:
    name = map_name or "classic"
    path = MAPS_DIR / f"{name}.csv"
    if not path.exists():
        raise ValueError(f"Unknown map '{name}' at {path}")

    with path.open(newline="") as csvfile:
        raw_rows = list(csv.DictReader(csvfile))

    group_totals: Counter[tuple[tuple[str, str], int]] = Counter()
    for row in raw_rows:
        key = (tuple(sorted((row["city1"], row["city2"]))), int(row["Distance"]))
        group_totals[key] += 1

    group_seen: Counter[tuple[tuple[str, str], int]] = Counter()
    routes: list[RouteInfo] = []
    for row in raw_rows:
        city1 = row["city1"]
        city2 = row["city2"]
        length = int(row["Distance"])
        key = (tuple(sorted((city1, city2))), length)
        group_seen[key] += 1
        route_id = f"{city1.replace(' ', '_')}-{city2.replace(' ', '_')}-{group_seen[key]}"
        locomotives = int(row.get("Locomotives") or 0)
        tunnel_raw = (row.get("Tunnel") or "").strip().lower()
        cost_spec = (row.get("Cost") or "").strip()
        cost = (parse_cost(cost_spec, length) if cost_spec
                else synthesize_cost(length, row["Color"]))
        routes.append(
            RouteInfo(
                city1=city1,
                city2=city2,
                length=length,
                color=row["Color"],
                route_id=route_id,
                locomotives=locomotives,
                is_tunnel=tunnel_raw in {"1", "true", "yes"},
                is_double=group_totals[key] > 1,
                cost=cost,
            )
        )
    return MapTopology(routes)


def state_from_view(view: Any) -> dict[str, Any]:
    """Convert a live PlayerView to the same symbolic state used by exports."""
    tickets = []
    for ticket in getattr(view, "tickets", []) or []:
        tickets.append({
            "city1": getattr(ticket, "city1"),
            "city2": getattr(ticket, "city2"),
            "value": getattr(ticket, "value"),
            "completed": bool(getattr(ticket, "is_completed", False)),
            "impossible": bool(getattr(ticket, "is_impossible", False)),
        })

    offer = []
    for ticket in getattr(view, "ticket_offer", None) or []:
        offer.append({
            "city1": getattr(ticket, "city1"),
            "city2": getattr(ticket, "city2"),
            "value": getattr(ticket, "value"),
        })

    opponents = []
    for opponent in getattr(view, "opponents", []) or []:
        opponents.append({
            "player_id": getattr(opponent, "player_id"),
            "exposed": dict(getattr(opponent, "exposed_hand", {}) or {}),
            "hand_count": int(getattr(opponent, "num_cards_in_hand", 0) or 0),
            "trains": int(getattr(opponent, "remaining_trains", 0) or 0),
            "score": int(getattr(opponent, "score", 0) or 0),
            "ticket_count": int(getattr(opponent, "destination_ticket_count", 0) or 0),
        })

    return {
        "player": getattr(view, "player_id", None),
        "decision": getattr(view, "decision", "turn"),
        "map_name": getattr(view, "map_name", "classic"),
        "player_count": int(getattr(view, "player_count", 2) or 2),
        "turn_number": int(getattr(view, "turn_number", 0) or 0),
        "score": int(getattr(view, "score", 0) or 0),
        "trains_remaining": int(getattr(view, "trains_remaining", 0) or 0),
        "hand": dict(getattr(view, "hand", {}) or {}),
        "tickets": tickets,
        "market": list(getattr(view, "face_up_cards", []) or []),
        "discard": dict(getattr(view, "discard_pile", {}) or {}),
        "train_cards_in_deck": int(getattr(view, "train_cards_in_deck", 0) or 0),
        "tickets_in_deck": int(getattr(view, "tickets_in_deck", 0) or 0),
        "claimed_by": dict(getattr(view, "claimed_by", {}) or {}),
        "opponents": opponents,
        "ticket_offer": offer or None,
    }


def actions_to_dicts(legal_actions: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert engine action dataclasses or dicts to the exported action shape."""
    rows = []
    for action in legal_actions:
        if isinstance(action, dict):
            row = dict(action)
        elif is_dataclass(action):
            row = {"type": type(action).__name__, **asdict(action)}
        else:
            row = {"type": type(action).__name__}
            row.update(getattr(action, "__dict__", {}))
        if "indices" in row:
            row["indices"] = list(row["indices"])
        rows.append(row)
    return rows


def chosen_action_index(row: dict[str, Any]) -> int | None:
    """Return the chosen action's index in a DecisionRecord legal menu."""
    chosen = _canonical_action(row.get("chosen"))
    for index, action in enumerate(row.get("legal_actions", ())):
        if _canonical_action(action) == chosen:
            return index
    return None


def build_action_feature_rows(row_or_state: dict[str, Any],
                              legal_action_dicts: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Build one feature row for each legal action in a decision menu."""
    state, decision, player_id = _state_and_meta(row_or_state)
    map_name = str(state.get("map_name") or "classic")
    player_count = int(state.get("player_count") or 2)
    claimed_by = {str(route_id): owner for route_id, owner in (state.get("claimed_by") or {}).items()}
    topology = _load_topology(map_name)
    tickets = list(state.get("tickets") or [])
    pending_tickets = [ticket for ticket in tickets if not _truthy(ticket.get("completed")) and not _truthy(ticket.get("impossible"))]
    completed_tickets = [ticket for ticket in tickets if _truthy(ticket.get("completed"))]
    impossible_tickets = [ticket for ticket in tickets if _truthy(ticket.get("impossible"))]
    hand = Counter({color: int(count or 0) for color, count in (state.get("hand") or {}).items()})
    market = Counter(state.get("market") or [])
    discard = Counter({color: int(count or 0) for color, count in (state.get("discard") or {}).items()})
    unknown_pool = _unknown_pool(state, hand, market, discard)
    needed_colors = _needed_colors(topology, state, player_id, pending_tickets, claimed_by)

    base = _empty_row()
    _apply_global_features(
        base,
        state=state,
        decision=decision,
        hand=hand,
        market=market,
        discard=discard,
        pending_tickets=pending_tickets,
        completed_tickets=completed_tickets,
        impossible_tickets=impossible_tickets,
    )

    rows = []
    for action in legal_action_dicts:
        features = dict(base)
        action_type = str(action.get("type") or "")
        if f"action_{action_type}" in features:
            features[f"action_{action_type}"] = 1.0
        if action_type == "ClaimRoute":
            _apply_claim_features(
                features,
                action=action,
                topology=topology,
                state=state,
                player_id=player_id,
                player_count=player_count,
                claimed_by=claimed_by,
                hand=hand,
                pending_tickets=pending_tickets,
            )
        elif action_type in {"DrawBlind", "DrawFaceUp"}:
            _apply_draw_features(
                features,
                action=action,
                hand=hand,
                market=market,
                unknown_pool=unknown_pool,
                needed_colors=needed_colors,
            )
        elif action_type == "DrawTickets":
            _apply_draw_ticket_features(features, state=state, pending_tickets=pending_tickets)
        elif action_type == "KeepTickets":
            _apply_keep_features(
                features,
                action=action,
                topology=topology,
                state=state,
                player_id=player_id,
                player_count=player_count,
                claimed_by=claimed_by,
                current_tickets=tickets,
            )
        rows.append(features)
    return rows


def vectorize(rows: list[dict[str, float]], names: list[str] | tuple[str, ...] | None = None):
    """Return a NumPy matrix for rows, importing NumPy lazily."""
    import numpy as np

    columns = list(names or _FEATURE_NAMES)
    return np.asarray([[float(row.get(name, 0.0)) for name in columns] for row in rows], dtype=np.float32)


def _state_and_meta(row_or_state: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    if "state" in row_or_state:
        state = dict(row_or_state["state"] or {})
        decision = str(row_or_state.get("decision") or state.get("decision") or "turn")
        player_id = row_or_state.get("player") or state.get("player") or state.get("player_id")
    else:
        state = dict(row_or_state or {})
        decision = str(state.get("decision") or "turn")
        player_id = state.get("player") or state.get("player_id")
    return state, decision, str(player_id) if player_id is not None else None


def _empty_row() -> dict[str, float]:
    return {name: 0.0 for name in _FEATURE_NAMES}


def _apply_global_features(
    features: dict[str, float],
    *,
    state: dict[str, Any],
    decision: str,
    hand: Counter,
    market: Counter,
    discard: Counter,
    pending_tickets: list[dict[str, Any]],
    completed_tickets: list[dict[str, Any]],
    impossible_tickets: list[dict[str, Any]],
) -> None:
    opponents = list(state.get("opponents") or [])
    score = int(state.get("score") or 0)
    opponent_scores = [int(opponent.get("score") or 0) for opponent in opponents]
    leader_score = max([score, *opponent_scores]) if opponent_scores else score
    best_opponent = max(opponent_scores) if opponent_scores else score
    turn_number = int(state.get("turn_number") or 0)
    trains_remaining = int(state.get("trains_remaining") or 0)

    features["bias"] = 1.0
    if f"decision_{decision}" in features:
        features[f"decision_{decision}"] = 1.0
    features["turn_number_norm"] = _norm(turn_number, 120)
    features["score_norm"] = _norm(score, 200)
    features["score_diff_vs_leader_norm"] = _signed_norm(score - leader_score, 100)
    features["trains_remaining_norm"] = _norm(trains_remaining, 45)
    features["hand_total_norm"] = _norm(sum(hand.values()), 80)
    features["locomotives_norm"] = _norm(hand.get("L", 0), 14)
    features["train_deck_norm"] = _norm(int(state.get("train_cards_in_deck") or 0), 110)
    features["ticket_deck_norm"] = _norm(int(state.get("tickets_in_deck") or 0), 40)
    features["pending_ticket_count_norm"] = _norm(len(pending_tickets), 10)
    features["pending_ticket_value_norm"] = _norm(_ticket_value(pending_tickets), 100)
    features["completed_ticket_count_norm"] = _norm(len(completed_tickets), 10)
    features["completed_ticket_value_norm"] = _norm(_ticket_value(completed_tickets), 100)
    features["impossible_ticket_count_norm"] = _norm(len(impossible_tickets), 10)
    features["impossible_ticket_value_norm"] = _norm(_ticket_value(impossible_tickets), 100)
    features["opponent_best_score_gap_norm"] = _signed_norm(score - best_opponent, 100)
    features["opponent_min_trains_norm"] = _norm(min((int(o.get("trains") or 0) for o in opponents), default=45), 45)
    features["opponent_max_hand_norm"] = _norm(max((int(o.get("hand_count") or 0) for o in opponents), default=0), 80)

    if trains_remaining >= 35 and turn_number < 35:
        features["phase_early"] = 1.0
    elif trains_remaining <= 15 or turn_number >= 80:
        features["phase_late"] = 1.0
    else:
        features["phase_mid"] = 1.0

    for color in CARD_COLORS:
        features[f"hand_{color}_norm"] = _norm(hand.get(color, 0), FULL_DECK_COUNTS[color])
        features[f"market_{color}_norm"] = _norm(market.get(color, 0), 5)
        features[f"discard_{color}_norm"] = _norm(discard.get(color, 0), FULL_DECK_COUNTS[color])


def _apply_claim_features(
    features: dict[str, float],
    *,
    action: dict[str, Any],
    topology: MapTopology,
    state: dict[str, Any],
    player_id: str | None,
    player_count: int,
    claimed_by: dict[str, str | None],
    hand: Counter,
    pending_tickets: list[dict[str, Any]],
) -> None:
    route = topology.routes_by_id.get(str(action.get("route_id") or ""))
    if route is None:
        return

    spent_locomotives = int(action.get("locomotives") or 0)
    spent_cards = route.length
    spend_color = str(action.get("color") or route.color)
    color_count = hand.get(spend_color, 0) if spend_color != "L" else hand.get("L", 0)
    needed_color_cards = 0 if spend_color == "L" else route.length - spent_locomotives
    surplus = color_count - needed_color_cards

    features[f"claim_route_color_{route.color}"] = 1.0
    features["claim_route_length_norm"] = _norm(route.length, 8)
    features["claim_route_points_norm"] = _norm(route.points, 21)
    features["claim_locomotives_spent_norm"] = _norm(spent_locomotives, max(1, route.length))
    features["claim_cards_spent_norm"] = _norm(spent_cards, 8)
    features["claim_hand_surplus_norm"] = _signed_norm(surplus, 8)
    features["claim_hand_deficit_norm"] = _norm(max(0, -surplus), 8)
    features["claim_is_gray"] = 1.0 if route.color == "X" else 0.0
    features["claim_is_double"] = 1.0 if route.is_double else 0.0
    features["claim_is_ferry"] = 1.0 if route.locomotives > 0 else 0.0
    features["claim_is_tunnel"] = 1.0 if route.is_tunnel else 0.0
    cost = route.cost or synthesize_cost(route.length, route.color)
    option_sets = sum(1 for component in cost if len(component.options) > 1)
    grey_spaces = sum(component.count for component in cost if component.is_grey())
    locomotive_spaces = sum(component.count for component in cost
                            if component.is_locomotive())
    real_colors = {
        color for component in cost
        if not (component.is_grey() or component.is_locomotive())
        for color in component.options
    }
    declared_options = sum(
        len(component.options) for component in cost
        if not (component.is_grey() or component.is_locomotive())
    )
    features["claim_cost_component_count_norm"] = _norm(len(cost), 8)
    features["claim_cost_option_set_count_norm"] = _norm(option_sets, 8)
    features["claim_cost_grey_spaces_norm"] = _norm(grey_spaces, 8)
    features["claim_cost_required_locomotive_spaces_norm"] = _norm(locomotive_spaces, 8)
    features["claim_cost_distinct_real_colors_norm"] = _norm(len(real_colors), 8)
    features["claim_cost_declared_real_color_options_norm"] = _norm(declared_options, 64)
    eligible_spaces = Counter()
    for component in cost:
        if component.is_locomotive():
            continue
        for color in component.concrete_options():
            eligible_spaces[color] += component.count
    for color in TRAIN_COLORS:
        features[f"claim_cost_eligible_{color}_spaces_norm"] = _norm(
            eligible_spaces[color], 8)

    components, owned_cities = topology.components_for(claimed_by, player_id)
    touches = route.city1 in owned_cities or route.city2 in owned_cities
    connects = touches and not components.connected(route.city1, route.city2)
    features["claim_touches_own_network"] = 1.0 if touches else 0.0
    features["claim_connects_own_components"] = 1.0 if connects else 0.0
    features["claim_opponent_endpoint_touch"] = 1.0 if _opponent_endpoint_touch(topology, claimed_by, player_id, route) else 0.0

    reduction = 0.0
    completed_count = 0
    completed_value = 0
    pressure = 0.0
    for ticket in pending_tickets:
        before = _ticket_distance(topology, claimed_by, player_id, player_count, ticket)
        after = _ticket_distance(topology, claimed_by, player_id, player_count, ticket, forced_owned={route.route_id})
        blocked = _ticket_distance(topology, claimed_by, player_id, player_count, ticket, blocked={route.route_id})
        if before is not None and after is not None:
            reduction += max(0, before - after)
        elif before is None and after is not None:
            reduction += max(0, 20 - after)
        if after == 0 and before != 0:
            completed_count += 1
            completed_value += int(ticket.get("value") or 0)
        if before is not None:
            pressure += (20 - before) if blocked is None else max(0, blocked - before)

    features["claim_completes_ticket_count_norm"] = _norm(completed_count, 5)
    features["claim_completes_ticket_value_norm"] = _norm(completed_value, 50)
    features["claim_ticket_distance_reduction_norm"] = _norm(reduction, 30)
    features["claim_route_pressure_norm"] = _norm(pressure, 30)


def _apply_draw_features(
    features: dict[str, float],
    *,
    action: dict[str, Any],
    hand: Counter,
    market: Counter,
    unknown_pool: Counter,
    needed_colors: Counter,
) -> None:
    action_type = str(action.get("type") or "")
    color = str(action.get("card") or "")
    unknown_total = sum(unknown_pool.values())
    useful_colors = {color for color, score in needed_colors.items() if score > 0}
    if useful_colors:
        useful_colors.add("L")

    if action_type == "DrawBlind":
        features["draw_is_blind"] = 1.0
        useful_unknown = sum(unknown_pool.get(color, 0) for color in useful_colors)
        features["draw_estimated_useful_probability"] = useful_unknown / unknown_total if unknown_total else 0.0
        features["draw_unknown_color_probability"] = 1.0 if unknown_total else 0.0
        return

    features["draw_is_face_up"] = 1.0
    if color in CARD_COLORS:
        features[f"draw_card_color_{color}"] = 1.0
    features["draw_is_locomotive"] = 1.0 if color == "L" else 0.0
    features["draw_matches_needed_color"] = 1.0 if color in useful_colors else 0.0
    features["draw_visible_color_count_norm"] = _norm(market.get(color, 0), 5)
    features["draw_hand_color_count_norm"] = _norm(hand.get(color, 0), FULL_DECK_COUNTS.get(color, 12))
    features["draw_estimated_useful_probability"] = 1.0 if color in useful_colors else 0.0
    features["draw_unknown_color_probability"] = (
        unknown_pool.get(color, 0) / unknown_total if unknown_total and color in CARD_COLORS else 0.0
    )


def _apply_draw_ticket_features(features: dict[str, float], *,
                                state: dict[str, Any],
                                pending_tickets: list[dict[str, Any]]) -> None:
    trains_remaining = int(state.get("trains_remaining") or 0)
    score = int(state.get("score") or 0)
    opponent_scores = [int(opponent.get("score") or 0) for opponent in (state.get("opponents") or [])]
    leader_score = max([score, *opponent_scores]) if opponent_scores else score

    features["draw_tickets_deck_norm"] = _norm(int(state.get("tickets_in_deck") or 0), 40)
    features["draw_tickets_pending_count_norm"] = _norm(len(pending_tickets), 10)
    features["draw_tickets_pending_value_norm"] = _norm(_ticket_value(pending_tickets), 100)
    features["draw_tickets_all_current_complete"] = 1.0 if not pending_tickets else 0.0
    features["draw_tickets_trains_remaining_norm"] = _norm(trains_remaining, 45)
    features["draw_tickets_score_position_norm"] = _signed_norm(score - leader_score, 100)


def _apply_keep_features(
    features: dict[str, float],
    *,
    action: dict[str, Any],
    topology: MapTopology,
    state: dict[str, Any],
    player_id: str | None,
    player_count: int,
    claimed_by: dict[str, str | None],
    current_tickets: list[dict[str, Any]],
) -> None:
    offer = list(state.get("ticket_offer") or [])
    indices = [int(index) for index in (action.get("indices") or []) if int(index) < len(offer)]
    kept = [offer[index] for index in indices]
    if not kept:
        return

    trains_remaining = int(state.get("trains_remaining") or 0)
    distances = []
    value_per_distance = []
    already_connected = 0
    impossible = 0
    for ticket in kept:
        distance = _ticket_distance(topology, claimed_by, player_id, player_count, ticket)
        if distance == 0:
            already_connected += 1
        if distance is None or distance > trains_remaining:
            impossible += 1
        bounded = float(distance if distance is not None else max(trains_remaining + 1, 20))
        distances.append(bounded)
        value_per_distance.append(float(ticket.get("value") or 0) / max(1.0, bounded))

    current_endpoints = {
        city
        for ticket in current_tickets
        for city in (str(ticket.get("city1")), str(ticket.get("city2")))
    }
    kept_endpoints = [city for ticket in kept for city in (str(ticket.get("city1")), str(ticket.get("city2")))]
    endpoint_overlap = sum(1 for city in kept_endpoints if city in current_endpoints)
    endpoint_counts = Counter(kept_endpoints)
    pair_overlap = sum(count - 1 for count in endpoint_counts.values() if count > 1)

    features["keep_count_norm"] = _norm(len(kept), 3)
    features["keep_total_value_norm"] = _norm(_ticket_value(kept), 60)
    features["keep_min_distance_norm"] = _norm(min(distances), 30)
    features["keep_mean_distance_norm"] = _norm(sum(distances) / len(distances), 30)
    features["keep_max_distance_norm"] = _norm(max(distances), 30)
    features["keep_value_per_distance_norm"] = _norm(sum(value_per_distance) / len(value_per_distance), 4)
    features["keep_endpoint_overlap_norm"] = _norm(endpoint_overlap, max(1, 2 * len(kept)))
    features["keep_pair_overlap_norm"] = _norm(pair_overlap, max(1, len(kept)))
    features["keep_already_connected_norm"] = _norm(already_connected, len(kept))
    features["keep_impossible_by_trains_norm"] = _norm(impossible, len(kept))


def _needed_colors(
    topology: MapTopology,
    state: dict[str, Any],
    player_id: str | None,
    pending_tickets: list[dict[str, Any]],
    claimed_by: dict[str, str | None],
) -> Counter:
    if not pending_tickets:
        return Counter()
    player_count = int(state.get("player_count") or 2)
    trains_remaining = int(state.get("trains_remaining") or 0)
    need: Counter[str] = Counter()
    for route in topology.routes:
        if route.length > trains_remaining:
            continue
        if claimed_by.get(route.route_id) is not None:
            continue
        if not topology.route_claimable_by(route, claimed_by, player_id, player_count):
            continue
        route_reduction = 0
        for ticket in pending_tickets:
            before = _ticket_distance(topology, claimed_by, player_id, player_count, ticket)
            after = _ticket_distance(topology, claimed_by, player_id, player_count, ticket, forced_owned={route.route_id})
            if before is not None and after is not None:
                route_reduction += max(0, before - after)
            elif before is None and after is not None:
                route_reduction += max(0, 20 - after)
        if route_reduction <= 0:
            continue
        if route.color == "X":
            for color in TRAIN_COLORS:
                need[color] += route_reduction
        else:
            need[route.color] += route_reduction
    return need


def _unknown_pool(state: dict[str, Any], hand: Counter, market: Counter, discard: Counter) -> Counter:
    pool = Counter(FULL_DECK_COUNTS)
    pool.subtract(hand)
    pool.subtract(market)
    pool.subtract(discard)
    for opponent in state.get("opponents") or []:
        pool.subtract(opponent.get("exposed") or {})
    return +pool


def _ticket_distance(
    topology: MapTopology,
    claimed_by: dict[str, str | None],
    player_id: str | None,
    player_count: int,
    ticket: dict[str, Any],
    *,
    forced_owned: set[str] | None = None,
    blocked: set[str] | None = None,
) -> int | None:
    city1 = str(ticket.get("city1") or "")
    city2 = str(ticket.get("city2") or "")
    return topology.shortest_cost(
        claimed_by,
        player_id,
        city1,
        city2,
        player_count=player_count,
        forced_owned=forced_owned,
        blocked=blocked,
    )


def _opponent_endpoint_touch(
    topology: MapTopology,
    claimed_by: dict[str, str | None],
    player_id: str | None,
    route: RouteInfo,
) -> bool:
    endpoints = {route.city1, route.city2}
    for candidate in topology.routes:
        owner = claimed_by.get(candidate.route_id)
        if owner is not None and owner != player_id and endpoints.intersection((candidate.city1, candidate.city2)):
            return True
    return False


def _ticket_value(tickets: Iterable[dict[str, Any]]) -> int:
    return sum(int(ticket.get("value") or 0) for ticket in tickets)


def _canonical_action(action: Any) -> Any:
    if action is None:
        return None
    if is_dataclass(action):
        action = {"type": type(action).__name__, **asdict(action)}
    if isinstance(action, dict):
        return tuple(sorted((key, _canonical_action(value)) for key, value in action.items()))
    if isinstance(action, (list, tuple)):
        return tuple(_canonical_action(item) for item in action)
    return action


def _truthy(value: Any) -> bool:
    return bool(value)


def _norm(value: float | int, scale: float | int) -> float:
    if not scale:
        return 0.0
    return max(0.0, min(float(value) / float(scale), 1.0))


def _signed_norm(value: float | int, scale: float | int) -> float:
    if not scale:
        return 0.0
    return max(-1.0, min(float(value) / float(scale), 1.0))
