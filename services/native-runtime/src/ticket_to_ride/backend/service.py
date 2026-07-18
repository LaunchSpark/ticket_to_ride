from __future__ import annotations

from typing import Any, Dict, List, Optional

from ticket_to_ride.backend.bot_catalog import BotCatalogClient
from ticket_to_ride.board_view import (
    build_culled_edges,
    build_culled_nodes,
    claimed_by_from_turn_state,
)
from ticket_to_ride.engine.state.map import MapGraph, contract_map
from ticket_to_ride.backend.models import (
    AverageScoreRecord,
    BotSummary,
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


def build_bot_summary(bot_record: Dict[str, Any]) -> BotSummary:
    return BotSummary(
        schemaVersion=bot_record["schemaVersion"],
        botId=bot_record["botId"],
        name=bot_record["name"],
        version=bot_record["version"],
        description=bot_record["description"],
        author=bot_record.get("author", ""),
        tags=list(bot_record.get("tags", [])),
        sourceKind=bot_record["sourceKind"],
        sourceBaseUrl=bot_record["sourceBaseUrl"],
        discoveryPath=bot_record["discoveryPath"],
        createdAt=bot_record.get("createdAt", ""),
    )


def list_bots(repository: MatchRepository) -> List[BotSummary]:
    return [build_bot_summary(bot_record) for bot_record in repository.list_bots()]


def register_bot(repository: MatchRepository, catalog_client: BotCatalogClient, bot_id: str) -> BotSummary:
    requested_bot_id = bot_id.strip()
    if not requested_bot_id:
        raise ValueError("Bot ID is required.")

    try:
        catalog_record = catalog_client.resolve_bot(requested_bot_id)
    except KeyError as exc:
        raise BotNotFoundError(f"Unknown bot '{requested_bot_id}'.") from exc

    stored_record = repository.upsert_bot(
        schema_version=catalog_record.schema_version,
        bot_id=catalog_record.bot_id,
        name=catalog_record.name,
        version=catalog_record.version,
        description=catalog_record.description,
        author=catalog_record.author,
        tags=catalog_record.tags,
        source_kind=catalog_record.source_kind,
        source_base_url=catalog_record.source_base_url,
        discovery_path=catalog_record.discovery_path,
    )
    return build_bot_summary(stored_record)


def launch_notebook(
    catalog_client: BotCatalogClient,
    notebook_launcher: NotebookLauncher,
    bot_id: str,
) -> NotebookLaunchResponse:
    requested_bot_id = bot_id.strip()
    if not requested_bot_id:
        raise ValueError("Bot ID is required.")

    try:
        catalog_record = catalog_client.resolve_bot(requested_bot_id)
    except KeyError as exc:
        raise BotNotFoundError(f"Unknown bot '{requested_bot_id}'.") from exc

    url = notebook_launcher.launch(catalog_record.bot_id, catalog_record.module_path)
    return NotebookLaunchResponse(botId=catalog_record.bot_id, url=url)


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
