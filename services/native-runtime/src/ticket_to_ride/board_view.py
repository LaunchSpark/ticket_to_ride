"""Board-view builders: turn game state into renderable node/edge dicts.

This is the single source of truth for the display schema consumed by the
notebook RouteGraphWidget and served by the backend's board endpoints -
``applications/notebook_harness/rendering.py`` re-exports from here. Keeping
one implementation means a culled map reconstructed over the API is
byte-identical to one built inside a notebook.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List, Tuple

from ticket_to_ride.engine.state.map import CulledMap, MapGraph, Route

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

# Locomotive card color for market/odds displays. Routes never use this
# letter; teal is distinct from all eight route colors above.
LOCOMOTIVE_GRADIENT_STOPS: List[str] = [
    "red", "orange", "yellow", "green", "blue", "indigo", "violet",
]


def card_color_hex() -> 'Dict[str, str | Dict[str, List[str]]]':
    """Card-color letter -> hex for market/odds displays.

    Derived from the same _ROUTE_COLOR_HEX map the route graph renders from
    (minus gray "X", which is a route color, not a card), plus the
    locomotive. Change a color in _ROUTE_COLOR_HEX and every widget updates.
    """
    colors = {letter: hex_ for letter, hex_ in _ROUTE_COLOR_HEX.items() if letter != "X"}
    colors["L"] = {"stops": LOCOMOTIVE_GRADIENT_STOPS}
    return colors


def build_nodes(map_graph: MapGraph) -> List[Dict[str, Any]]:
    """Build node dicts, one per city on the map."""
    return [{"id": city, "name": city} for city in sorted(map_graph.cities())]


def claimed_by_from_turn_state(turn_state: Dict[str, Any]) -> Dict[str, str]:
    """Map route_id -> owning player_id for every route claimed as of this snapshot.

    `turn_state` is one serialized turn (GameLogSerializer.serialize_turn_state
    output, as recorded by loggers and stored by the match repository). The
    active player's own claimedRoutes plus every opponent's claimedRoutes
    together cover every player, so this is the complete board state at that
    turn.
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


def build_segments(route: Route) -> List[Dict[str, Any]]:
    """One renderer-neutral fill description per train space."""
    segments: List[Dict[str, Any]] = []
    for component in route.cost:
        if component.is_locomotive():
            entry = {"kind": "loco", "colors": LOCOMOTIVE_GRADIENT_STOPS}
        elif len(component.options) == 1:
            entry = {"kind": "solid", "colors": [
                _ROUTE_COLOR_HEX.get(component.options[0], "#999999")
            ]}
        else:
            entry = {"kind": "options", "colors": [
                _ROUTE_COLOR_HEX.get(color, "#999999")
                for color in component.options
            ]}
        segments.extend([entry] * component.count)
    return segments


def _city_pair_key(route: Route) -> Tuple[str, str]:
    return tuple(sorted((route.city1, route.city2)))


def _curvatures_for(
    routes: List[Route], pair_key: Callable[[Route], Tuple[str, str]]
) -> Dict[str, float]:
    """Assign a symmetric curvature offset to every route sharing an endpoint pair.

    A single route between two endpoints gets 0 (straight line). Routes that
    share an endpoint pair with others - parallel/double routes, or routes
    made parallel by contraction - get evenly spaced offsets centered on 0,
    so they bow apart instead of overlapping.
    """
    routes_by_pair: Dict[Tuple[str, str], List[Route]] = defaultdict(list)
    for route in routes:
        routes_by_pair[pair_key(route)].append(route)

    curvature_by_route_id: Dict[str, float] = {}
    for parallel_routes in routes_by_pair.values():
        count = len(parallel_routes)
        for index, route in enumerate(sorted(parallel_routes, key=lambda r: r.route_id)):
            curvature_by_route_id[route.route_id] = (index - (count - 1) / 2) * _PARALLEL_EDGE_CURVATURE_STEP
    return curvature_by_route_id


def _curvature_by_route_id(map_graph: MapGraph) -> Dict[str, float]:
    return _curvatures_for(map_graph.routes, _city_pair_key)


def build_culled_nodes(culled: CulledMap) -> List[Dict[str, Any]]:
    """Node dicts for a player's culled map; merged nodes read as "A + B"."""
    return [{"id": node, "name": node.replace("+", " + ")} for node in sorted(culled.nodes)]


def build_culled_edges(culled: CulledMap) -> List[Dict[str, Any]]:
    """Edge dicts for a player's culled map, same schema as build_edges.

    Every surviving route is by definition unclaimed and claimable by the
    viewpoint player, so claimedColor/claimedBy are always None. Contraction
    routinely makes previously separate routes parallel (they now join the
    same merged nodes), so curvature is regrouped by contracted endpoints.
    """
    curvature_by_route_id = _curvatures_for(
        culled.routes, lambda route: tuple(sorted(culled.endpoints(route)))
    )

    edges: List[Dict[str, Any]] = []
    for route in culled.routes:
        source, target = culled.endpoints(route)
        edges.append(
            {
                "id": route.route_id,
                "source": source,
                "target": target,
                "width": route.length,
                "color": _edge_color(route),
                "claimedColor": None,
                "curvature": curvature_by_route_id[route.route_id],
                "data": {
                    "length": route.length,
                    "color": route.color,
                    "claimedBy": None,
                    "segments": build_segments(route),
                },
            }
        )
    return edges


def build_edges(
    map_graph: MapGraph,
    claimed_by: Dict[str, str],
    player_colors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Build edge dicts, one per route.

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
                    "segments": build_segments(route),
                },
            }
        )
    return edges
