from __future__ import annotations

from typing import Any, Dict, List, Optional

from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.player_context import PlayerContext
from ticket_to_ride.logging.game_logger import GameLogSerializer


class InMemoryGameLogger:
    """Records turn snapshots in memory instead of posting them to PocketBase.

    Satisfies the same `record_turn(round_number, context)` call that
    `Game.next_turn()` already makes on its logger, so it's a drop-in
    replacement for `GameLogger` with no engine changes required.
    """

    def __init__(self, players: List[Player], serializer: Optional[GameLogSerializer] = None) -> None:
        self.player_list = players
        self.serializer = serializer or GameLogSerializer()
        self.snapshots: List[Dict[str, Any]] = []

    def set_player_list(self, players: List[Player]) -> None:
        self.player_list = players

    def record_turn(self, round_number: int, context: PlayerContext) -> Dict[str, Any]:
        snapshot = {
            "roundNumber": round_number,
            "turnIndex": len(self.snapshots),
            "turnState": self.serializer.serialize_turn_state(self.player_list, context),
        }
        self.snapshots.append(snapshot)
        return snapshot
