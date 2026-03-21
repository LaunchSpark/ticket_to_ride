from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ticket_to_ride.backend.models import (
    MatchCreateRequest,
    MatchCreateResponse,
    MatchFinalizeResponse,
    MatchPayload,
    MatchSummary,
    RoundCreateRequest,
    RoundCreateResponse,
    TurnCreateRequest,
    TurnCreateResponse,
)
from ticket_to_ride.backend.pocketbase import PocketBaseError, build_repository_from_env
from ticket_to_ride.backend.repository import MatchRepository
from ticket_to_ride.backend.service import MatchNotFoundError, create_match, create_round, create_turn, finalize_match, get_match, list_matches


def _cors_origins_from_env() -> list[str]:
    configured = os.getenv("TICKET_TO_RIDE_CORS_ALLOW_ORIGINS", "*").strip()
    if configured == "*":
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def create_app(repository: Optional[MatchRepository] = None) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Match Logger", version="1.0.0")
    app.state.match_repository = repository or build_repository_from_env()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_from_env(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PocketBaseError)
    async def handle_pocketbase_error(_, exc: PocketBaseError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "service": "pocketbase",
            },
        )

    def get_repository() -> MatchRepository:
        return app.state.match_repository

    @app.post("/matches", response_model=MatchCreateResponse)
    def post_match(
        request: MatchCreateRequest,
        repository: MatchRepository = Depends(get_repository),
    ) -> MatchCreateResponse:
        match_name = request.name or "-".join(player.name for player in request.players)
        match_id = create_match(
            repository,
            name=match_name,
            players=request.players,
            player_names=request.playerNames or [player.name for player in request.players],
        )
        return MatchCreateResponse(matchId=match_id)

    @app.post("/matches/{match_id}/rounds", response_model=RoundCreateResponse)
    def post_round(
        match_id: str,
        request: RoundCreateRequest,
        repository: MatchRepository = Depends(get_repository),
    ) -> RoundCreateResponse:
        try:
            round_id = create_round(repository, match_id=match_id, round_number=request.roundNumber)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RoundCreateResponse(roundId=round_id)

    @app.post("/matches/{match_id}/rounds/{round_id}/turns", response_model=TurnCreateResponse)
    def post_turn(
        match_id: str,
        round_id: str,
        request: TurnCreateRequest,
        repository: MatchRepository = Depends(get_repository),
    ) -> TurnCreateResponse:
        try:
            turn_id = create_turn(
                repository,
                match_id=match_id,
                round_id=round_id,
                turn_index=request.turnIndex,
                turn_state=request.turnState,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TurnCreateResponse(turnId=turn_id)

    @app.post("/matches/{match_id}/finalize", response_model=MatchFinalizeResponse)
    def post_finalize(
        match_id: str,
        repository: MatchRepository = Depends(get_repository),
    ) -> MatchFinalizeResponse:
        try:
            average_scores = finalize_match(repository, match_id)
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MatchFinalizeResponse(matchId=match_id, status="completed", averageScores=average_scores)

    @app.get("/matches", response_model=list[MatchSummary])
    def get_matches(
        repository: MatchRepository = Depends(get_repository),
    ) -> list[MatchSummary]:
        return list_matches(repository)

    @app.get("/matches/{match_id}", response_model=MatchPayload)
    def get_match_by_id(
        match_id: str,
        repository: MatchRepository = Depends(get_repository),
    ) -> MatchPayload:
        try:
            return get_match(repository, match_id)
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
