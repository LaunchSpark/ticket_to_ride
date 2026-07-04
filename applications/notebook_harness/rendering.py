from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from ticket_to_ride.engine.state.map import MapGraph, Route

# Curvature step between adjacent parallel edges, in force-graph's
# linkCurvature units (roughly: fraction of the edge's on-screen length that
# its midpoint bows out perpendicular to the straight line between cities).
_PARALLEL_EDGE_CURVATURE_STEP = 0.2

# Route.color letter codes -> a readable CSS color for unclaimed edges.
_ROUTE_COLOR_HEX: Dict[str, str] = {
    "R": "#d62728",
    "B": "#1f1f1f",
    "U": "#1f77b4",
    "G": "#2ca02c",
    "O": "#ff7f0e",
    "P": "#9467bd",
    "W": "#dddddd",
    "Y": "#f1c40f",
    "X": "#999999",
}


def build_nodes(map_graph: MapGraph) -> List[Dict[str, Any]]:
    """Build GraphWidget node dicts, one per city on the map."""
    return [{"id": city, "name": city} for city in sorted(map_graph.cities())]


def claimed_by_from_snapshot(turn_state: Dict[str, Any]) -> Dict[str, str]:
    """Map route_id -> owning player_id for every route claimed as of this snapshot.

    `turn_state` is one entry's `["turnState"]` from InMemoryGameLogger.snapshots.
    The active player's own claimedRoutes plus every opponent's claimedRoutes
    together cover every player, so this is the complete board state at that turn.
    """
    claimed_by: Dict[str, str] = {}

    player_entry = turn_state["player"]
    for claimed_route in player_entry["claimedRoutes"]:
        claimed_by[claimed_route["routeId"]] = player_entry["playerId"]

    for opponent in turn_state["opponents"]:
        for claimed_route in opponent["claimedRoutes"]:
            claimed_by[claimed_route["routeId"]] = opponent["playerId"]

    return claimed_by


def _edge_color(route: Route) -> str:
    return _ROUTE_COLOR_HEX.get(route.color, "#999999")


def _city_pair_key(route: Route) -> Tuple[str, str]:
    return tuple(sorted((route.city1, route.city2)))


def _curvature_by_route_id(map_graph: MapGraph) -> Dict[str, float]:
    """Assign a symmetric curvature offset to every route sharing a city pair.

    A single route between two cities gets 0 (straight line). Routes that
    share a city pair with others - parallel/double routes - get evenly
    spaced offsets centered on 0, so they bow apart instead of overlapping.
    """
    routes_by_pair: Dict[Tuple[str, str], List[Route]] = defaultdict(list)
    for route in map_graph.routes:
        routes_by_pair[_city_pair_key(route)].append(route)

    curvature_by_route_id: Dict[str, float] = {}
    for parallel_routes in routes_by_pair.values():
        count = len(parallel_routes)
        for index, route in enumerate(sorted(parallel_routes, key=lambda r: r.route_id)):
            curvature_by_route_id[route.route_id] = (index - (count - 1) / 2) * _PARALLEL_EDGE_CURVATURE_STEP
    return curvature_by_route_id


def build_edges(
    map_graph: MapGraph,
    claimed_by: Dict[str, str],
    player_colors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Build GraphWidget edge dicts, one per route.

    `color` is always the route's own base color; claiming a route never
    repaints it. Instead the owner's color rides along in `claimedColor`
    (None while unclaimed), which the widget draws as an inset marker inside
    each train space so the base color stays visible around it - keeping a
    black player's trains distinguishable from a black route. The
    authoritative length/base-color/owner live in each edge's `data` dict,
    separate from the rendering fields. Parallel routes between the same two
    cities get a `curvature` offset so they bow apart instead of overlapping.
    """
    curvature_by_route_id = _curvature_by_route_id(map_graph)

    edges: List[Dict[str, Any]] = []
    for route in map_graph.routes:
        owner = claimed_by.get(route.route_id)
        edges.append(
            {
                "id": route.route_id,
                "source": route.city1,
                "target": route.city2,
                "width": route.length,
                "color": _edge_color(route),
                "claimedColor": player_colors.get(owner) if owner is not None else None,
                "curvature": curvature_by_route_id[route.route_id],
                "data": {
                    "length": route.length,
                    "color": route.color,
                    "claimedBy": owner,
                },
            }
        )
    return edges
