from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class BotSessionCreateRequest(BaseModel):
    botName: str


class BotSessionCreateResponse(BaseModel):
    sessionId: str


class PlayerStatePayload(BaseModel):
    playerId: str
    name: str
    color: str
    trainsRemaining: int
    hand: Dict[str, int]
    exposedHand: Dict[str, int]
    tickets: List[Dict[str, Any]]
    context: Dict[str, Any]


class TurnActionRequest(BaseModel):
    playerState: PlayerStatePayload


class TurnActionResponse(BaseModel):
    action: int


class DrawTrainRequest(BaseModel):
    playerState: PlayerStatePayload


class DrawTrainResponse(BaseModel):
    drawIndex: int


class ClaimRouteRequest(BaseModel):
    playerState: PlayerStatePayload
    claimableRoutes: List[Dict[str, Any]]


class ClaimRouteResponse(BaseModel):
    selectedIndex: int
    locomotives: int


class ChooseColorRequest(BaseModel):
    playerState: PlayerStatePayload
    route: Dict[str, Any]
    colorOptions: List[str]


class ChooseColorResponse(BaseModel):
    color: Optional[str] = None


class TicketOfferRequest(BaseModel):
    playerState: PlayerStatePayload
    offer: List[Dict[str, Any]]


class TicketOfferResponse(BaseModel):
    selectedIndices: List[int]

