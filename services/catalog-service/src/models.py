from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class GameStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    MAINTENANCE = "MAINTENANCE"

class Game(BaseModel):
    id: int
    title: str
    description: str
    category: str
    price_per_day: float
    status: GameStatus = GameStatus.AVAILABLE
    owner_id: str
    owner_name: str
    latitude: float
    longitude: float

class GamePublicResponse(BaseModel):
    id: int
    title: str
    description: str
    category: str
    price_per_day: float
    status: GameStatus
    owner_name: str

class GameNearbyResponse(GamePublicResponse):
    distance_km: float

class StatusUpdatePayload(BaseModel):
    status: GameStatus
