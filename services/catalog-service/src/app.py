import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from models import (
    ConsistencyMode,
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
    expose_headers=["X-Lamport-Clock", "X-Consistency-Mode", "X-DB-Read-Latency-Ms", "X-Served-By-Node"],
)

# ponytail: lock em memória por processo; migrar para DynamoDB ConditionalExpression em multi-réplica
_lock = threading.Lock()
_lamport_clock = 0

INSTANCE_ID = naming.instance_id()
DNS_TARGET = os.getenv("DNS_DISCOVERY_TARGET", DNS_TARGETS[0])


def tick_lamport(incoming: Optional[int] = None) -> int:
    global _lamport_clock
    with _lock:
        _lamport_clock = (max(_lamport_clock, incoming) if incoming is not None else _lamport_clock) + 1
        return _lamport_clock


def _resolve_dns(target: str) -> DNSResolutionInfo:
    """Resolução via naming.resolve (timeout e log [DNS]) no formato DNSResolutionInfo."""
    r = naming.resolve(target)
    return DNSResolutionInfo(
        target_hostname=r["hostname"],
        resolved_ips=r["resolved_ips"],
        status=r["status"],
        error_message=r["error"],
    )


def _get_dynamodb_status() -> DynamoDBStatusInfo:
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL") or None
    name = os.getenv("GAMES_TABLE_NAME", "gamerent_games")
    table = _get_ddb_table()
    if table is not None:
        # Qualquer endpoint explícito é o DynamoDB Local (ex.: http://dynamodb-local:8000 no Compose)
        mode = "LOCAL_DYNAMODB" if endpoint else "AWS_DYNAMODB"
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

# ponytail: scan/get_item com ConsistentRead e filtro Haversine em memória; usar GeoIndex/GSI se acervo crescer >10k itens
_ddb_table = None


def _get_ddb_table():
    global _ddb_table
    if _ddb_table is not None:
        return _ddb_table
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL") or None
    if not (os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes") or endpoint):
        return None
    try:
        import boto3
        # dynamodb-local aceita qualquer credencial; na AWS deixamos o boto3 usar a cadeia padrão
        # (IAM Role da EC2), sem injetar chaves fictícias que sobrescreveriam o Instance Profile.
        creds = (
            {
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "local"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "local"),
            }
            if endpoint
            else {}
        )
        ddb = boto3.resource(
            "dynamodb",
            region_name=os.getenv("AWS_REGION", "sa-east-1"),
            endpoint_url=endpoint,
            **creds,
        )
        name = os.getenv("GAMES_TABLE_NAME", "gamerent_games")
        try:
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
        except ddb.meta.client.exceptions.ResourceInUseException:
            # Outra réplica do catalog-service criou a tabela ao mesmo tempo
            table = ddb.Table(name)
        table.wait_until_exists()
        items = table.scan().get("Items", [])
        if not items:
            for g in GAMES_DB.values():
                _put_ddb_game(table, g)
        else:
            for it in items:
                try:
                    GAMES_DB[int(it["id"])] = Game(**it)
                except Exception:
                    pass
        _ddb_table = table
        return _ddb_table
    except Exception as exc:
        # Com USE_DYNAMODB=true (AWS) cair para memória quebra o estado compartilhado entre réplicas
        log = logger.error if os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes") else logger.warning
        log(f"DynamoDB indisponível, operando com GAMES_DB em memória: {exc}")
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


def _release_ddb_game(table, game_id: int, rental_id: Optional[str], is_forced: bool, clock: int) -> bool:
    """Liberação atômica condicional no DynamoDB: restaura status para AVAILABLE."""
    try:
        expr_names = {"#st": "status"}
        expr_vals = {
            ":avail": GameStatus.AVAILABLE.value,
            ":inc": 1,
            ":clk": clock,
            ":upd": datetime.now(timezone.utc).isoformat(),
        }
        cond = "attribute_exists(id)"
        if not is_forced and rental_id:
            cond += " AND (current_rental_id = :rid OR attribute_not_exists(current_rental_id))"
            expr_vals[":rid"] = rental_id
        table.update_item(
            Key={"id": game_id},
            UpdateExpression="SET #st = :avail, version = version + :inc, lamport_clock = :clk, updated_at = :upd REMOVE current_rental_id, current_renter_name",
            ConditionExpression=cond,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_vals,
        )
        return True
    except Exception as exc:
        if "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc):
            raise
        logger.warning(f"Erro na liberação condicional do DynamoDB para jogo {game_id}: {exc}")
        return False


def _get_game_for_mutation(game_id: int) -> Optional[Game]:
    """Obtém o jogo para mutação, sincronizando com DynamoDB com ConsistentRead."""
    table = _get_ddb_table()
    if table is not None:
        try:
            item = table.get_item(Key={"id": game_id}, ConsistentRead=True).get("Item")
            if item:
                game = Game(**item)
                GAMES_DB[game_id] = game
                return game
        except Exception as exc:
            logger.warning(f"Erro ao sincronizar jogo {game_id} do DynamoDB: {exc}")
    return GAMES_DB.get(game_id)


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
def health_check(
    response: Response = None,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """Endpoint de integridade para monitoramento (Health Check)."""
    clock = tick_lamport(x_lamport_clock)
    if response:
        response.headers["X-Lamport-Clock"] = str(clock)
    # Conta pela fonte de verdade (DynamoDB quando ativo), igual em todas as réplicas
    games, _ = _read_games("eventual")
    return {
        "status": "HEALTHY",
        "service": "catalog-service",
        "node_urn": NODE_URN,
        "instance_id": INSTANCE_ID,
        "total_games": len(games),
        "lamport_clock": clock
    }


def log_dns_resolution():
    logger.info(f"Nó {NODE_URN} iniciado")
    for target in DNS_TARGETS:
        naming.resolve(target)


# Executa uma vez ao carregar o módulo (antes de o uvicorn aceitar conexões)
log_dns_resolution()


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

    extras = naming.naming_extras(DNS_TARGETS)
    return DiscoveryResponse(
        service="catalog-service",
        node_urn=NODE_URN,
        instance_id=INSTANCE_ID,
        hostname=socket.gethostname(),
        local_ip=(extras["local_ips"] or ["127.0.0.1"])[0],
        dns_target=DNS_TARGET,
        dns_resolution=_resolve_dns(DNS_TARGET),
        lamport_clock=clock,
        dynamodb=_get_dynamodb_status(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        **extras,
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
        table = _get_ddb_table()
        max_id = max(GAMES_DB.keys(), default=0)
        if table is not None:
            try:
                items = table.scan(ProjectionExpression="id").get("Items", [])
                max_id = max(max_id, max([int(it["id"]) for it in items], default=0))
            except Exception:
                pass
        new_id = max_id + 1
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
    logger.info(f"[LAMPORT={clock}] Atualização de status do jogo ID={game_id} para {payload.status.value}")

    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        if (
            (game.status == GameStatus.RENTED and payload.status != GameStatus.AVAILABLE)
            or (game.status == GameStatus.MAINTENANCE and payload.status == GameStatus.RENTED)
        ):
            logger.warning(f"[LAMPORT={clock}] Conflito 409: tentativa de alterar jogo ID={game_id} de {game.status.value} para {payload.status.value}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transição inválida de '{game.status.value}' para '{payload.status.value}' no jogo '{game.title}'."
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
    Suporta retentativas idempotentes para a mesma locação (mesmo rental_id).
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Tentativa de reserva atômica para o jogo ID={game_id} (Rental={payload.rental_id}, Locatário={payload.renter_name})")

    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            logger.warning(f"Jogo ID={game_id} não encontrado para reserva.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        # Idempotência: se já estiver RENTED para o mesmo rental_id, confirma sem erro
        if game.status == GameStatus.RENTED and game.current_rental_id == payload.rental_id:
            logger.info(f"[LAMPORT={clock}] Retentativa idempotente de reserva confirmada para jogo ID={game_id} (Rental={payload.rental_id}).")
            return _save_game(game)

        if game.status != GameStatus.AVAILABLE:
            logger.warning(f"[LAMPORT={clock}] Conflito 409: Jogo ID={game_id} indisponível para reserva (status atual: {game.status.value})")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"O jogo '{game.title}' não está disponível para reserva no momento (status atual: {game.status.value})."
            )

        prev_status = game.status
        prev_rental = game.current_rental_id
        prev_renter = game.current_renter_name
        prev_ver = game.version

        game.status = GameStatus.RENTED
        game.current_rental_id = payload.rental_id
        game.current_renter_name = payload.renter_name
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    # I/O DynamoDB executado fora do lock em memória para evitar thread starvation
    table = _get_ddb_table()
    if table is not None:
        try:
            _reserve_ddb_game(table, game_id, payload.rental_id, payload.renter_name, clock)
        except Exception as exc:
            with _lock:
                game.status = prev_status
                game.current_rental_id = prev_rental
                game.current_renter_name = prev_renter
                game.version = prev_ver
            if "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc):
                # Sincroniza estado real do DynamoDB em caso de disputa concorrente
                _get_game_for_mutation(game_id)
                logger.warning(f"[LAMPORT={clock}] DynamoDB ConditionalCheckFailedException para jogo ID={game_id}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Conflito de concorrência: o jogo '{game.title}' acabou de ser reservado por outro locatário."
                )
            logger.warning(f"Erro ao persistir reserva no DynamoDB: {exc}")

    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} reservado com sucesso para rental {payload.rental_id}.")
    return _save_game(game)


@app.post("/games/{game_id}/release", response_model=GamePublicResponse, tags=["Catálogo"])
def release_game(
    game_id: int,
    response: Response,
    payload: Optional[GameReleaseRequest] = None,
    force: bool = Query(False, description="Liberação administrativa forçada ignorando validação de rental_id"),
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FB-01: Liberação atômica de exemplar alugado.
    Restaura status para AVAILABLE e limpa vínculos de locação ativa.
    Exige validação do rental_id da locação ativa para prevenir liberações desautorizadas.
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Liberação de exemplar solicitada para o jogo ID={game_id}")

    is_forced = force or (payload.force if payload else False)

    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            logger.warning(f"Jogo ID={game_id} não encontrado para liberação.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Jogo com ID {game_id} não encontrado no catálogo."
            )

        # Validação de segurança: se o jogo estiver RENTED com um rental_id ativo,
        # exige confirmação do rental_id correspondente (salvo se liberação forçada)
        if not is_forced and game.status == GameStatus.RENTED and game.current_rental_id:
            provided_rental_id = payload.rental_id if payload else None
            if not provided_rental_id or provided_rental_id != game.current_rental_id:
                logger.warning(
                    f"[LAMPORT={clock}] Conflito 409 na liberação: rental_id fornecido '{provided_rental_id}' "
                    f"não coincide com a locação ativa '{game.current_rental_id}' do jogo ID={game_id}."
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operação negada: o rental_id informado não corresponde à locação ativa do jogo '{game.title}'."
                )

        game.status = GameStatus.AVAILABLE
        game.current_rental_id = None
        game.current_renter_name = None
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    table = _get_ddb_table()
    if table is not None:
        try:
            _release_ddb_game(table, game_id, payload.rental_id if payload else None, is_forced, clock)
        except Exception as exc:
            if "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Operação negada: o rental_id informado não corresponde à locação ativa do jogo '{game.title}'."
                )
            logger.warning(f"Erro ao persistir liberação no DynamoDB: {exc}")

    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} liberado com sucesso para AVAILABLE.")
    return GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
