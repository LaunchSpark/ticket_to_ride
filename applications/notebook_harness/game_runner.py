from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import DEFAULT_MAP_NAME, available_maps

from applications.notebook_harness.in_memory_logger import InMemoryGameLogger
from applications.notebook_harness.rendering import build_edges, build_nodes, claimed_by_from_snapshot

_SEAT_COLORS = ["red", "blue", "green", "yellow", "black"]


def list_maps() -> List[str]:
    """Return the names of every map a notebook can play on."""
    return available_maps()


@dataclass
class HarnessGame:
    game: Game
    players: List[Player]
    logger: InMemoryGameLogger

    def play(self) -> None:
        """Run the game to completion, recording one snapshot per turn."""
        self.game.play()

    def snapshot_count(self) -> int:
        return len(self.logger.snapshots)

    def board_at(self, step_index: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Return (nodes, edges) for the board as of the given recorded turn."""
        snapshot = self.logger.snapshots[step_index]
        map_graph = self.game.context.get_map()
        player_colors = {player.player_id: player.color for player in self.players}
        claimed_by = claimed_by_from_snapshot(snapshot["turnState"])

        return build_nodes(map_graph), build_edges(map_graph, claimed_by, player_colors)


def initialize_game(bots: List[Any], map_name: str = DEFAULT_MAP_NAME, round_number: int = 0) -> HarnessGame:
    """Build a HarnessGame seating one Player per bot instance, in order.

    `bots` are BaseBot instances (or anything implementing the same
    choose_*/select_* interface, like BootstrapRandomBot). The Nth bot
    becomes player "bot_N" with a distinct default color.
    """
    if not bots:
        raise ValueError("initialize_game requires at least one bot.")
    if len(bots) > len(_SEAT_COLORS):
        raise ValueError(f"initialize_game supports at most {len(_SEAT_COLORS)} seats.")

    player_ids = [f"bot_{index}" for index in range(len(bots))]
    players = [
        Player(
            player_ids[index],
            bots[index],
            getattr(bots[index], "name", None) or player_ids[index],
            _SEAT_COLORS[index],
        )
        for index in range(len(bots))
    ]

    context = GameContext(player_ids, map_name=map_name)
    logger = InMemoryGameLogger(players)
    game = Game(context, players, logger, round_number)

    return HarnessGame(game=game, players=players, logger=logger)
