from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional
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
    image_url: Optional[str] = Field(
        None,
        max_length=1000,
        pattern=r"^https?://",
        description="Link público da foto da caixa do jogo (opcional)",
    )


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
    image_url: Optional[str] = None
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


class DNSResolutionInfo(BaseModel):
    target_hostname: str
    resolved_ips: List[str]
    status: str
    error_message: Optional[str] = None


class DynamoDBStatusInfo(BaseModel):
    connected: bool
    table_name: str
    mode: str
    endpoint_url: Optional[str] = None


class DiscoveryResponse(BaseModel):
    service: str
    node_urn: str
    instance_id: str
    hostname: str
    local_ip: str
    dns_target: str
    dns_resolution: DNSResolutionInfo
    lamport_clock: int
    dynamodb: DynamoDBStatusInfo
    timestamp: str
    # Esquema formal de nomeação (issue #5)
    region: Optional[str] = None
    local_ips: List[str] = Field(default_factory=list)
    internal_domain: Optional[str] = None
    dns: List[dict] = Field(default_factory=list)
    urn_schema: dict = Field(default_factory=dict)
