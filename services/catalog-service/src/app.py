import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
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
from database import build_seed_games, repository, is_conditional_failure
from geo_utils import calculate_haversine_distance
import naming
import auth

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

# Caracteres de controle (0x00-0x1F inclui \n, \r, \t e ESC/ANSI) + DEL: removidos de valores
# controlados pelo usuário antes de logar, prevenindo log injection.
_CONTROL_CHARS = dict.fromkeys(range(0x20))
_CONTROL_CHARS[0x7F] = None


def _log_safe(value) -> str:
    """Sanitiza um valor livre (ex.: renter_name/renter_email) antes de registrá-lo nos logs."""
    return str(value).translate(_CONTROL_CHARS)


app = FastAPI(
    title="GameRent — Catalog Service",
    description="Microsserviço de Catálogo e Cálculo de Proximidade Relativa de Jogos de Tabuleiro.",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, **auth.cors_settings())

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


# Base de dados em memória (fallback quando o DynamoDB está indisponível). A fonte de
# verdade é o Amazon DynamoDB; GAMES_DB nasce do seed (build_seed_games) e é sincronizado
# com a tabela na primeira conexão bem-sucedida.
GAMES_DB: dict[int, Game] = build_seed_games()

# ponytail: scan/get_item com ConsistentRead e filtro Haversine em memória; usar GeoIndex/GSI se acervo crescer >10k itens
_games_db_loaded = False


def _get_ddb_table():
    """Retorna a tabela do DynamoDB via repositório e sincroniza o GAMES_DB na 1ª conexão.

    A criação automática da tabela e o seed inicial ficam no repositório (database.py);
    aqui apenas espelhamos o conteúdo persistido no fallback em memória (GAMES_DB).
    """
    global _games_db_loaded
    table = repository.table
    if table is not None and not _games_db_loaded:
        _games_db_loaded = True
        for it in repository.scan_items(consistent=False):
            try:
                GAMES_DB[int(it["id"])] = Game(**it)
            except Exception:
                pass
    return table


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or None
# Na AWS o DynamoDB é gerenciado e DYNAMODB_ENDPOINT_URL fica vazio; no ambiente local
# o endpoint aponta para o dynamodb-local. Sem ADMIN_TOKEN, liberação forçada só é
# permitida no desenvolvimento local.
PRODUCTION_AWS = (
    os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes")
    and not os.getenv("DYNAMODB_ENDPOINT_URL")
)
if ADMIN_TOKEN is None:
    if PRODUCTION_AWS:
        logger.error("ADMIN_TOKEN não definido: liberação forçada (force=true) DESABILITADA na AWS.")
    else:
        logger.warning("ADMIN_TOKEN não definido: liberação forçada (force=true) aceita sem autenticação (modo de desenvolvimento).")

# Footgun de deploy: em produção (AWS) o AUTH_PROVIDER deve ser 'cognito'. Com 'none', a
# autorização de force=true passa a depender só de ADMIN_TOKEN; sinalize com clareza.
if PRODUCTION_AWS and auth.AUTH_PROVIDER != "cognito":
    logger.error(
        "PRODUCTION_AWS ativo com AUTH_PROVIDER=%r: use AUTH_PROVIDER=cognito e defina ADMIN_TOKEN "
        "em produção (a liberação forçada fica desabilitada se ADMIN_TOKEN estiver ausente).",
        auth.AUTH_PROVIDER,
    )


def _authorize_forced_release(x_admin_token: Optional[str]) -> None:
    """force=true ignora o rental_id ativo; exige X-Admin-Token quando configurado.

    Com AUTH_PROVIDER=cognito, auth.require_admin já validou admin/token antes desta função.
    """
    if auth.AUTH_PROVIDER == "cognito":
        return
    if ADMIN_TOKEN is not None:
        # Comparação em tempo constante (hmac.compare_digest) para não vazar o segredo por timing.
        if not auth.verify_admin_token(x_admin_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Liberação forçada exige o header X-Admin-Token válido.",
            )
    elif PRODUCTION_AWS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Liberação forçada desabilitada: configure ADMIN_TOKEN no ambiente.",
        )


def _get_game_for_mutation(game_id: int) -> Optional[Game]:
    """Obtém o jogo para mutação, sincronizando com DynamoDB com ConsistentRead."""
    table = _get_ddb_table()
    if table is not None:
        try:
            item = repository.get_item(game_id, consistent=True)
            if item:
                game = Game(**item)
                GAMES_DB[game_id] = game
                return game
        except Exception as exc:
            logger.warning(f"Erro ao sincronizar jogo {game_id} do DynamoDB: {exc}")
    return GAMES_DB.get(game_id)


def _read_games(consistency: ConsistencyMode) -> tuple[list[Game], float]:
    table = _get_ddb_table()
    t0 = time.perf_counter()
    if table is not None:
        try:
            items = repository.scan_items(consistent=(consistency == "strong"))
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
            item = repository.get_item(game_id, consistent=(consistency == "strong"))
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
    x_lamport_clock: Optional[int] = Header(default=None),
    _admin: Optional[auth.User] = Depends(auth.require_admin),
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
    x_lamport_clock: Optional[int] = Header(default=None),
    user: Optional[auth.User] = Depends(auth.require_user),
):
    """FA-01: Cadastra um novo jogo de tabuleiro pelo locador sem expor coordenadas de GPS."""
    if user is not None and not user.is_admin:
        # O dono do anúncio é quem está logado, não o que veio no corpo
        payload = payload.model_copy(update={"owner_id": user.sub, "owner_name": payload.owner_name or user.name})
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    with _lock:
        table = _get_ddb_table()
        max_id = max(GAMES_DB.keys(), default=0)
        if table is None:
            new_id = max_id + 1
            game = Game(id=new_id, lamport_clock=clock, **payload.model_dump())
            GAMES_DB[new_id] = game
        else:
            # O scan dá um palpite; a gravação condicional (attribute_not_exists) garante que duas
            # réplicas nunca fiquem com o mesmo ID: quem perde a corrida tenta o próximo.
            try:
                existing_ids = repository.scan_ids()
                max_id = max(max_id, max(existing_ids, default=0))
            except Exception as exc:
                logger.warning(f"Falha ao consultar maior ID no DynamoDB: {exc}")
            game = None
            for attempt in range(10):
                candidate = Game(id=max_id + 1 + attempt, lamport_clock=clock, **payload.model_dump())
                try:
                    repository.put_game(candidate, condition={"ConditionExpression": "attribute_not_exists(id)"})
                    game = candidate
                    break
                except Exception as exc:
                    if not is_conditional_failure(exc):
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Falha ao persistir o jogo no DynamoDB: {exc}",
                        )
            if game is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Não foi possível reservar um ID livre para o jogo; tente novamente.",
                )
            GAMES_DB[game.id] = game
    logger.info(f"[LAMPORT={clock}] Novo jogo cadastrado: ID={game.id}, URN={game.urn}")
    return GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN)


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


def _core_update_status(
    game_id: int,
    new_status: GameStatus,
    clock: int,
    user: Optional[auth.User] = None,
) -> dict:
    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            logger.warning(f"Jogo ID={game_id} não encontrado para atualização de status.")
            return {"status": 404, "detail": f"Jogo com ID {game_id} não encontrado no catálogo.", "lamport_clock": clock}

        if user is not None and not user.is_admin and game.owner_id != user.sub:
            return {
                "status": 403,
                "detail": "Só o dono do anúncio pode alterar o status deste jogo.",
                "lamport_clock": clock,
            }

        if (
            (game.status == GameStatus.RENTED and new_status != GameStatus.AVAILABLE)
            or (game.status == GameStatus.MAINTENANCE and new_status == GameStatus.RENTED)
        ):
            logger.warning(f"[LAMPORT={clock}] Conflito 409: tentativa de alterar jogo ID={game_id} de {game.status.value} para {new_status.value}")
            return {
                "status": 409,
                "detail": f"Transição inválida de '{game.status.value}' para '{new_status.value}' no jogo '{game.title}'.",
                "lamport_clock": clock,
            }

        expected_version = game.version
        game.status = new_status
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

        table = _get_ddb_table()
        if table is not None:
            # Controle otimista: só grava se ninguém (outra réplica, uma reserva) mudou o item
            # desde a leitura forte acima. Sem isso, o put_item sobrescreve uma reserva concorrente.
            try:
                repository.put_game(game, condition={
                    "ConditionExpression": "#v = :expected",
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {":expected": expected_version},
                })
            except Exception as exc:
                _get_game_for_mutation(game_id)  # descarta a mudança local e recarrega o estado real
                if is_conditional_failure(exc):
                    logger.warning(f"[LAMPORT={clock}] Conflito 409: jogo ID={game_id} mudou durante a atualização de status")
                    return {
                        "status": 409,
                        "detail": f"O jogo '{game.title}' foi alterado por outra operação; atualize e tente novamente.",
                        "lamport_clock": clock,
                    }
                return {
                    "status": 503,
                    "detail": f"Falha ao persistir o status no DynamoDB: {exc}",
                    "lamport_clock": clock,
                }
    return {"status": 200, "data": GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN).model_dump(), "lamport_clock": clock}


@app.patch("/games/{game_id}/status", response_model=GamePublicResponse, tags=["Catálogo"])
def update_game_status(
    game_id: int,
    payload: StatusUpdatePayload,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None),
    user: Optional[auth.User] = Depends(auth.require_user),
):
    """
    FA-05: Atualiza o status do jogo (bloqueia com 409 Conflict se estiver RENTED
    e tentar ir para MAINTENANCE ou ser locado novamente, permitindo devolução para AVAILABLE).
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Atualização de status do jogo ID={game_id} para {payload.status.value}")
    res = _core_update_status(game_id, payload.status, clock, user=user)
    if res["status"] != 200:
        raise HTTPException(status_code=res["status"], detail=res["detail"])
    return res["data"]


def _core_reserve(game_id: int, rental_id: str, renter_name: str, clock: int) -> dict:
    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            logger.warning(f"Jogo ID={game_id} não encontrado para reserva.")
            return {"status": 404, "detail": f"Jogo com ID {game_id} não encontrado no catálogo.", "lamport_clock": clock}

        # Idempotência: se já estiver RENTED para o mesmo rental_id, confirma sem erro
        if game.status == GameStatus.RENTED and game.current_rental_id == rental_id:
            logger.info(f"[LAMPORT={clock}] Retentativa idempotente de reserva confirmada para jogo ID={game_id} (Rental={rental_id}).")
            return {
                "status": 200,
                "data": GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN).model_dump(),
                "lamport_clock": clock,
            }

        if game.status != GameStatus.AVAILABLE:
            logger.warning(f"[LAMPORT={clock}] Conflito 409: Jogo ID={game_id} indisponível para reserva (status atual: {game.status.value})")
            return {"status": 409, "detail": f"O jogo '{game.title}' não está disponível para reserva no momento (status atual: {game.status.value}).", "lamport_clock": clock}

        prev_status = game.status
        prev_rental = game.current_rental_id
        prev_renter = game.current_renter_name
        prev_ver = game.version

        game.status = GameStatus.RENTED
        game.current_rental_id = rental_id
        game.current_renter_name = renter_name
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    # I/O DynamoDB executado fora do lock em memória para evitar thread starvation
    table = _get_ddb_table()
    if table is not None:
        try:
            repository.reserve_game_atomically(game_id, rental_id, clock, renter_name)
        except Exception as exc:
            with _lock:
                game.status = prev_status
                game.current_rental_id = prev_rental
                game.current_renter_name = prev_renter
                game.version = prev_ver
            if is_conditional_failure(exc):
                # Sincroniza estado real do DynamoDB em caso de disputa concorrente
                _get_game_for_mutation(game_id)
                logger.warning(f"[LAMPORT={clock}] DynamoDB ConditionalCheckFailedException para jogo ID={game_id}")
                return {"status": 409, "detail": f"Conflito de concorrência: o jogo '{game.title}' acabou de ser reservado por outro locatário.", "lamport_clock": clock}
            logger.warning(f"Erro ao persistir reserva no DynamoDB: {exc}")
            return {"status": 503, "detail": f"Falha ao persistir a reserva no DynamoDB: {exc}", "lamport_clock": clock}

    if table is not None:
        # Não reescrever o item de forma incondicional: a reserva já foi aplicada pelo
        # update condicional acima. Relê o estado canônico para responder sem lost update.
        game = _get_game_for_mutation(game_id) or game
    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} reservado com sucesso para rental {rental_id}.")
    return {
        "status": 200,
        "data": GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN).model_dump(),
        "lamport_clock": clock,
    }


@app.post("/games/{game_id}/reserve", response_model=GamePublicResponse, tags=["Catálogo"])
def reserve_game(
    game_id: int,
    payload: GameReserveRequest,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None),
    _internal: None = Depends(auth.require_service_or_admin),
):
    """
    FA-03 / FA-04: Reserva atômica de exemplar para locação.
    Garante exclusão mútua: se o jogo não estiver AVAILABLE, rejeita imediatamente com 409 Conflict.
    Suporta retentativas idempotentes para a mesma locação (mesmo rental_id).
    """
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Tentativa de reserva atômica para o jogo ID={game_id} (Rental={_log_safe(payload.rental_id)}, Locatário={_log_safe(payload.renter_name)})")
    res = _core_reserve(game_id, payload.rental_id, payload.renter_name, clock)
    if res["status"] != 200:
        raise HTTPException(status_code=res["status"], detail=res["detail"])
    return res["data"]


def _core_release(game_id: int, rental_id: Optional[str], is_forced: bool, clock: int) -> dict:
    with _lock:
        game = _get_game_for_mutation(game_id)
        if game is None:
            logger.warning(f"Jogo ID={game_id} não encontrado para liberação.")
            return {"status": 404, "detail": f"Jogo com ID {game_id} não encontrado no catálogo.", "lamport_clock": clock}

        # Validação de segurança: se o jogo estiver RENTED com um rental_id ativo,
        # exige confirmação do rental_id correspondente (salvo se liberação forçada)
        if not is_forced and game.status == GameStatus.RENTED and game.current_rental_id:
            if not rental_id or rental_id != game.current_rental_id:
                logger.warning(
                    f"[LAMPORT={clock}] Conflito 409 na liberação: rental_id fornecido '{rental_id}' "
                    f"não coincide com a locação ativa '{game.current_rental_id}' do jogo ID={game_id}."
                )
                return {
                    "status": 409,
                    "detail": f"Operação negada: o rental_id informado não corresponde à locação ativa do jogo '{game.title}'.",
                    "lamport_clock": clock,
                }

        prev_status = game.status
        prev_rental = game.current_rental_id
        prev_renter = game.current_renter_name
        prev_version = game.version
        prev_clock = game.lamport_clock
        prev_updated_at = game.updated_at

        game.status = GameStatus.AVAILABLE
        game.current_rental_id = None
        game.current_renter_name = None
        game.version += 1
        game.lamport_clock = clock
        game.updated_at = datetime.now(timezone.utc).isoformat()

    table = _get_ddb_table()
    if table is not None:
        try:
            repository.release_game_atomically(game_id, clock, rental_id=rental_id, is_forced=is_forced)
        except Exception as exc:
            with _lock:
                game.status = prev_status
                game.current_rental_id = prev_rental
                game.current_renter_name = prev_renter
                game.version = prev_version
                game.lamport_clock = prev_clock
                game.updated_at = prev_updated_at
            if is_conditional_failure(exc):
                # A liberação local já foi desfeita; recarrega o estado canônico do DynamoDB
                _get_game_for_mutation(game_id)
                return {
                    "status": 409,
                    "detail": f"Operação negada: o rental_id informado não corresponde à locação ativa do jogo '{game.title}'.",
                    "lamport_clock": clock,
                }
            logger.warning(f"Erro ao persistir liberação no DynamoDB: {exc}")
            return {"status": 503, "detail": f"Falha ao persistir a liberação no DynamoDB: {exc}", "lamport_clock": clock}
        game = _get_game_for_mutation(game_id) or game

    logger.info(f"[LAMPORT={clock}] Jogo ID={game_id} liberado com sucesso para AVAILABLE.")
    return {"status": 200, "data": GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN).model_dump(), "lamport_clock": clock}


@app.post("/games/{game_id}/release", response_model=GamePublicResponse, tags=["Catálogo"])
def release_game(
    game_id: int,
    response: Response,
    payload: Optional[GameReleaseRequest] = None,
    force: bool = Query(False, description="Liberação administrativa forçada ignorando validação de rental_id"),
    x_lamport_clock: Optional[int] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
    _internal: None = Depends(auth.require_service_or_admin),
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
    if is_forced:
        # Ignora o rental_id ativo: só administradores (grupo admin do Cognito ou X-Admin-Token)
        auth.require_admin(authorization=authorization, x_admin_token=x_admin_token)
        _authorize_forced_release(x_admin_token)
    rental_id = payload.rental_id if payload else None
    res = _core_release(game_id, rental_id, is_forced, clock)
    if res["status"] != 200:
        raise HTTPException(status_code=res["status"], detail=res["detail"])
    return res["data"]


# ---------------------------------------------------------
# Consumidor Amazon SQS para comunicação inter-serviços
# ---------------------------------------------------------
def _get_sqs_client():
    import boto3
    endpoint = os.getenv("SQS_ENDPOINT_URL") or None
    region = os.getenv("AWS_REGION", "sa-east-1")
    creds = {"aws_access_key_id": "local", "aws_secret_access_key": "local"} if endpoint else {}
    return boto3.client("sqs", endpoint_url=endpoint, region_name=region, **creds)


def _normalize_sqs_url(queue_url: str, endpoint: Optional[str]) -> str:
    if endpoint and "://" in queue_url:
        from urllib.parse import urlparse, urlunparse
        end_p = urlparse(endpoint)
        q_p = urlparse(queue_url)
        return urlunparse(q_p._replace(scheme=end_p.scheme, netloc=end_p.netloc))
    return queue_url


def _get_or_create_sqs_queue(sqs, name: str, endpoint: Optional[str]) -> str:
    try:
        url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    except Exception:
        try:
            url = sqs.create_queue(QueueName=name)["QueueUrl"]
        except Exception:
            # Corrida entre processos: outra instância pode ter criado a fila neste instante
            url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    return _normalize_sqs_url(url, endpoint)


def _sqs_worker():
    import json
    endpoint = os.getenv("SQS_ENDPOINT_URL") or None
    req_queue_name = os.getenv("CATALOG_REQUESTS_QUEUE_NAME", "gamerent_catalog_requests")
    sqs = None
    req_url = None

    while True:
        try:
            sqs = _get_sqs_client()
            req_url = _get_or_create_sqs_queue(sqs, req_queue_name, endpoint)
            logger.info(f"Consumidor SQS do Catálogo ativo na fila: {req_url}")
            break
        except Exception as exc:
            logger.warning(f"Aguardando inicialização da fila SQS {req_queue_name}: {exc}")
            time.sleep(2)

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=req_url,
                MaxNumberOfMessages=5,
                WaitTimeSeconds=2,
            )
            for msg in resp.get("Messages", []):
                receipt = msg["ReceiptHandle"]
                try:
                    body = json.loads(msg["Body"])
                    corr_id = body.get("correlation_id")
                    reply_to = body.get("reply_to")
                    if reply_to:
                        reply_to = _normalize_sqs_url(reply_to, endpoint)
                    action = body.get("action")
                    payload = body.get("payload", {})
                    clock = tick_lamport(payload.get("lamport_clock"))

                    # Autenticação da mensagem (espelha auth.require_service_or_admin das rotas HTTP):
                    # com SERVICE_TOKEN configurado, qualquer ação exige o token no corpo da mensagem.
                    if not auth.verify_service_token(body.get("service_token")):
                        res = {"status": 403, "detail": "Mensagem SQS rejeitada: service_token ausente ou inválido.", "lamport_clock": clock}
                    elif action == "set_status":
                        # set_status exige contexto de dono (auth.require_user + checagem de owner no
                        # HTTP). Via SQS não existe esse contexto, então negar evita escalada de privilégio.
                        res = {"status": 403, "detail": "Atualização de status não é permitida via SQS; use o endpoint HTTP autenticado.", "lamport_clock": clock}
                    elif action == "reserve":
                        res = _core_reserve(payload["game_id"], payload["rental_id"], payload["renter_name"], clock)
                    elif action == "release":
                        if payload.get("force"):
                            # A liberação forçada ignora a locação ativa e não deve ser aceita
                            # por mensageria interna; use o endpoint HTTP com ADMIN_TOKEN.
                            res = {"status": 403, "detail": "Liberação forçada não é permitida via SQS.", "lamport_clock": clock}
                        else:
                            res = _core_release(payload["game_id"], payload.get("rental_id"), False, clock)
                    elif action == "get_game":
                        gid = payload["game_id"]
                        game, _ = _read_game(gid, "strong")
                        if game is None:
                            res = {"status": 404, "detail": f"Jogo {gid} não encontrado.", "lamport_clock": clock}
                        else:
                            res = {"status": 200, "data": GamePublicResponse(**game.model_dump(), served_by_node=NODE_URN).model_dump(), "lamport_clock": clock}
                    else:
                        res = {"status": 400, "detail": f"Ação desconhecida: {action}", "lamport_clock": clock}

                    if reply_to and corr_id:
                        res["correlation_id"] = corr_id
                        sqs.send_message(QueueUrl=reply_to, MessageBody=json.dumps(res))
                except Exception as exc:
                    logger.error(f"Erro processando mensagem SQS no catálogo: {exc}")
                finally:
                    sqs.delete_message(QueueUrl=req_url, ReceiptHandle=receipt)
        except Exception:
            time.sleep(1)


if os.getenv("ENABLE_SQS_CONSUMER", "true").lower() in ("1", "true", "yes"):
    threading.Thread(target=_sqs_worker, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
