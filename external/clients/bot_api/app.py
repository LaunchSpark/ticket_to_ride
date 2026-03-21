from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException

from external.clients.bot_api.models import (
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
from external.clients.bot_api.service import BotSessionManager


def create_app(session_manager: Optional[BotSessionManager] = None) -> FastAPI:
    app = FastAPI(title="Ticket to Ride Bot API", version="1.0.0")
    app.state.bot_session_manager = session_manager or BotSessionManager()

    def get_session_manager() -> BotSessionManager:
        return app.state.bot_session_manager

    @app.get("/bots", response_model=list[str])
    def get_bots(manager: BotSessionManager = Depends(get_session_manager)) -> list[str]:
        return manager.available_bot_names()

    @app.post("/bot-sessions", response_model=BotSessionCreateResponse)
    def post_bot_session(
        request: BotSessionCreateRequest,
        manager: BotSessionManager = Depends(get_session_manager),
    ) -> BotSessionCreateResponse:
        try:
            session_id = manager.create_session(request.botName)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return BotSessionCreateResponse(sessionId=session_id)

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
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
