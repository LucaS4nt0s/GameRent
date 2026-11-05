import logging
import os
import socket
import threading
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from models import (
    DiscoveryResponse,
    DNSResolutionInfo,
    DynamoDBStatusInfo,
    Game,
    GameCreateRequest,
    GameNearbyResponse,
    GamePublicResponse,
    GameReleaseRequest,
    GameReserveRequest,
    GameStatus,
    StatusUpdatePayload,
)
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

# ponytail: lock em memória por processo; migrar para DynamoDB ConditionalExpression em multi-réplica
_lock = threading.Lock()
_lamport_clock = 0

INSTANCE_ID = os.getenv("INSTANCE_ID", os.getenv("HOSTNAME", "node-catalog-01"))
NODE_URN = f"urn:gamerent:node:catalog-service:{INSTANCE_ID}"
DNS_TARGET = os.getenv("DNS_DISCOVERY_TARGET", "catalog.gamerent.internal")


def tick_lamport(incoming: Optional[int] = None) -> int:
    global _lamport_clock
    with _lock:
        _lamport_clock = (max(_lamport_clock, incoming) if incoming is not None else _lamport_clock) + 1
        return _lamport_clock


def _resolve_dns(target: str) -> DNSResolutionInfo:
    try:
        host = target
        if "://" in host:
            host = urllib.parse.urlparse(host).hostname or host
        if ":" in host:
            host = host.split(":")[0]

        addr_info = socket.getaddrinfo(host, None)
        ips = list(dict.fromkeys([item[4][0] for item in addr_info]))
        return DNSResolutionInfo(
            target_hostname=host,
            resolved_ips=ips,
            status="RESOLVED"
        )
    except Exception as exc:
        return DNSResolutionInfo(
            target_hostname=target,
            resolved_ips=[],
            status="UNRESOLVED",
            error_message=str(exc)
        )


def _get_dynamodb_status() -> DynamoDBStatusInfo:
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL")
    name = os.getenv("GAMES_TABLE_NAME", "gamerent_games")
    table = _get_ddb_table()
    if table is not None:
        mode = "LOCAL_DYNAMODB" if endpoint and ("localhost" in endpoint or "127.0.0.1" in endpoint) else "AWS_DYNAMODB"
        return DynamoDBStatusInfo(
            connected=True,
            table_name=name,
            mode=mode,
            endpoint_url=endpoint
        )
    return DynamoDBStatusInfo(
        connected=False,
        table_name=name,
        mode="IN_MEMORY_FALLBACK",
        endpoint_url=endpoint
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

# ponytail: espelhamento write-through opcional; leituras seguem em GAMES_DB até a issue de repositório
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
        if k in item and item[k] is not None:
            item[k] = Decimal(str(item[k]))
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)


def _reserve_ddb_game(table, game_id: int, rental_id: str, renter_name: str, clock: int) -> bool:
    """Trava atômica condicional no DynamoDB: só atualiza se status atual for AVAILABLE."""
    try:
        table.update_item(
            Key={"id": game_id},
            UpdateExpression="SET #st = :rented, current_rental_id = :rid, current_renter_name = :rname, version = version + :inc, lamport_clock = :clk, updated_at = :upd",
            ConditionExpression="attribute_exists(id) AND #st = :avail",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":rented": GameStatus.RENTED.value,
                ":avail": GameStatus.AVAILABLE.value,
                ":rid": rental_id,
                ":rname": renter_name,
                ":inc": 1,
                ":clk": clock,
                ":upd": datetime.now(timezone.utc).isoformat()
            }
        )
        return True
    except Exception as exc:
        if "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc):
            raise
        logger.warning(f"Erro na reserva condicional do DynamoDB para jogo {game_id}: {exc}")
        return False


def _save_game(game: Game) -> GamePublicResponse:
    GAMES_DB[game.id] = game
    table = _get_ddb_table()
    if table is not None:
        try:
            _put_ddb_game(table, game)
        except Exception as exc:
            logger.warning(f"Falha ao persistir jogo {game.id} no DynamoDB: {exc}")
    return GamePublicResponse(**game.model_dump())


@app.get("/health", tags=["Monitoramento"])
def health_check(
    response: Response = None,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """Endpoint de integridade para monitoramento (Health Check)."""
    clock = tick_lamport(x_lamport_clock)
    if response:
        response.headers["X-Lamport-Clock"] = str(clock)
    return {
        "status": "HEALTHY",
        "service": "catalog-service",
        "node_urn": NODE_URN,
        "instance_id": INSTANCE_ID,
        "total_games": len(GAMES_DB),
        "lamport_clock": clock
    }


@app.get("/discovery", response_model=DiscoveryResponse, tags=["Observabilidade"])
def get_discovery(
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FC-01: Descoberta de serviços, identidade de nó (URNs), resolução DNS e telemetria.
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    dns_info = _resolve_dns(DNS_TARGET)
    ddb_info = _get_dynamodb_status()

    return DiscoveryResponse(
        service="catalog-service",
        node_urn=NODE_URN,
        instance_id=INSTANCE_ID,
        hostname=hostname,
        local_ip=local_ip,
        dns_target=DNS_TARGET,
        dns_resolution=dns_info,
        lamport_clock=clock,
        dynamodb=ddb_info,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


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
def list_games(status_filter: Optional[GameStatus] = None, owner_id: Optional[str] = None):
    """Lista todos os jogos, omitindo coordenadas sensíveis de GPS."""
    logger.info("Listagem de jogos solicitada.")
    return [
        GamePublicResponse(**g.model_dump())
        for g in GAMES_DB.values()
        if (not status_filter or g.status == status_filter)
        and (not owner_id or g.owner_id == owner_id)
    ]


@app.get("/games/nearby", response_model=List[GameNearbyResponse], tags=["Catálogo"])
def list_nearby_games(
    lat: float = Query(..., description="Latitude do locatário"),
    lon: float = Query(..., description="Longitude do locatário"),
    max_km: float = Query(10.0, description="Raio máximo de busca em km")
):
    """Calcula a distância haversine sem expor as coordenadas reais do locador."""
    logger.info(f"Busca geográfica recebida: lat={lat}, lon={lon}, max_km={max_km}")
    results = [
        GameNearbyResponse(**g.model_dump(), distance_km=dist)
        for g in GAMES_DB.values()
        if (dist := calculate_haversine_distance(lat, lon, g.latitude, g.longitude)) <= max_km
    ]
    results.sort(key=lambda x: x.distance_km)
    return results


@app.get("/games/{game_id}", response_model=GamePublicResponse, tags=["Catálogo"])
def get_game_by_id(game_id: int):
    """Consulta um jogo específico."""
    logger.info(f"Consulta de jogo ID={game_id} solicitada.")
    if game_id not in GAMES_DB:
        logger.warning(f"Jogo ID={game_id} não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Jogo com ID {game_id} não encontrado no catálogo."
        )
    return GamePublicResponse(**GAMES_DB[game_id].model_dump())


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


@app.post("/games/{game_id}/reserve", response_model=GamePublicResponse, tags=["Catálogo"])
def reserve_game(
    game_id: int,
    payload: GameReserveRequest,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FA-03 / FA-04: Reserva atômica de exemplar para locação.
    Garante exclusão mútua: se o jogo não estiver AVAILABLE, rejeita imediatamente com 409 Conflict.
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Tentativa de reserva atômica para o jogo ID={game_id} (Rental={payload.rental_id}, Locatário={payload.renter_name})")

    with _lock:
        if game_id not in GAMES_DB:
            logger.warning(f"Jogo ID={game_id} não encontrado para reserva.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        game = GAMES_DB[game_id]
        if game.status != GameStatus.AVAILABLE:
            logger.warning(f"[LAMPORT={clock}] Conflito 409: Jogo ID={game_id} indisponível para reserva (status atual: {game.status})")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"O jogo '{game.title}' não está disponível para reserva no momento (status atual: {game.status})."
            )

        # Atualiza trava condicional no DynamoDB se configurado
        table = _get_ddb_table()
        if table is not None:
            try:
                _reserve_ddb_game(table, game_id, payload.rental_id, payload.renter_name, clock)
            except Exception as exc:
                if "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc):
                    logger.warning(f"[LAMPORT={clock}] DynamoDB ConditionalCheckFailedException para jogo ID={game_id}")
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Conflito de concorrência: o jogo '{game.title}' acabou de ser reservado por outro locatário."
                    )

        game.status = GameStatus.RENTED
        game.current_rental_id = payload.rental_id
        game.current_renter_name = payload.renter_name
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} reservado com sucesso para rental {payload.rental_id}.")
    return _save_game(game)


@app.post("/games/{game_id}/release", response_model=GamePublicResponse, tags=["Catálogo"])
def release_game(
    game_id: int,
    response: Response,
    payload: Optional[GameReleaseRequest] = None,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FB-01: Liberação atômica de exemplar alugado.
    Restaura status para AVAILABLE e limpa vínculos de locação ativa.
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Liberação de exemplar solicitada para o jogo ID={game_id}")

    with _lock:
        if game_id not in GAMES_DB:
            logger.warning(f"Jogo ID={game_id} não encontrado para liberação.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        game = GAMES_DB[game_id]
        game.status = GameStatus.AVAILABLE
        game.current_rental_id = None
        game.current_renter_name = None
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} liberado com sucesso para AVAILABLE.")
    return _save_game(game)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
