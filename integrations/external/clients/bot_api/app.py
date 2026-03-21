from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from external.clients.bot_api.models import (
    BotMetadata,
    BotSessionDeleteResponse,
    BotSessionCreateRequest,
    BotSessionCreateResponse,
    ChooseColorRequest,
    ChooseColorResponse,
    ClaimRouteRequest,
    ClaimRouteResponse,
    DrawTrainRequest,
    DrawTrainResponse,
    TicketOfferRequest,
    TicketOfferResponse,
    TurnActionRequest,
    TurnActionResponse,
)
from external.clients.bot_api.service import BotExecutionError, BotSessionManager


def create_app(session_manager: Optional[BotSessionManager] = None) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Bot API", version="1.0.0")
    app.state.bot_session_manager = session_manager or BotSessionManager()

    @app.exception_handler(BotExecutionError)
    async def handle_bot_execution_error(_, exc: BotExecutionError) -> JSONResponse:
        return JSONResponse(status_code=422, content=exc.to_response())

    def get_session_manager() -> BotSessionManager:
        return app.state.bot_session_manager

    @app.get("/bots", response_model=list[BotMetadata])
    def get_bots(manager: BotSessionManager = Depends(get_session_manager)) -> list[BotMetadata]:
        return manager.list_bots()

    @app.post("/bot-sessions", response_model=BotSessionCreateResponse)
    def post_bot_session(
        request: BotSessionCreateRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> BotSessionCreateResponse:
        try:
            session_id = manager.create_session(request.botId)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return BotSessionCreateResponse(sessionId=session_id)

    @app.delete("/bot-sessions/{session_id}", response_model=BotSessionDeleteResponse)
    def delete_bot_session(
        session_id: str,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> BotSessionDeleteResponse:
        try:
            manager.delete_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return BotSessionDeleteResponse(status="deleted")

    @app.post("/bot-sessions/{session_id}/choose-turn-action", response_model=TurnActionResponse)
    def post_choose_turn_action(
        session_id: str,
        request: TurnActionRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> TurnActionResponse:
        try:
            action = manager.choose_turn_action(session_id, request.playerState.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TurnActionResponse(action=action)

    @app.post("/bot-sessions/{session_id}/choose-draw-train-action", response_model=DrawTrainResponse)
    def post_choose_draw_train_action(
        session_id: str,
        request: DrawTrainRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> DrawTrainResponse:
        try:
            draw_index = manager.choose_draw_train_action(session_id, request.playerState.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return DrawTrainResponse(drawIndex=draw_index)

    @app.post("/bot-sessions/{session_id}/choose-route-to-claim", response_model=ClaimRouteResponse)
    def post_choose_route_to_claim(
        session_id: str,
        request: ClaimRouteRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> ClaimRouteResponse:
        try:
            result = manager.choose_route_to_claim(
                session_id,
                request.playerState.model_dump(),
                request.claimableRoutes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ClaimRouteResponse(**result)

    @app.post("/bot-sessions/{session_id}/choose-color-to-spend", response_model=ChooseColorResponse)
    def post_choose_color_to_spend(
        session_id: str,
        request: ChooseColorRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> ChooseColorResponse:
        try:
            color = manager.choose_color_to_spend(
                session_id,
                request.playerState.model_dump(),
                request.route,
                request.colorOptions,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ChooseColorResponse(color=color)

    @app.post("/bot-sessions/{session_id}/select-ticket-offer", response_model=TicketOfferResponse)
    def post_select_ticket_offer(
        session_id: str,
        request: TicketOfferRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> TicketOfferResponse:
        try:
            selected_indices = manager.select_ticket_offer(
                session_id,
                request.playerState.model_dump(),
                request.offer,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TicketOfferResponse(selectedIndices=selected_indices)

    return app


app = create_app()
