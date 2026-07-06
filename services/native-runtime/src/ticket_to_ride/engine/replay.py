"""Deterministic replay: a (seed, action sequence) pair rebuilds a game.

record_of(game) captures the record after (or during) a game whose players
chose through the act() interface; replay_game(record) reconstructs the
identical final state by scripting those actions back through the engine
with the same RNG seed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import List, Tuple

from ticket_to_ride.engine.actions import (
    Action, ClaimRoute, DrawBlind, DrawFaceUp, DrawTickets, KeepTickets, Pass,
)
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext

_ACTION_TYPES = {
    cls.__name__: cls
    for cls in (Pass, DrawBlind, DrawFaceUp, ClaimRoute, DrawTickets, KeepTickets)
}


def action_to_dict(action: Action) -> dict:
    return {"type": type(action).__name__, **asdict(action)}


def action_from_dict(data: dict) -> Action:
    data = dict(data)
    cls = _ACTION_TYPES[data.pop("type")]
    if "indices" in data:
        data["indices"] = tuple(data["indices"])
    return cls(**data)


@dataclass
class GameRecord:
    seed: int
    map_name: str
    player_ids: List[str]
    actions: List[Tuple[str, Action]]

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "mapName": self.map_name,
            "playerIds": list(self.player_ids),
            "actions": [
                {"playerId": player_id, **action_to_dict(action)}
                for player_id, action in self.actions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameRecord":
        actions = []
        for row in data["actions"]:
            row = dict(row)
            player_id = row.pop("playerId")
            actions.append((player_id, action_from_dict(row)))
        return cls(
            seed=data["seed"],
            map_name=data["mapName"],
            player_ids=list(data["playerIds"]),
            actions=actions,
        )


class ScriptedBot:
    """Feeds back a recorded action stream; never consults the view."""

    def __init__(self, script: List[Action]):
        self._script = deque(script)

    def set_player(self, player):
        self.player = player

    def act(self, view, legal_actions):
        return self._script.popleft()


class _SilentLogger:
    def record_turn(self, *args, **kwargs):
        return None


def record_of(game: Game) -> GameRecord:
    context = game.context
    return GameRecord(
        seed=context.seed,
        map_name=context.get_map().map_name,
        player_ids=[p.player_id for p in game.players],
        actions=list(context.action_log),
    )


def replay_game(record: GameRecord) -> Game:
    scripts = {
        player_id: [a for owner, a in record.actions if owner == player_id]
        for player_id in record.player_ids
    }
    players = [
        Player(player_id, ScriptedBot(scripts[player_id]), player_id, "gray")
        for player_id in record.player_ids
    ]
    context = GameContext(record.player_ids, map_name=record.map_name, seed=record.seed)
    game = Game(context, players, _SilentLogger(), 0)
    game.play()
    return game
