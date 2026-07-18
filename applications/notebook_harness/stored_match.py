"""Series-protocol adapter for snapshot-only matches loaded from the API."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from urllib.request import Request, urlopen

from ticket_to_ride.board_view import card_color_hex
from ticket_to_ride.engine.state.map import DEFAULT_MAP_NAME, MapGraph, contract_map

from notebook_harness.rendering import (
    build_culled_edges,
    build_culled_nodes,
    build_edges,
    build_nodes,
    claimed_by_from_snapshot,
)

DEFAULT_API_BASE = "http://127.0.0.1:8000"


class StoredMatchSeries:
    """Expose a stored match payload through the notebook series protocol.

    Stored turns contain snapshots rather than a replayable action log. Board,
    scores, active-player details, and public opponent details are therefore
    available, while draw-pile odds and route-distance ticket analysis are not.
    """

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self._rounds: List[List[Dict[str, Any]]] = [
            list(round_record.get("turns", []))
            for round_record in payload.get("rounds", [])
        ]
        self._map_graph = MapGraph(
            player_count=len(payload["players"]),
            map_name=payload.get("mapName") or DEFAULT_MAP_NAME,
        )
        self._colors = {
            player["playerId"]: player["color"] for player in payload["players"]
        }

    def _turn(self, round_index: int, turn_index: int) -> Dict[str, Any]:
        return self._rounds[round_index][turn_index]

    def _rows(self, round_index: int, turn_index: int) -> List[Dict[str, Any]]:
        state = self._turn(round_index, turn_index)
        return [state["player"], *state["opponents"]]

    def roster(self) -> List[Dict[str, str]]:
        return [
            {
                "id": player["playerId"],
                "name": player["name"],
                "color": player["color"],
            }
            for player in self.payload["players"]
        ]

    def round_count(self) -> int:
        return len(self._rounds)

    def turn_count(self, round_index: int) -> int:
        return len(self._rounds[round_index])

    def rounds_meta(self) -> List[Dict[str, int]]:
        return [
            {"roundNumber": index, "turnCount": len(turns)}
            for index, turns in enumerate(self._rounds)
        ]

    def active_player_at(self, round_index: int, turn_index: int) -> str:
        return self._turn(round_index, turn_index)["player"]["playerId"]

    def board_at(
        self,
        round_index: int,
        turn_index: int,
        viewpoint: 'str | None' = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        claimed_by = claimed_by_from_snapshot(self._turn(round_index, turn_index))
        if viewpoint is not None:
            culled = contract_map(
                self._map_graph.routes,
                self._map_graph.player_count,
                claimed_by,
                viewpoint,
            )
            return build_culled_nodes(culled), build_culled_edges(culled)
        return (
            build_nodes(self._map_graph),
            build_edges(self._map_graph, claimed_by, self._colors),
        )

    def market_at(
        self,
        round_index: int,
        turn_index: int,
        viewpoint: 'str | None' = None,
    ) -> Dict[str, Any]:
        del viewpoint
        decks = self._turn(round_index, turn_index).get("gameObjects", {}).get(
            "decks", {}
        )
        return {
            "face_up": list(decks.get("marketCards", [])),
            "deck_count": None,
            "discard_count": None,
            "pie": [],
            "pie_label": "Unavailable for stored matches",
            "colors": card_color_hex(),
        }

    def leaderboard_at(
        self, round_index: int, turn_index: int
    ) -> List[Dict[str, Any]]:
        metadata = {entry["id"]: entry for entry in self.roster()}
        rows = sorted(
            self._rows(round_index, turn_index), key=lambda row: -row["score"]
        )
        return [
            {
                "playerId": row["playerId"],
                "name": metadata[row["playerId"]]["name"],
                "color": metadata[row["playerId"]]["color"],
                "score": row["score"],
                "remainingTrains": row["remainingTrains"],
                "place": place,
            }
            for place, row in enumerate(rows, start=1)
        ]

    def stats_at(
        self, round_index: int, turn_index: int
    ) -> Dict[str, Dict[str, Any]]:
        state = self._turn(round_index, turn_index)
        active = state["player"]
        stats: Dict[str, Dict[str, Any]] = {
            active["playerId"]: {
                "hand": dict(active["hand"]),
                "hiddenCards": None,
                "score": active["score"],
                "remainingTrains": active["remainingTrains"],
                "ticketCount": len(active["destinationTickets"]),
                "routeCount": len(active["claimedRoutes"]),
            }
        }
        for opponent in state["opponents"]:
            stats[opponent["playerId"]] = {
                "hand": dict(opponent["hand"]["public"]),
                "hiddenCards": opponent["hand"]["hidden"],
                "score": opponent["score"],
                "remainingTrains": opponent["remainingTrains"],
                "ticketCount": opponent["destinationTicketCount"],
                "routeCount": len(opponent["claimedRoutes"]),
            }
        return stats

    def tickets_at(
        self, round_index: int, turn_index: int, player_id: str
    ) -> List[Dict[str, Any]]:
        for turn in reversed(self._rounds[round_index][: turn_index + 1]):
            player = turn["player"]
            if player["playerId"] != player_id:
                continue
            return [
                {
                    "from": ticket["from"],
                    "to": ticket["to"],
                    "points": ticket["points"],
                    "status": "completed" if ticket["completed"] else "open",
                    "trainsShort": None,
                }
                for ticket in player["destinationTickets"]
            ]
        return []

    def aggregates(self) -> List[Dict[str, Any]]:
        metadata = self.roster()
        scores: Dict[str, List[int]] = {entry["id"]: [] for entry in metadata}
        wins: Dict[str, int] = {entry["id"]: 0 for entry in metadata}
        for round_index, turns in enumerate(self._rounds):
            if not turns:
                continue
            final = self.leaderboard_at(round_index, len(turns) - 1)
            for row in final:
                scores[row["playerId"]].append(row["score"])
            wins[final[0]["playerId"]] += 1
        return [
            {
                "playerId": entry["id"],
                "name": entry["name"],
                "color": entry["color"],
                "scores": scores[entry["id"]],
                "averageScore": round(
                    sum(scores[entry["id"]]) / max(len(scores[entry["id"]]), 1), 1
                ),
                "bestScore": max(scores[entry["id"]], default=0),
                "wins": wins[entry["id"]],
            }
            for entry in metadata
        ]


def _get_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def list_stored_matches(api_base: str = DEFAULT_API_BASE) -> List[Dict[str, Any]]:
    return _get_json(f"{api_base.rstrip('/')}/matches")


def load_stored_match(
    match_id: str, api_base: str = DEFAULT_API_BASE
) -> StoredMatchSeries:
    payload = _get_json(f"{api_base.rstrip('/')}/matches/{match_id}")
    return StoredMatchSeries(payload)
