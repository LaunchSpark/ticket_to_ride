from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError


class BotMetadata(BaseModel):
    schemaVersion: Literal[1]
    botId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    author: str = ""
    tags: List[str] = Field(default_factory=list)
    modulePath: str = ""

    @classmethod
    def from_module_meta(cls, meta: Dict[str, Any]) -> "BotMetadata":
        if not isinstance(meta, dict):
            raise ValueError("BOT_META must be a dictionary.")

        try:
            return cls.model_validate(
                {
                    "schemaVersion": meta.get("schema_version"),
                    "botId": meta.get("id"),
                    "name": meta.get("name"),
                    "version": meta.get("version"),
                    "description": meta.get("description"),
                    "author": meta.get("author") or "",
                    "tags": meta.get("tags") or [],
                }
            )
        except ValidationError as exc:
            first_error = exc.errors()[0]
            field_path = ".".join(str(part) for part in first_error.get("loc", ()))
            raise ValueError(f"Invalid BOT_META field '{field_path}': {first_error.get('msg', 'invalid value')}.") from exc


class BotSessionCreateRequest(BaseModel):
    botId: str


class BotSessionCreateResponse(BaseModel):
    sessionId: str


class BotSessionDeleteResponse(BaseModel):
    status: Literal["deleted"]


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
