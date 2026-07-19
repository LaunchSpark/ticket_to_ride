from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ticket_to_ride.backend.bot_catalog import BotCatalogError
from ticket_to_ride.backend.bot_directory import BotDirectory
from ticket_to_ride.backend.runtime import (
    ManagedMatchNotFoundError,
    ManagedMatchRuntimeManager,
    ManagedRoundNotFoundError,
    ManagedRuntimeError,
)
from ticket_to_ride.backend.models import (
    BotCreateRequest,
    BotCreateResponse,
    BotListResponse,
    ConnectionCreateRequest,
    ConnectionCreateResponse,
    CulledBoardResponse,
    ManagedMatchCreateRequest,
    ManagedMatchSummary,
    ManagedRoundSummary,
    MatchCreateRequest,
    MatchCreateResponse,
    MatchFinalizeResponse,
    MatchPayload,
    MatchSummary,
    NotebookLaunchResponse,
    RoundClockView,
    RoundCreateRequest,
    RoundCreateResponse,
    RoundRuntimeView,
    TurnCreateRequest,
    TurnCreateResponse,
)
from ticket_to_ride.backend.notebook_launcher import NotebookLauncher
from ticket_to_ride.backend.pocketbase import PocketBaseError, build_repository_from_env
from ticket_to_ride.backend.repository import MatchRepository
from ticket_to_ride.backend.service import (
    BotNotFoundError,
    ConnectionNotFoundError,
    MatchNotFoundError,
    add_bot_connection,
    create_bot,
    create_match,
    create_round,
    create_turn,
    finalize_match,
    get_culled_board,
    get_match,
    launch_notebook,
    list_bot_directory,
    list_matches,
    remove_bot_connection,
)


def _cors_origins_from_env() -> list[str]:
    configured = os.getenv("TICKET_TO_RIDE_CORS_ALLOW_ORIGINS", "*").strip()
    if configured == "*":
        return ["*"]
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def create_app(
    repository: Optional[MatchRepository] = None,
    bot_directory: Optional[BotDirectory] = None,
    runtime_manager: Optional[ManagedMatchRuntimeManager] = None,
    notebook_launcher: Optional[NotebookLauncher] = None,
) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Match Logger", version="1.0.0")
    app.state.match_repository = repository or build_repository_from_env()
    app.state.bot_directory = bot_directory or BotDirectory(app.state.match_repository)
    app.state.runtime_manager = runtime_manager
    app.state.notebook_launcher = notebook_launcher or NotebookLauncher()
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

    @app.exception_handler(BotCatalogError)
    async def handle_bot_catalog_error(_, exc: BotCatalogError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "service": "bot_catalog",
            },
        )

    @app.exception_handler(ManagedRuntimeError)
    async def handle_managed_runtime_error(_, exc: ManagedRuntimeError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "service": "managed_runtime",
            },
        )

    def get_repository() -> MatchRepository:
        return app.state.match_repository

    def get_bot_directory() -> BotDirectory:
        return app.state.bot_directory

    def get_notebook_launcher() -> NotebookLauncher:
        return app.state.notebook_launcher

    def get_runtime_manager() -> ManagedMatchRuntimeManager:
        if app.state.runtime_manager is None:
            app.state.runtime_manager = ManagedMatchRuntimeManager(
                app.state.match_repository,
                bot_directory=app.state.bot_directory,
            )
        return app.state.runtime_manager

    @app.get("/bots", response_model=BotListResponse)
    def get_bots(directory: BotDirectory = Depends(get_bot_directory)) -> BotListResponse:
        return list_bot_directory(directory)

    @app.post("/bots/new", response_model=BotCreateResponse)
    def post_new_bot(
        request: BotCreateRequest,
        notebook_launcher: NotebookLauncher = Depends(get_notebook_launcher),
    ) -> BotCreateResponse:
        try:
            return create_bot(notebook_launcher, request.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/bot-connections", response_model=ConnectionCreateResponse)
    def post_bot_connection(
        request: ConnectionCreateRequest,
        repository: MatchRepository = Depends(get_repository),
        directory: BotDirectory = Depends(get_bot_directory),
    ) -> ConnectionCreateResponse:
        try:
            return add_bot_connection(repository, directory, request.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/bot-connections/{connection_id}")
    def delete_bot_connection(
        connection_id: str,
        repository: MatchRepository = Depends(get_repository),
    ) -> dict:
        try:
            remove_bot_connection(repository, connection_id)
        except ConnectionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    @app.post("/notebooks/{bot_id}/launch", response_model=NotebookLaunchResponse)
    def post_launch_notebook(
        bot_id: str,
        directory: BotDirectory = Depends(get_bot_directory),
        notebook_launcher: NotebookLauncher = Depends(get_notebook_launcher),
    ) -> NotebookLaunchResponse:
        try:
            return launch_notebook(directory, notebook_launcher, bot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
            map_name=request.mapName,
            seed=request.seed,
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

    @app.get("/matches/{match_id}/culled-board", response_model=CulledBoardResponse)
    def get_culled_board_view(
        match_id: str,
        playerId: str,
        turnIndex: Optional[int] = None,
        roundNumber: Optional[int] = None,
        mapName: Optional[str] = None,
        repository: MatchRepository = Depends(get_repository),
    ) -> CulledBoardResponse:
        """A player's contracted view of the board at a recorded turn.

        Reconstructed on the fly from the stored turn snapshot (defaults:
        latest turn of the first round, classic map), in the same
        nodes/links shape the notebook graph widget consumes.
        """
        try:
            board = get_culled_board(
                repository,
                match_id,
                player_id=playerId,
                turn_index=turnIndex,
                round_number=roundNumber,
                map_name=mapName,
            )
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return CulledBoardResponse(**board)

    @app.get("/matches/{match_id}", response_model=MatchPayload)
    def get_match_by_id(
        match_id: str,
        repository: MatchRepository = Depends(get_repository),
    ) -> MatchPayload:
        try:
            return get_match(repository, match_id)
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/managed-matches", response_model=ManagedMatchSummary)
    def post_managed_match(
        request: ManagedMatchCreateRequest,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> ManagedMatchSummary:
        return runtime_manager.create_managed_match(request)

    @app.get("/managed-matches", response_model=list[ManagedMatchSummary])
    def get_managed_matches(
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> list[ManagedMatchSummary]:
        return runtime_manager.list_managed_matches()

    @app.get("/managed-matches/{match_id}", response_model=ManagedMatchSummary)
    def get_managed_match(
        match_id: str,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> ManagedMatchSummary:
        try:
            return runtime_manager.get_managed_match(match_id)
        except ManagedMatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/managed-matches/{match_id}/rounds", response_model=list[ManagedRoundSummary])
    def get_managed_rounds(
        match_id: str,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> list[ManagedRoundSummary]:
        try:
            return runtime_manager.list_rounds(match_id)
        except ManagedMatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/managed-matches/{match_id}/rounds/{round_number}", response_model=ManagedRoundSummary)
    def get_managed_round(
        match_id: str,
        round_number: int,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> ManagedRoundSummary:
        try:
            return runtime_manager.get_round(match_id, round_number)
        except ManagedRoundNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/managed-matches/{match_id}/rounds/{round_number}/clock", response_model=RoundClockView)
    def get_managed_round_clock(
        match_id: str,
        round_number: int,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> RoundClockView:
        try:
            return runtime_manager.get_round_clock(match_id, round_number)
        except ManagedRoundNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/managed-matches/{match_id}/rounds/{round_number}/runtime", response_model=RoundRuntimeView)
    def get_managed_round_runtime(
        match_id: str,
        round_number: int,
        runtime_manager: ManagedMatchRuntimeManager = Depends(get_runtime_manager),
    ) -> RoundRuntimeView:
        try:
            return runtime_manager.get_round_runtime(match_id, round_number)
        except ManagedRoundNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
