from __future__ import annotations

import random
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

_HAND_LABELS = {
    "B": "black", "U": "blue", "G": "green", "L": "locomotive", "O": "orange",
    "P": "purple", "R": "red", "W": "white", "Y": "yellow",
}


def _hand_counts(hand: Dict[str, int]) -> Dict[str, int]:
    return {label: hand.get(code, 0) for code, label in _HAND_LABELS.items()}


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

    def _snapshot_rows(self, step_index: int) -> List[Dict[str, Any]]:
        state = self.logger.snapshots[step_index]["turnState"]
        return [state["player"], *state["opponents"]]

    def active_player_at(self, step_index: int) -> str:
        return self.logger.snapshots[step_index]["turnState"]["player"]["playerId"]

    def leaderboard_at(self, step_index: int) -> List[Dict[str, Any]]:
        meta = {entry["id"]: entry for entry in self.roster()}
        rows = sorted(self._snapshot_rows(step_index), key=lambda row: -row["score"])
        return [
            {
                "playerId": row["playerId"],
                "name": meta[row["playerId"]]["name"],
                "color": meta[row["playerId"]]["color"],
                "score": row["score"],
                "remainingTrains": row["remainingTrains"],
                "place": place,
            }
            for place, row in enumerate(rows, start=1)
        ]

    def stats_at(self, step_index: int) -> Dict[str, Dict[str, Any]]:
        """Omniscient per-player stats at a step: full hands come from the
        replayed game (snapshots only carry the active player's hand)."""
        replayed = self._replayed_game(step_index)
        routes = {row["playerId"]: len(row["claimedRoutes"]) for row in self._snapshot_rows(step_index)}
        scores = {row["playerId"]: row["score"] for row in self._snapshot_rows(step_index)}
        trains = {row["playerId"]: row["remainingTrains"] for row in self._snapshot_rows(step_index)}
        return {
            player.player_id: {
                "hand": _hand_counts(player.get_hand()),
                "hiddenCards": None,
                "score": scores[player.player_id],
                "remainingTrains": trains[player.player_id],
                "ticketCount": len(player.get_tickets()),
                "routeCount": routes.get(player.player_id, 0),
            }
            for player in replayed.players
        }

    def tickets_at(self, step_index: int, player_id: str) -> List[Dict[str, Any]]:
        replayed = self._replayed_game(step_index)
        view = PlayerView(player_id, replayed.context, replayed.players)
        results = []
        for ticket, cost in zip(view.tickets, view.ticket_costs()):
            if ticket.is_completed:
                status, short = "completed", 0
            elif cost is None:
                status, short = "cut_off", None
            else:
                status, short = "open", cost
            results.append(
                {"from": ticket.city1, "to": ticket.city2, "points": ticket.value,
                 "status": status, "trainsShort": short}
            )
        return results

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


@dataclass
class HarnessSeries:
    """A sequence of rounds: one fully-independent HarnessGame per round,
    same seats and map, seed derived as base_seed + round_index so every
    round is individually reproducible."""

    games: List[HarnessGame]

    def play(self) -> None:
        for game in self.games:
            game.play()

    def roster(self) -> List[Dict[str, str]]:
        return self.games[0].roster()

    def round_count(self) -> int:
        return len(self.games)

    def turn_count(self, round_index: int) -> int:
        return self.games[round_index].snapshot_count()

    def rounds_meta(self) -> List[Dict[str, int]]:
        return [
            {"roundNumber": index, "turnCount": game.snapshot_count()}
            for index, game in enumerate(self.games)
        ]

    def active_player_at(self, round_index: int, turn_index: int) -> str:
        return self.games[round_index].active_player_at(turn_index)

    def board_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None):
        return self.games[round_index].board_at(turn_index, viewpoint)

    def market_at(self, round_index: int, turn_index: int, viewpoint: 'str | None' = None):
        return self.games[round_index].market_at(turn_index, viewpoint)

    def leaderboard_at(self, round_index: int, turn_index: int):
        return self.games[round_index].leaderboard_at(turn_index)

    def stats_at(self, round_index: int, turn_index: int):
        return self.games[round_index].stats_at(turn_index)

    def tickets_at(self, round_index: int, turn_index: int, player_id: str):
        return self.games[round_index].tickets_at(turn_index, player_id)

    def aggregates(self) -> List[Dict[str, Any]]:
        meta = self.roster()
        scores: Dict[str, List[int]] = {entry["id"]: [] for entry in meta}
        wins: Dict[str, int] = {entry["id"]: 0 for entry in meta}
        for game in self.games:
            final = game.leaderboard_at(game.snapshot_count() - 1)
            for row in final:
                scores[row["playerId"]].append(row["score"])
            wins[final[0]["playerId"]] += 1
        return [
            {
                "playerId": entry["id"],
                "name": entry["name"],
                "color": entry["color"],
                "scores": scores[entry["id"]],
                "averageScore": round(sum(scores[entry["id"]]) / len(scores[entry["id"]]), 1),
                "bestScore": max(scores[entry["id"]]),
                "wins": wins[entry["id"]],
            }
            for entry in meta
        ]


def initialize_series(
    bot_classes: List[type],
    map_name: str = DEFAULT_MAP_NAME,
    rounds: int = 1,
    seed: 'int | None' = None,
) -> HarnessSeries:
    """Build one unplayed HarnessGame per round from bot *classes* (a fresh
    instance per seat per round, so bot state never leaks across rounds)."""
    if rounds < 1:
        raise ValueError("initialize_series requires at least one round.")
    base_seed = seed if seed is not None else random.randrange(2**32)
    games = [
        initialize_game(
            [bot_class() for bot_class in bot_classes],
            map_name=map_name,
            round_number=round_index,
            seed=base_seed + round_index,
        )
        for round_index in range(rounds)
    ]
    return HarnessSeries(games=games)
