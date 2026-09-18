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
    game_id: int
    game_title: str
    renter_name: str
    renter_email: str
    rental_days: int
    daily_rate: float
    total_price: float
    status: RentalStatus
    created_at: str
