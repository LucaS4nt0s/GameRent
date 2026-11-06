import logging
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from models import (
    ConsistencyMode,
    Game,
    GameCreateRequest,
    GameNearbyResponse,
    GamePublicResponse,
    GameStatus,
    StatusUpdatePayload,
)
from geo_utils import calculate_haversine_distance
import naming

SERVICE_NAME = "catalog-service"
NODE_URN = naming.node_urn(SERVICE_NAME)
# Nomes simbólicos deste nó: Route 53 / Cloud Map na AWS, aliases do Docker DNS localmente
DNS_TARGETS = [t for t in os.getenv("DNS_DISCOVERY_TARGETS", f"catalog.{naming.INTERNAL_DOMAIN},catalog-service").split(",") if t]

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

# ponytail: lock em memória por processo; migrar para DynamoDB ConditionalExpression em multi-réplica
_lock = threading.Lock()
_lamport_clock = 0


def tick_lamport(incoming: Optional[int] = None) -> int:
    global _lamport_clock
    with _lock:
        _lamport_clock = (max(_lamport_clock, incoming) if incoming is not None else _lamport_clock) + 1
        return _lamport_clock


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
        longitude=-46.6333  # Região Central de SP
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
        longitude=-46.6560  # Av. Paulista
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
        status=GameStatus.RENTED,  # Inicialmente já locado para testes de conflito
        owner_id="locador-003",
        owner_name="Mariana Souza",
        latitude=-23.5874,
        longitude=-46.6795  # Itaim Bibi
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

# ponytail: scan/get_item com ConsistentRead e filtro Haversine em memória; usar GeoIndex/GSI se acervo crescer >10k itens
_ddb_table = None


def _get_ddb_table():
    global _ddb_table
    if _ddb_table is not None:
        return _ddb_table
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL")
    if not (os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes") or endpoint):
        return None
    try:
        import boto3
        ddb = boto3.resource(
            "dynamodb",
            region_name=os.getenv("AWS_REGION", "sa-east-1"),
            endpoint_url=endpoint,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
        name = os.getenv("GAMES_TABLE_NAME", "gamerent_games")
        table = (
            ddb.Table(name)
            if name in [t.name for t in ddb.tables.all()]
            else ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "N"}],
                BillingMode="PAY_PER_REQUEST",
            )
        )
        table.wait_until_exists()
        if not table.scan(Limit=1).get("Items"):
            for g in GAMES_DB.values():
                _put_ddb_game(table, g)
        _ddb_table = table
        return _ddb_table
    except Exception as exc:
        logger.warning(f"DynamoDB indisponível, operando com GAMES_DB em memória: {exc}")
        return None


def _put_ddb_game(table, game: Game) -> None:
    item = {**game.model_dump(), "status": game.status.value}
    for k in ("price_per_day", "latitude", "longitude"):
        item[k] = Decimal(str(item[k]))
    table.put_item(Item=item)


def _save_game(game: Game) -> GamePublicResponse:
    GAMES_DB[game.id] = game
    table = _get_ddb_table()
    if table is not None:
        try:
            _put_ddb_game(table, game)
        except Exception as exc:
            logger.warning(f"Falha ao persistir jogo {game.id} no DynamoDB: {exc}")
    return GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN)


def _read_games(consistency: ConsistencyMode) -> tuple[list[Game], float]:
    table = _get_ddb_table()
    t0 = time.perf_counter()
    if table is not None:
        try:
            items = table.scan(ConsistentRead=(consistency == "strong")).get("Items", [])
            games = sorted((Game(**it) for it in items), key=lambda g: g.id)
            return games, round((time.perf_counter() - t0) * 1000, 3)
        except Exception as exc:
            logger.warning(f"Falha ao ler catálogo no DynamoDB: {exc}")
    return list(GAMES_DB.values()), round((time.perf_counter() - t0) * 1000, 3)


def _read_game(game_id: int, consistency: ConsistencyMode) -> tuple[Optional[Game], float]:
    table = _get_ddb_table()
    t0 = time.perf_counter()
    if table is not None:
        try:
            item = table.get_item(Key={"id": game_id}, ConsistentRead=(consistency == "strong")).get("Item")
            return (Game(**item) if item else None), round((time.perf_counter() - t0) * 1000, 3)
        except Exception as exc:
            logger.warning(f"Falha ao ler jogo {game_id} no DynamoDB: {exc}")
    return GAMES_DB.get(game_id), round((time.perf_counter() - t0) * 1000, 3)


def _set_read_headers(response: Response, consistency: ConsistencyMode, latency_ms: float) -> dict:
    response.headers["X-Consistency-Mode"] = consistency
    response.headers["X-DB-Read-Latency-Ms"] = str(latency_ms)
    response.headers["X-Served-By-Node"] = NODE_URN
    return {"consistency_mode": consistency, "db_read_latency_ms": latency_ms, "served_by_node": NODE_URN}


def _matches(g: Game, status_filter: Optional[GameStatus], category: Optional[str], owner_id: Optional[str]) -> bool:
    return (
        (not status_filter or g.status == status_filter)
        and (not category or g.category.lower() == category.strip().lower())
        and (not owner_id or g.owner_id == owner_id)
    )


@app.get("/health", tags=["Monitoramento"])
def health_check():
    """Endpoint de integridade para monitoramento (Health Check)."""
    return {
        "status": "HEALTHY",
        "service": "catalog-service",
        "node_urn": NODE_URN,
        "instance_id": naming.instance_id(),
        "total_games": len(GAMES_DB),
        "lamport_clock": _lamport_clock
    }


@app.get("/discovery", tags=["Monitoramento"])
def discovery():
    """Metadados de nomeação do nó: URN, INSTANCE_ID, esquema de URNs e resolução DNS interna."""
    return naming.discovery_info(SERVICE_NAME, DNS_TARGETS, _lamport_clock)


@app.on_event("startup")
def log_dns_resolution():
    logger.info(f"Nó {NODE_URN} iniciado")
    for target in DNS_TARGETS:
        naming.resolve(target)


@app.post("/games", response_model=GamePublicResponse, status_code=status.HTTP_201_CREATED, tags=["Catálogo"])
def create_game(
    payload: GameCreateRequest,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """FA-01: Cadastra um novo jogo de tabuleiro pelo locador sem expor coordenadas de GPS."""
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    with _lock:
        new_id = max(GAMES_DB.keys(), default=0) + 1
        game = Game(id=new_id, lamport_clock=clock, **payload.model_dump())
        GAMES_DB[new_id] = game
    logger.info(f"[LAMPORT={clock}] Novo jogo cadastrado: ID={new_id}, URN={game.urn}")
    return _save_game(game)


@app.get("/games", response_model=List[GamePublicResponse], tags=["Catálogo"])
def list_games(
    response: Response,
    status_filter: Optional[GameStatus] = None,
    category: Optional[str] = None,
    owner_id: Optional[str] = None,
    consistency: ConsistencyMode = "strong",
):
    """FA-02: Lista jogos com filtros opcionais e seletor de consistência, omitindo coordenadas de GPS."""
    games, latency_ms = _read_games(consistency)
    meta = _set_read_headers(response, consistency, latency_ms)
    return [
        GamePublicResponse(**g.model_dump(), **meta)
        for g in games
        if _matches(g, status_filter, category, owner_id)
    ]


@app.get("/games/nearby", response_model=List[GameNearbyResponse], tags=["Catálogo"])
def list_nearby_games(
    response: Response,
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude do locatário"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude do locatário"),
    max_km: float = Query(10.0, gt=0, description="Raio máximo de busca em km"),
    status_filter: Optional[GameStatus] = None,
    category: Optional[str] = None,
    owner_id: Optional[str] = None,
    consistency: ConsistencyMode = "strong",
):
    """FA-02: Calcula a distância Haversine em memória sem expor as coordenadas reais do locador."""
    games, latency_ms = _read_games(consistency)
    meta = _set_read_headers(response, consistency, latency_ms)
    results = [
        GameNearbyResponse(**g.model_dump(), **meta, distance_km=dist)
        for g in games
        if _matches(g, status_filter, category, owner_id)
        and (dist := calculate_haversine_distance(lat, lon, g.latitude, g.longitude)) <= max_km
    ]
    results.sort(key=lambda x: x.distance_km)
    return results


@app.get("/games/{game_id}", response_model=GamePublicResponse, tags=["Catálogo"])
def get_game_by_id(game_id: int, response: Response, consistency: ConsistencyMode = "strong"):
    """Consulta um jogo específico com seletor de consistência."""
    game, latency_ms = _read_game(game_id, consistency)
    meta = _set_read_headers(response, consistency, latency_ms)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogo com ID {game_id} não encontrado no catálogo."
        )
    return GamePublicResponse(**game.model_dump(), **meta)


@app.patch("/games/{game_id}/status", response_model=GamePublicResponse, tags=["Catálogo"])
def update_game_status(
    game_id: int,
    payload: StatusUpdatePayload,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FA-05: Atualiza o status do jogo (bloqueia com 409 Conflict se estiver RENTED
    e tentar ir para MAINTENANCE ou ser locado novamente, permitindo devolução para AVAILABLE).
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Atualização de status do jogo ID={game_id} para {payload.status}")

    with _lock:
        if game_id not in GAMES_DB:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        game = GAMES_DB[game_id]
        if (
            (game.status == GameStatus.RENTED and payload.status != GameStatus.AVAILABLE)
            or (game.status == GameStatus.MAINTENANCE and payload.status == GameStatus.RENTED)
        ):
            logger.warning(f"[LAMPORT={clock}] Conflito 409: tentativa de alterar jogo ID={game_id} de {game.status} para {payload.status}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transição inválida de '{game.status}' para '{payload.status}' no jogo '{game.title}'."
            )

        game.status = payload.status
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()
    return _save_game(game)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
