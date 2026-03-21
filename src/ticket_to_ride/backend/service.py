from __future__ import annotations

from typing import Any, Dict, List

from ticket_to_ride.backend.models import (
    AverageScoreRecord,
    MatchPayload,
    MatchSummary,
    PlayerRecord,
    RoundPayload,
)
from ticket_to_ride.backend.repository import MatchRepository


class MatchNotFoundError(KeyError):
    """Raised when a requested match does not exist."""


def create_match(
    repository: MatchRepository,
    name: str,
    players: List[PlayerRecord],
    player_names: List[str] | None = None,
) -> str:
    return repository.create_match(name=name, players=players, player_names=player_names)


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
        players=[PlayerRecord.model_validate(player) for player in match_record.get("players", [])],
        rounds=round_payloads,
        averageScores=[
            AverageScoreRecord.model_validate(record)
            for record in match_record.get("averageScores", [])
        ],
    )


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
