from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ticket_to_ride.backend.bot_catalog import BotCatalogError
from ticket_to_ride.backend.bot_directory import BotDirectory, ConnectionStatus, DirectoryBot
from ticket_to_ride.backend.bot_scaffold import scaffold_bot
from ticket_to_ride.board_view import (
    build_culled_edges,
    build_culled_nodes,
    claimed_by_from_turn_state,
)
from ticket_to_ride.engine.state.map import MapGraph, contract_map
from ticket_to_ride.backend.models import (
    AverageScoreRecord,
    BotCreateResponse,
    BotEntry,
    BotListResponse,
    ConnectionCreateResponse,
    ConnectionSummary,
    MatchPayload,
    MatchSummary,
    NotebookLaunchResponse,
    PlayerRecord,
    RoundPayload,
)
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.repository import MatchRepository


class MatchNotFoundError(KeyError):
    """Raised when a requested match does not exist."""


class BotNotFoundError(LookupError):
    """Raised when a requested bot cannot be discovered."""


class ConnectionNotFoundError(LookupError):
    """Raised when a requested bot connection does not exist."""


def _bot_entry(bot: DirectoryBot) -> BotEntry:
    return BotEntry(
        botId=bot.bot_id,
        name=bot.name,
        version=bot.version,
        description=bot.description,
        author=bot.author,
        tags=list(bot.tags),
        source=bot.source,
        connectionId=bot.connection_id,
        baseUrl=bot.base_url,
    )


def _connection_summary(connection: ConnectionStatus) -> ConnectionSummary:
    return ConnectionSummary(
        connectionId=connection.connection_id,
        url=connection.url,
        status=connection.status,
        error=connection.error,
        botCount=connection.bot_count,
        createdAt=connection.created_at,
    )


def list_bot_directory(directory: BotDirectory) -> BotListResponse:
    listing = directory.list_all()
    return BotListResponse(
        bots=[_bot_entry(bot) for bot in listing.bots],
        connections=[_connection_summary(connection) for connection in listing.connections],
    )


def create_bot(directory: BotDirectory, notebook_launcher: NotebookLauncher, name: str) -> BotCreateResponse:
    existing = {bot.bot_id for bot in directory.list_all().bots if bot.source == "local"}
    scaffolded = scaffold_bot(name, existing_bot_ids=existing)
    url = notebook_launcher.launch(scaffolded.bot_id, scaffolded.path)
    return BotCreateResponse(botId=scaffolded.bot_id, url=url)


def add_bot_connection(
    repository: MatchRepository,
    directory: BotDirectory,
    url: str,
) -> ConnectionCreateResponse:
    normalized = url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Connection URL must be an http or https URL.")

    if any(record["url"] == normalized for record in repository.list_bot_connections()):
        raise ValueError("This connection is already registered.")

    try:
        remote_records = directory.remote_catalog_factory(normalized).list_bots()
    except BotCatalogError as exc:
        raise ValueError(f"Unable to reach a bot API at {normalized}: {exc}") from exc

    record = repository.create_bot_connection(normalized)
    connection = ConnectionSummary(
        connectionId=record["id"],
        url=record["url"],
        status="online",
        error=None,
        botCount=len(remote_records),
        createdAt=record["createdAt"],
    )
    bots = [
        BotEntry(
            botId=remote.bot_id,
            name=remote.name,
            version=remote.version,
            description=remote.description,
            author=remote.author,
            tags=list(remote.tags),
            source="remote",
            connectionId=record["id"],
            baseUrl=record["url"],
        )
        for remote in remote_records
    ]
    return ConnectionCreateResponse(connection=connection, bots=bots)


def remove_bot_connection(repository: MatchRepository, connection_id: str) -> None:
    try:
        repository.delete_bot_connection(connection_id)
    except KeyError as exc:
        raise ConnectionNotFoundError(f"Unknown bot connection '{connection_id}'.") from exc


def launch_notebook(
    directory: BotDirectory,
    notebook_launcher: NotebookLauncher,
    bot_id: str,
) -> NotebookLaunchResponse:
    requested_bot_id = bot_id.strip()
    if not requested_bot_id:
        raise ValueError("Bot ID is required.")

    try:
        bot = directory.resolve(requested_bot_id)
    except KeyError as exc:
        raise BotNotFoundError(f"Unknown bot '{requested_bot_id}'.") from exc

    if bot.source != "local" or not bot.module_path:
        raise ValueError("Only local bots have notebooks to open.")

    url = notebook_launcher.launch(bot.bot_id, bot.module_path)
    return NotebookLaunchResponse(botId=bot.bot_id, url=url)


def create_match(
    repository: MatchRepository,
    name: str,
    players: List[PlayerRecord],
    player_names: List[str] | None = None,
    map_name: str | None = None,
    seed: int | None = None,
) -> str:
    return repository.create_match(
        name=name,
        players=players,
        player_names=player_names,
        map_name=map_name,
        seed=seed,
    )


def create_round(repository: MatchRepository, match_id: str, round_number: int) -> str:
    return repository.create_round(match_id=match_id, round_number=round_number)


def create_turn(
    repository: MatchRepository,
    match_id: str,
    round_id: str,
    turn_index: int,
    turn_state: Dict[str, Any],
) -> str:
    turn_id = repository.create_turn(
        match_id=match_id,
        round_id=round_id,
        turn_index=turn_index,
        turn_state=turn_state,
    )
    match_payload = get_match(repository, match_id)
    average_scores = compute_average_scores(match_payload.players, match_payload.rounds)
    repository.update_match_progress(match_id, average_scores)
    return turn_id


def finalize_match(repository: MatchRepository, match_id: str) -> List[AverageScoreRecord]:
    match_payload = get_match(repository, match_id)
    average_scores = compute_average_scores(match_payload.players, match_payload.rounds)
    repository.update_match_progress(match_id, average_scores)
    repository.finalize_match(match_id, average_scores)
    return average_scores


def list_matches(repository: MatchRepository) -> List[MatchSummary]:
    return [
        MatchSummary(
            matchId=match["id"],
            name=match["name"],
            status=match["status"],
            playerCount=len(match.get("players", [])),
            playerNames=list(match.get("playerNames", [])),
            mapName=match.get("mapName"),
            seed=match.get("seed"),
            createdAt=match.get("createdAt", ""),
        )
        for match in repository.list_matches()
    ]


def get_match(repository: MatchRepository, match_id: str) -> MatchPayload:
    try:
        match_record = repository.get_match_record(match_id)
    except KeyError as exc:
        raise MatchNotFoundError(match_id) from exc

    round_payloads: List[RoundPayload] = []
    for round_record in repository.get_round_records(match_id):
        turns = [turn["turnState"] for turn in repository.get_turn_records(round_record["id"])]
        round_payloads.append(
            RoundPayload(
                roundId=round_record["id"],
                roundNumber=round_record["roundNumber"],
                turns=turns,
            )
        )

    return MatchPayload(
        matchId=match_record["id"],
        name=match_record["name"],
        status=match_record["status"],
        createdAt=match_record.get("createdAt", ""),
        playerNames=list(match_record.get("playerNames", [])),
        mapName=match_record.get("mapName"),
        seed=match_record.get("seed"),
        players=[PlayerRecord.model_validate(player) for player in match_record.get("players", [])],
        rounds=round_payloads,
        averageScores=[
            AverageScoreRecord.model_validate(record)
            for record in match_record.get("averageScores", [])
        ],
    )


def get_culled_board(
    repository: MatchRepository,
    match_id: str,
    player_id: str,
    turn_index: Optional[int] = None,
    round_number: Optional[int] = None,
    map_name: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Reconstruct a player's culled board view from stored turn snapshots.

    Claims are rebuilt from the recorded turnState (nothing new is persisted,
    so the storage schema is unchanged) and run through the same contract_map
    + board_view builders the notebooks use, returning the widget's
    {"nodes": [...], "links": [...]} shape. `map_name` defaults to the
    classic map; match records don't currently store which map was played.
    """
    try:
        match_record = repository.get_match_record(match_id)
    except KeyError as exc:
        raise MatchNotFoundError(match_id) from exc

    round_records = repository.get_round_records(match_id)
    if round_number is not None:
        round_records = [record for record in round_records if record["roundNumber"] == round_number]
    if not round_records:
        raise MatchNotFoundError(f"Match '{match_id}' has no round {round_number}.")

    turn_records = repository.get_turn_records(round_records[0]["id"])
    if turn_index is not None:
        turn_records = [record for record in turn_records if record["turnIndex"] == turn_index]
    if not turn_records:
        raise MatchNotFoundError(f"Match '{match_id}' has no turn {turn_index}.")
    turn_state = turn_records[-1]["turnState"]

    player_count = len(match_record.get("players", [])) or 4
    map_graph = MapGraph(player_count=player_count, map_name=map_name)
    claimed_by = claimed_by_from_turn_state(turn_state)
    culled = contract_map(map_graph.routes, map_graph.player_count, claimed_by, player_id)

    return {"nodes": build_culled_nodes(culled), "links": build_culled_edges(culled)}


def compute_average_scores(players: List[PlayerRecord], rounds: List[RoundPayload]) -> List[AverageScoreRecord]:
    average_scores = [AverageScoreRecord(playerId=player.playerId, scores=[]) for player in players]
    max_turns = max((len(round_payload.turns) for round_payload in rounds), default=0)

    for turn_index in range(max_turns):
        for average_score in average_scores:
            turn_scores = []
            for round_payload in rounds:
                if turn_index >= len(round_payload.turns):
                    continue
                turn_scores.append(find_player_score(round_payload.turns[turn_index], average_score.playerId))
            if turn_scores:
                average_score.scores.append(round(sum(turn_scores) / len(turn_scores)))

    return average_scores


def find_player_score(turn_state: Dict[str, Any], player_id: str) -> int:
    current_player = turn_state["player"]
    if current_player["playerId"] == player_id:
        return current_player["score"]
    for opponent in turn_state["opponents"]:
        if opponent["playerId"] == player_id:
            return opponent["score"]
    raise KeyError(f"Player '{player_id}' was not present in the turn state.")
