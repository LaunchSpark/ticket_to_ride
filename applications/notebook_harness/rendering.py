from __future__ import annotations

from typing import Any, Dict, List

from ticket_to_ride.engine.state.map import MapGraph, Route

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


def _edge_color(route: Route, owner: 'str | None', player_colors: Dict[str, str]) -> str:
    if owner is not None:
        return player_colors.get(owner, _ROUTE_COLOR_HEX.get(route.color, "#999999"))
    return _ROUTE_COLOR_HEX.get(route.color, "#999999")


def build_edges(
    map_graph: MapGraph,
    claimed_by: Dict[str, str],
    player_colors: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Build GraphWidget edge dicts, one per route, colored by claim state.

    The authoritative length/base-color/owner live in each edge's `data` dict,
    separate from the rendering `width`/`color` fields.
    """
    edges: List[Dict[str, Any]] = []
    for route in map_graph.routes:
        owner = claimed_by.get(route.route_id)
        edges.append(
            {
                "id": route.route_id,
                "source": route.city1,
                "target": route.city2,
                "width": route.length,
                "color": _edge_color(route, owner, player_colors),
                "data": {
                    "length": route.length,
                    "color": route.color,
                    "claimedBy": owner,
                },
            }
        )
    return edges
