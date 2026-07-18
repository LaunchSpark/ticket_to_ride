from __future__ import annotations

"""
Own replay/log persistence bridging for the managed runtime.

This module is responsible for:
- adapting the repository/service layer to the GameLogger transport contract
- creating repository-backed replay loggers for managed matches
- keeping replay persistence details out of round orchestration

This module does not own:
- match sequencing
- round failover or clock behavior
- backend HTTP routes
"""

from typing import Any, Dict, Optional

from external.contracts.abstract_interface import Interface
from ticket_to_ride.backend.models import PlayerRecord
from ticket_to_ride.backend.repository import MatchRepository
from ticket_to_ride.backend.service import create_match, create_round, create_turn, finalize_match
from ticket_to_ride.backend.runtime.models import MatchExecutionContext
from ticket_to_ride.engine.player import Player
from ticket_to_ride.logging.game_logger import GameLogSerializer, GameLogger

DEFAULT_PLAYER_COLORS = ["red", "blue", "green", "yellow", "black"]


class RepositoryLoggerTransport:
    """Repository-backed transport that satisfies the GameLogger transport interface."""

    def __init__(self, repository: MatchRepository) -> None:
        self.repository = repository

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Persist replay logger requests through the repository/service layer."""

        payload = payload or {}

        if method == "POST" and path == "/matches":
            match_id = create_match(
                self.repository,
                name=payload["name"],
                players=[PlayerRecord.model_validate(player) for player in payload["players"]],
                player_names=list(payload.get("playerNames", [])),
                map_name=payload.get("mapName"),
                seed=payload.get("seed"),
            )
            return {"matchId": match_id}

        if method == "POST" and path.endswith("/finalize"):
            match_id = path.split("/")[2]
            average_scores = finalize_match(self.repository, match_id)
            return {"matchId": match_id, "status": "completed", "averageScores": [score.model_dump() for score in average_scores]}

        if method == "POST" and path.endswith("/rounds"):
            match_id = path.split("/")[2]
            round_id = create_round(self.repository, match_id, payload["roundNumber"])
            return {"roundId": round_id}

        if method == "POST" and "/turns" in path:
            match_id = path.split("/")[2]
            round_id = path.split("/")[4]
            turn_id = create_turn(
                self.repository,
                match_id=match_id,
                round_id=round_id,
                turn_index=payload["turnIndex"],
                turn_state=payload["turnState"],
            )
            return {"turnId": turn_id}

        raise ValueError(f"Unsupported repository transport request: {method} {path}")


def build_managed_replay_logger(repository: MatchRepository, match_context: MatchExecutionContext) -> GameLogger:
    """Create a repository-backed GameLogger for one managed match."""

    serializer = GameLogSerializer()
    transport = RepositoryLoggerTransport(repository)
    placeholder_players = [
        Player(
            seat.seatId,
            Interface(),
            _player_display_name(match_context, seat.primaryBotId, seat.seatId),
            _player_color(index),
        )
        for index, seat in enumerate(match_context.seats)
    ]
    return GameLogger(placeholder_players, transport=transport, serializer=serializer)


def _player_display_name(match_context: MatchExecutionContext, bot_id: str, seat_id: str) -> str:
    return f"{match_context.bot_names[bot_id]} [{seat_id}]"


def _player_color(index: int) -> str:
    return DEFAULT_PLAYER_COLORS[index % len(DEFAULT_PLAYER_COLORS)]
