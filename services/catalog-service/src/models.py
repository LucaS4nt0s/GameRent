from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

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


class GameReserveRequest(BaseModel):
    rental_id: str = Field(..., min_length=1, description="UUID da locação gerado pelo rental-service")
    renter_name: str = Field(..., min_length=1, description="Nome do locatário")
    renter_email: Optional[str] = Field(None, description="E-mail do locatário (opcional)")


class GameReleaseRequest(BaseModel):
    rental_id: Optional[str] = Field(None, description="UUID da locação que está sendo encerrada (opcional)")
    force: bool = Field(False, description="Liberação administrativa forçada ignorando validação de rental_id")


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
    version: int = 1
    lamport_clock: int = 1
    current_rental_id: Optional[str] = None
    current_renter_name: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def model_post_init(self, __context) -> None:
        if not self.urn:
            self.urn = f"urn:gamerent:game:sa-east-1:{self.id}"
        if not self.owner_urn:
            self.owner_urn = f"urn:gamerent:owner:{self.owner_id}"


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
