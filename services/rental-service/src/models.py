from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class RentalStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

class RentalCreateRequest(BaseModel):
    renter_name: str = Field(..., example="João da Silva")
    renter_email: str = Field(..., example="joao.silva@exemplo.com")
    game_id: int = Field(..., example=1)
    rental_days: int = Field(..., gt=0, example=3)

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

    def model_post_init(self, __context) -> None:
        if not self.urn and self.rental_id:
            self.urn = f"urn:gamerent:rental:{self.rental_id}"
        if not self.game_urn and self.game_id:
            self.game_urn = f"urn:gamerent:game:sa-east-1:{self.game_id}"

