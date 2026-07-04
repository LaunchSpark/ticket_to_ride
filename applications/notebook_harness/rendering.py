"""Notebook-facing re-exports of the shared board-view builders.

The implementations live in ``ticket_to_ride.board_view`` so the backend's
board endpoints and the notebooks build the display schema from the same
code. ``claimed_by_from_snapshot`` is the harness's historical name for
``claimed_by_from_turn_state``.
"""

from __future__ import annotations

from ticket_to_ride.board_view import (
    build_culled_edges,
    build_culled_nodes,
    build_edges,
    build_nodes,
    claimed_by_from_turn_state,
    claimed_by_from_turn_state as claimed_by_from_snapshot,
)

__all__ = [
    "build_culled_edges",
    "build_culled_nodes",
    "build_edges",
    "build_nodes",
    "claimed_by_from_snapshot",
    "claimed_by_from_turn_state",
]
