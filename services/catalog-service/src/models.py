from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


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


class GamePublicResponse(BaseModel):
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
    version: int = 1
    lamport_clock: int = 1
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def model_post_init(self, __context) -> None:
        if not self.urn:
            self.urn = f"urn:gamerent:game:sa-east-1:{self.id}"
        if not self.owner_urn:
            self.owner_urn = f"urn:gamerent:owner:{self.owner_id}"


class Game(GamePublicResponse):
    latitude: float
    longitude: float


class GameNearbyResponse(GamePublicResponse):
    distance_km: float


class StatusUpdatePayload(BaseModel):
    status: GameStatus
