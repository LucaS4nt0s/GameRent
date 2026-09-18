import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from models import Game, GameStatus, GamePublicResponse, GameNearbyResponse, StatusUpdatePayload
from geo_utils import calculate_haversine_distance

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [CATALOG-SERVICE] %(message)s"
)
logger = logging.getLogger("catalog-service")

app = FastAPI(
    title="GameRent — Catalog Service",
    description="Microsserviço de Catálogo e Cálculo de Proximidade Relativa de Jogos de Tabuleiro.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de dados em memória inicial (Jogos de Tabuleiro)
GAMES_DB: dict[int, Game] = {
    1: Game(
        id=1,
        title="Catan (Os Colonizadores de Catan)",
        description="Clássico jogo de negociação, comércio e colonização.",
        category="Estratégia",
        price_per_day=15.0,
        status=GameStatus.AVAILABLE,
        owner_id="locador-001",
        owner_name="Ana Paula",
        latitude=-23.5505,
        longitude=-46.6333 # Região Central de SP
    ),
    2: Game(
        id=2,
        title="Terraforming Mars",
        description="Corporações competindo para tornar Marte habitável.",
        category="Estratégia Pesada",
        price_per_day=25.0,
        status=GameStatus.AVAILABLE,
        owner_id="locador-002",
        owner_name="Carlos Eduardo",
        latitude=-23.5615,
        longitude=-46.6560 # Av. Paulista
    ),
    3: Game(
        id=3,
        title="Dixit",
        description="Jogo de dedução visual e imaginação com belas ilustrações.",
        category="Party Game",
        price_per_day=12.0,
        status=GameStatus.AVAILABLE,
        owner_id="locador-001",
        owner_name="Ana Paula",
        latitude=-23.5505,
        longitude=-46.6333
    ),
    4: Game(
        id=4,
        title="Ticket to Ride: Europa",
        description="Aventura ferroviária conectando cidades pelo continente.",
        category="Familiar",
        price_per_day=18.0,
        status=GameStatus.RENTED, # Inicialmente já locado para testes de conflito
        owner_id="locador-003",
        owner_name="Mariana Souza",
        latitude=-23.5874,
        longitude=-46.6795 # Itaim Bibi
    ),
    5: Game(
        id=5,
        title="Pandemic",
        description="Jogo cooperativo contra surtos globais de doenças.",
        category="Cooperativo",
        price_per_day=16.0,
        status=GameStatus.AVAILABLE,
        owner_id="locador-002",
        owner_name="Carlos Eduardo",
        latitude=-23.5615,
        longitude=-46.6560
    )
}

@app.get("/health", tags=["Monitoramento"])
def health_check():
    """Endpoint de integridade para monitoramento (Health Check)."""
    return {
        "status": "HEALTHY",
        "service": "catalog-service",
        "total_games": len(GAMES_DB)
    }

@app.get("/games", response_model=List[GamePublicResponse], tags=["Catálogo"])
def list_games(status_filter: Optional[GameStatus] = None):
    """Lista todos os jogos, omitindo coordenadas sensíveis de GPS."""
    logger.info("Listagem de jogos solicitada.")
    games = list(GAMES_DB.values())
    if status_filter:
        games = [g for g in games if g.status == status_filter]
    return [GamePublicResponse(**g.model_dump()) for g in games]

@app.get("/games/nearby", response_model=List[GameNearbyResponse], tags=["Catálogo"])
def list_nearby_games(
    lat: float = Query(..., description="Latitude do locatário"),
    lon: float = Query(..., description="Longitude do locatário"),
    max_km: float = Query(10.0, description="Raio máximo de busca em km")
):
    """
    Calcula em memória a distância euclidiana/haversine entre o locatário e os jogos,
    sem jamais expor as coordenadas reais do locador ao cliente (Requisito Arquitetural Entrega 1).
    """
    logger.info(f"Busca geográfica recebida: lat={lat}, lon={lon}, max_km={max_km}")
    results = []

    for game in GAMES_DB.values():
        dist = calculate_haversine_distance(lat, lon, game.latitude, game.longitude)
        if dist <= max_km:
            results.append(
                GameNearbyResponse(
                    id=game.id,
                    title=game.title,
                    description=game.description,
                    category=game.category,
                    price_per_day=game.price_per_day,
                    status=game.status,
                    owner_name=game.owner_name,
                    distance_km=dist
                )
            )

    results.sort(key=lambda x: x.distance_km)
    return results

@app.get("/games/{game_id}", response_model=GamePublicResponse, tags=["Catálogo"])
def get_game_by_id(game_id: int):
    """
    Consulta um jogo específico.
    Este endpoint é consumido internamente pelo RENTAL-SERVICE via chamada REST síncrona.
    """
    logger.info(f"Consulta de jogo ID={game_id} solicitada.")
    if game_id not in GAMES_DB:
        logger.warning(f"Jogo ID={game_id} não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogo com ID {game_id} não encontrado no catálogo."
        )
    return GamePublicResponse(**GAMES_DB[game_id].model_dump())

@app.patch("/games/{game_id}/status", response_model=GamePublicResponse, tags=["Catálogo"])
def update_game_status(game_id: int, payload: StatusUpdatePayload):
    """Atualiza o status do jogo (utilizado na confirmação ou devolução de locação)."""
    logger.info(f"Atualização de status do jogo ID={game_id} para {payload.status}")
    if game_id not in GAMES_DB:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogo com ID {game_id} não encontrado no catálogo."
        )
    GAMES_DB[game_id].status = payload.status
    return GamePublicResponse(**GAMES_DB[game_id].model_dump())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
