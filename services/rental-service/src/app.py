import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from models import (
    DiscoveryResponse,
    DNSResolutionInfo,
    DynamoDBStatusInfo,
    RentalCreateRequest,
    RentalResponse,
    RentalStatus,
)
from database import repository
from catalog_client import (
    CatalogClient,
    CatalogCommunicationError,
    GameConflictError,
    GameNotFoundError,
)
import naming
import auth

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [RENTAL-SERVICE] %(message)s"
)
logger = logging.getLogger("rental-service")

app = FastAPI(
    title="GameRent — Rental Service",
    description="Microsserviço de Orquestração de Reservas e Locação com Comunicação Inter-Serviços.",
    version="1.0.0"
)

app.add_middleware(CORSMiddleware, **auth.cors_settings())

_lock = threading.Lock()
_lamport_clock = 0

SERVICE_NAME = "rental-service"
INSTANCE_ID = naming.instance_id()
NODE_URN = naming.node_urn(SERVICE_NAME, INSTANCE_ID)
DNS_TARGET = os.getenv("DNS_DISCOVERY_TARGET", os.getenv("CATALOG_SERVICE_URL", f"catalog.{naming.INTERNAL_DOMAIN}"))
# dns[0] é o catálogo (o que este nó precisa achar); depois o próprio nome do rental
DNS_TARGETS = [DNS_TARGET, f"rental.{naming.INTERNAL_DOMAIN}"]


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
    name = os.getenv("RENTALS_TABLE_NAME", "gamerent_rentals")
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


# Inicializa o cliente de comunicação com o Catalog-Service
catalog_client = CatalogClient()

# Base em memória para reservas
RENTALS_DB: Dict[str, dict] = {}


def _get_ddb_table():
    """Retorna a tabela do DynamoDB via repositório (database.py).

    A criação automática da tabela ``gamerent_rentals`` fica no repositório; aqui apenas
    devolvemos a referência (``None`` quando o banco não está configurado/indisponível).
    """
    return repository.table


def _save_rental(record: dict) -> RentalResponse:
    rental_id = record["rental_id"]
    RENTALS_DB[rental_id] = record
    if repository.connected:
        try:
            repository.put_rental(record)
        except Exception as exc:
            logger.warning(f"Falha ao persistir locação {rental_id} no DynamoDB: {exc}")
    return RentalResponse(**record)


def _find_rentals(
    renter_email: Optional[str] = None,
    game_id: Optional[int] = None,
    status_filter: Optional[RentalStatus] = None
) -> List[dict]:
    """Consulta locações no DynamoDB ou na memória local com suporte a múltiplos predicados de filtro."""
    if repository.connected:
        try:
            items = repository.scan_rentals(
                renter_email=renter_email,
                game_id=game_id,
                status_filter=status_filter,
            )
            for item in items:
                RENTALS_DB[item["rental_id"]] = item
            return items
        except Exception as exc:
            logger.warning(f"Falha ao consultar DynamoDB, utilizando base em memória: {exc}")

    # Fallback em memória local
    status_val = status_filter.value if isinstance(status_filter, RentalStatus) else (str(status_filter) if status_filter else None)
    return [
        r for r in RENTALS_DB.values()
        if (not renter_email or r.get("renter_email") == renter_email)
        and (game_id is None or r.get("game_id") == game_id)
        and (not status_val or (r.get("status").value if isinstance(r.get("status"), RentalStatus) else r.get("status")) == status_val)
    ]


@app.get("/health", tags=["Monitoramento"])
def health_check(
    response: Response = None,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """Health check do rental-service."""
    clock = tick_lamport(x_lamport_clock)
    if response:
        response.headers["X-Lamport-Clock"] = str(clock)
    return {
        "status": "HEALTHY",
        "service": "rental-service",
        "node_urn": NODE_URN,
        "instance_id": INSTANCE_ID,
        "total_rentals": len(RENTALS_DB),
        "target_catalog_url": catalog_client.base_url,
        "lamport_clock": clock
    }

def log_dns_resolution():
    logger.info(f"Nó {NODE_URN} iniciado; catálogo em {catalog_client.base_url}")
    naming.resolve(catalog_client.base_url)


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
        service="rental-service",
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


@app.post("/rentals", response_model=RentalResponse, status_code=status.HTTP_201_CREATED, tags=["Locações"])
async def create_rental(
    payload: RentalCreateRequest,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None),
    user: Optional[auth.User] = Depends(auth.require_user),
):
    """
    FA-03 / FA-04 / FB-01: Cria uma nova locação atômica de jogo de tabuleiro.
    Elimina condição de corrida (double-booking) delegando a reserva em chamada atômica única
    ao catalog-service via POST /games/{id}/reserve.
    """
    if user is not None and not user.is_admin:
        # O locatário é quem está logado; o admin pode informar outro (ex.: simulador de disputa)
        payload = payload.model_copy(update={"renter_email": user.email, "renter_name": payload.renter_name or user.name})
    clock = tick_lamport(x_lamport_clock)
    rental_id = str(uuid.uuid4())
    logger.info(f"[LAMPORT={clock}] Solicitação de aluguel: Jogo {payload.game_id} por {payload.renter_name} (Rental={rental_id})")

    # Chamada atômica de reserva com propagação de Lamport
    try:
        game_data = await catalog_client.reserve_game(
            game_id=payload.game_id,
            rental_id=rental_id,
            renter_name=payload.renter_name,
            renter_email=payload.renter_email,
            lamport_clock=clock
        )
    except GameConflictError as exc:
        # Rejeição imediata com 409 Conflict
        logger.warning(f"[LAMPORT={clock}] Reserva rejeitada com 409 Conflict: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
            headers={"X-Lamport-Clock": str(clock)}
        )
    except GameNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Lamport-Clock": str(clock)}
        )
    except CatalogCommunicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha de comunicação inter-serviços: {exc}",
            headers={"X-Lamport-Clock": str(clock)}
        )

    # Sincroniza o relógio de Lamport com o relógio retornado pelo catálogo
    resp_clock = game_data.get("lamport_clock")
    clock = tick_lamport(resp_clock)
    response.headers["X-Lamport-Clock"] = str(clock)

    daily_rate = float(game_data.get("price_per_day", 0.0))
    total_price = round(daily_rate * payload.rental_days, 2)
    created_at_iso = datetime.now(timezone.utc).isoformat()

    rental_record = {
        "rental_id": rental_id,
        "urn": f"urn:gamerent:rental:{rental_id}",
        "game_id": payload.game_id,
        "game_urn": game_data.get("urn", f"urn:gamerent:game:sa-east-1:{payload.game_id}"),
        "game_title": game_data.get("title", ""),
        "renter_name": payload.renter_name,
        "renter_email": payload.renter_email,
        "rental_days": payload.rental_days,
        "daily_rate": daily_rate,
        "total_price": total_price,
        "status": RentalStatus.CONFIRMED,
        "lamport_clock": clock,
        "created_at": created_at_iso,
        # URN canônico vem do catálogo (dono do recurso), não é recalculado com a região deste nó
        "game_urn": game_data.get("urn", ""),
        "returned_at": None
    }

    try:
        resp_obj = _save_rental(rental_record)
    except Exception as exc:
        logger.error(f"[LAMPORT={clock}] Falha ao persistir locação {rental_id}: {exc}. Executando rollback compensatório no catálogo.")
        try:
            await catalog_client.release_game(
                game_id=payload.game_id,
                rental_id=rental_id,
                lamport_clock=clock
            )
        except Exception as rollback_err:
            logger.critical(f"Falha catastrófica ao tentar compensar reserva do jogo {payload.game_id}: {rollback_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao registrar locação. A reserva do exemplar foi cancelada: {exc}",
            headers={"X-Lamport-Clock": str(clock)}
        )

    logger.info(f"[LAMPORT={clock}] Aluguel confirmado com sucesso! ID={rental_id}, URN={resp_obj.urn}, Total=R$ {total_price}")
    return resp_obj


@app.get("/rentals", response_model=List[RentalResponse], tags=["Locações"])
def list_rentals(
    response: Response,
    renter_email: Optional[str] = Query(None, description="FB-02: Filtra locações pelo e-mail do locatário (Painel 'Meus Aluguéis')"),
    game_id: Optional[int] = Query(None, description="FB-02: Filtra histórico de locações pelo ID do jogo (Visão do Locador)"),
    status: Optional[RentalStatus] = Query(None, description="Filtra por status da locação (CONFIRMED, COMPLETED, CANCELLED)"),
    x_lamport_clock: Optional[int] = Header(default=None),
    user: Optional[auth.User] = Depends(auth.require_user),
):
    """
    FB-02: Consulta reservas registradas com suporte a filtros combináveis por locatário, jogo e status.
    Atende ao painel 'Meus Aluguéis' (Locatário) e ao histórico de locações (Locador).
    """
    if user is not None and not user.is_admin:
        renter_email = user.email  # cada locatário só vê as próprias locações
    clock = tick_lamport(x_lamport_clock)
    response.headers["X-Lamport-Clock"] = str(clock)
    logger.info(f"[LAMPORT={clock}] Consulta de locações: renter_email={renter_email}, game_id={game_id}, status={status}")

    records = _find_rentals(renter_email=renter_email, game_id=game_id, status_filter=status)
    return [RentalResponse(**r) for r in records]


def _ensure_owner(rental: dict, user: Optional[auth.User]) -> None:
    """Com login ativo, só o locatário da reserva (ou um admin) pode vê-la ou devolvê-la."""
    if user is None or user.is_admin:
        return
    if (rental.get("renter_email") or "").lower() != user.email:
        # 404 em vez de 403: não revela que a locação existe
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Locação não encontrada.")


@app.get("/rentals/{rental_id}", response_model=RentalResponse, tags=["Locações"])
def get_rental(rental_id: str, user: Optional[auth.User] = Depends(auth.require_user)):
    """Consulta detalhes de uma locação específica."""
    if rental_id not in RENTALS_DB:
        if repository.connected:
            try:
                item = repository.get_rental(rental_id)
                if item:
                    RENTALS_DB[rental_id] = item
            except Exception as exc:
                logger.warning(f"Falha ao buscar locação {rental_id} no DynamoDB: {exc}")

    if rental_id not in RENTALS_DB:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locação com ID {rental_id} não encontrada."
        )
    _ensure_owner(RENTALS_DB[rental_id], user)
    return RentalResponse(**RENTALS_DB[rental_id])


@app.post("/rentals/{rental_id}/return", response_model=RentalResponse, tags=["Locações"])
async def return_rental(
    rental_id: str,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None),
    user: Optional[auth.User] = Depends(auth.require_user),
):
    """
    FB-01 / FB-03: Finaliza a locação e comunica o catalog-service via /release para liberar o exemplar.
    Idempotente: se já estiver COMPLETED, retorna o estado final sem duplicar chamadas de liberação.
    """
    clock = tick_lamport(x_lamport_clock)

    if rental_id not in RENTALS_DB:
        if repository.connected:
            try:
                item = repository.get_rental(rental_id)
                if item:
                    RENTALS_DB[rental_id] = item
            except Exception as exc:
                logger.warning(f"Falha ao recuperar locação {rental_id} no DynamoDB: {exc}")

    if rental_id not in RENTALS_DB:
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Locação com ID {rental_id} não encontrada.")

    rental = RENTALS_DB[rental_id]
    _ensure_owner(rental, user)
    current_status = rental.get("status")
    if current_status == RentalStatus.COMPLETED or current_status == "COMPLETED":
        response.headers["X-Lamport-Clock"] = str(clock)
        logger.info(f"[LAMPORT={clock}] Locação {rental_id} já finalizada anteriormente (retorno idempotente).")
        return RentalResponse(**rental)

    # Libera jogo atomicamente no catálogo remoto
    try:
        release_data = await catalog_client.release_game(
            game_id=rental["game_id"],
            rental_id=rental_id,
            lamport_clock=clock
        )
        resp_clock = release_data.get("lamport_clock")
        clock = tick_lamport(resp_clock)
    except GameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
            headers={"X-Lamport-Clock": str(clock)}
        )
    except GameNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Lamport-Clock": str(clock)}
        )
    except Exception as exc:
        logger.error(f"Erro ao liberar jogo {rental['game_id']} no catálogo: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Não foi possível liberar o jogo no catálogo: {exc}",
            headers={"X-Lamport-Clock": str(clock)}
        )

    rental["status"] = RentalStatus.COMPLETED
    rental["returned_at"] = datetime.now(timezone.utc).isoformat()
    rental["lamport_clock"] = clock
    response.headers["X-Lamport-Clock"] = str(clock)

    resp_obj = _save_rental(rental)
    logger.info(f"[LAMPORT={clock}] Locação {rental_id} finalizada com sucesso. Jogo {rental['game_id']} liberado no catálogo.")
    return resp_obj


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
