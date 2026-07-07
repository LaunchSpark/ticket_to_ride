from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from ticket_to_ride.board_view import card_color_hex
from ticket_to_ride.engine.game import Game
from ticket_to_ride.engine.player import Player
from ticket_to_ride.engine.replay import record_of, replay_to_turn
from ticket_to_ride.engine.state.game_context import GameContext
from ticket_to_ride.engine.state.map import DEFAULT_MAP_NAME, available_maps, contract_map
from ticket_to_ride.engine.state.views import GlobalPrivateView, GlobalPublicView, PlayerView

from notebook_harness.in_memory_logger import InMemoryGameLogger
from notebook_harness.rendering import (
    build_culled_edges,
    build_culled_nodes,
    build_edges,
    build_nodes,
    claimed_by_from_snapshot,
)

_SEAT_COLORS = ["red", "blue", "green", "yellow", "black"]


def list_maps() -> List[str]:
    """Return the names of every map a notebook can play on."""
    return available_maps()


def available_bots() -> 'Dict[str, type]':
    """Display-name -> bot class for every bot notebook under integrations/external/bots.

    Discovery goes through the same BotLoader the backend uses (BOT_META +
    single BaseBot subclass per notebook). Notebooks that want their own
    freshly-edited class to win over the on-disk version can override that
    one entry after calling this.
    """
    from external.clients.bot_api.loader import BotLoader

    descriptors = BotLoader().load_bots().values()
    return {
        descriptor.metadata.name: descriptor.bot_class
        for descriptor in sorted(descriptors, key=lambda d: d.metadata.name.casefold())
    }


@dataclass
class HarnessGame:
    game: Game
    players: List[Player]
    logger: InMemoryGameLogger
    _market_games: Dict[int, Game] = field(default_factory=dict, repr=False)

    def play(self) -> None:
        """Run the game to completion, recording one snapshot per turn."""
        self.game.play()

    def snapshot_count(self) -> int:
        return len(self.logger.snapshots)

    def public_view(self) -> GlobalPublicView:
        """Live view of everything publicly observable: board, market, deck
        counts, scores, and each player's public info. Build once, query
        whenever — every accessor reads the current game state."""
        return self.game.public_view()

    def private_view(self) -> GlobalPrivateView:
        """The omniscient extension of public_view(): full hands and tickets
        per player. For notebook analysis only — never hand it to a bot."""
        return self.game.private_view()

    def roster(self) -> List[Dict[str, str]]:
        """Return one {id, name, color} dict per seat, in seating order.

        This is the shape PlayerListWidget's `players` trait expects.
        """
        return [
            {"id": player.player_id, "name": player.name, "color": player.color}
            for player in self.players
        ]

    def board_at(
        self, step_index: int, viewpoint: 'str | None' = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Return (nodes, edges) for the board as of the given recorded turn.

        With a `viewpoint` player id, returns that player's culled view
        instead: their claimed network contracted into merged nodes, showing
        only routes they could still claim as of that turn.
        """
        snapshot = self.logger.snapshots[step_index]
        map_graph = self.game.context.get_map()
        claimed_by = claimed_by_from_snapshot(snapshot["turnState"])

        if viewpoint is not None:
            culled = contract_map(map_graph.routes, map_graph.player_count, claimed_by, viewpoint)
            return build_culled_nodes(culled), build_culled_edges(culled)

        player_colors = {player.player_id: player.color for player in self.players}
        return build_nodes(map_graph), build_edges(map_graph, claimed_by, player_colors)

    def _replayed_game(self, step_index: int) -> Game:
        """Game state as of recorded step `step_index`, rebuilt by replaying
        the action log with the game's seed (and cached per step)."""
        game = self._market_games.get(step_index)
        if game is None:
            game = replay_to_turn(record_of(self.game), step_index)
            self._market_games[step_index] = game
        return game

    def market_at(self, step_index: int, viewpoint: 'str | None' = None) -> Dict[str, Any]:
        """Market payload for the InfoBarWidget as of the given recorded turn.

        Without a viewpoint the pie is the true draw-pile composition
        (spectator view). With a viewpoint player id it is that player's
        public-information unknown pool (draw pile + opponents' hidden
        cards) — the exact distribution PlayerView.draw_odds() gives bots.
        """
        replayed = self._replayed_game(step_index)
        deck = replayed.context.get_train_deck()

        if viewpoint is None:
            pie_counts = deck.deck_composition()
            pie_label = "Draw pile"
        else:
            view = PlayerView(viewpoint, replayed.context, replayed.players)
            pie_counts = view.unknown_pool()
            names = {p["id"]: p["name"] for p in self.roster()}
            pie_label = f"Unknown to {names.get(viewpoint, viewpoint)} (deck + hidden hands)"

        return {
            "face_up": deck.get_face_up(),
            "deck_count": len(deck),
            "discard_count": len(deck.get_discard_pile()),
            "pie": [
                {"color": color, "count": count}
                for color, count in sorted(pie_counts.items())
                if count > 0
            ],
            "pie_label": pie_label,
            "colors": card_color_hex(),
        }


def initialize_game(
    bots: List[Any],
    map_name: str = DEFAULT_MAP_NAME,
    round_number: int = 0,
    seed: 'int | None' = None,
) -> HarnessGame:
    """Build a HarnessGame seating one Player per bot instance, in order.

    `bots` are ActionBot/BaseBot instances, or anything implementing the
    legacy choose_*/select_* interface. The Nth bot becomes player "bot_N"
    with a distinct default color.

    Pass an int `seed` to make the whole game reproducible; leave None for
    a random one (the generated value lands on `game.context.seed`).
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

    context = GameContext(player_ids, map_name=map_name, seed=seed)
    logger = InMemoryGameLogger(players)
    game = Game(context, players, logger, round_number)

    return HarnessGame(game=game, players=players, logger=logger)
