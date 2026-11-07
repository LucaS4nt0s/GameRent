from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

import naming

class RentalStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

class RentalCreateRequest(BaseModel):
    renter_name: str = Field(..., min_length=1, example="João da Silva")
    renter_email: str = Field(..., min_length=3, example="joao.silva@exemplo.com")
    game_id: int = Field(..., gt=0, example=1)
    rental_days: int = Field(..., gt=0, le=365, example=3)

class RentalResponse(BaseModel):
    rental_id: str
    urn: str = ""
    game_id: int
    game_urn: str = ""
    game_title: str
    renter_name: str
    renter_email: str
    rental_days: int
    daily_rate: float
    total_price: float
    status: RentalStatus
    lamport_clock: int = 1
    created_at: str
    returned_at: Optional[str] = None
    served_by_node: str = ""

    def model_post_init(self, __context) -> None:
        if not self.urn:
            try:
                self.urn = naming.rental_urn(self.rental_id)
            except ValueError:
                # Registro legado com id fora do padrão UUID: não derruba a listagem inteira
                self.urn = ""
        if not self.game_urn:
            self.game_urn = naming.game_urn(self.game_id)
        if not self.served_by_node:
            self.served_by_node = naming.node_urn("rental-service")


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


