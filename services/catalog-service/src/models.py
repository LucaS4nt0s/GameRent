from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

import naming

ConsistencyMode = Literal["strong", "eventual"]


class GameStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    MAINTENANCE = "MAINTENANCE"


class GameCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    price_per_day: float = Field(..., gt=0)
    owner_id: str = Field(..., min_length=1)
    owner_name: str = Field(..., min_length=1)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class _GameBase(BaseModel):
    id: int
    urn: str = ""
    title: str
    description: str
    category: str
    price_per_day: float
    status: GameStatus = GameStatus.AVAILABLE
    owner_id: str
    owner_urn: str = ""
    owner_name: str
    current_rental_id: Optional[str] = None
    version: int = 1
    lamport_clock: int = 1
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def model_post_init(self, __context) -> None:
        if not self.urn:
            self.urn = naming.game_urn(self.id)
        if not self.owner_urn:
            self.owner_urn = naming.owner_urn(self.owner_id)


class GamePublicResponse(_GameBase):
    consistency_mode: ConsistencyMode = "strong"
    db_read_latency_ms: float = 0.0
    served_by_node: str = ""


class Game(_GameBase):
    latitude: float
    longitude: float


class GameNearbyResponse(GamePublicResponse):
    distance_km: float


class StatusUpdatePayload(BaseModel):
    status: GameStatus
