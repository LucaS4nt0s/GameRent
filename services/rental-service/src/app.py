import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from models import RentalCreateRequest, RentalResponse, RentalStatus
from catalog_client import (
    CatalogClient,
    CatalogCommunicationError,
    GameConflictError,
    GameNotFoundError,
)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_lamport_clock = 0


def tick_lamport(incoming: Optional[int] = None) -> int:
    global _lamport_clock
    with _lock:
        _lamport_clock = (max(_lamport_clock, incoming) if incoming is not None else _lamport_clock) + 1
        return _lamport_clock


# Inicializa o cliente de comunicação com o Catalog-Service
catalog_client = CatalogClient()

# Base em memória para reservas
RENTALS_DB: Dict[str, dict] = {}

# Helper DynamoDB para persistência de locações
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
        name = os.getenv("RENTALS_TABLE_NAME", "gamerent_rentals")
        table = (
            ddb.Table(name)
            if name in [t.name for t in ddb.tables.all()]
            else ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "rental_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "rental_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        )
        table.wait_until_exists()
        _ddb_table = table
        return _ddb_table
    except Exception as exc:
        logger.warning(f"DynamoDB indisponível, operando com RENTALS_DB em memória: {exc}")
        return None


def _put_ddb_rental(table, record: dict) -> None:
    from decimal import Decimal
    item = {**record}
    if isinstance(item.get("status"), RentalStatus):
        item["status"] = item["status"].value
    for k in ("daily_rate", "total_price"):
        if k in item and item[k] is not None:
            item[k] = Decimal(str(item[k]))
    clean_item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=clean_item)


def _save_rental(record: dict) -> RentalResponse:
    rental_id = record["rental_id"]
    RENTALS_DB[rental_id] = record
    table = _get_ddb_table()
    if table is not None:
        try:
            _put_ddb_rental(table, record)
        except Exception as exc:
            logger.warning(f"Falha ao persistir locação {rental_id} no DynamoDB: {exc}")
    return RentalResponse(**record)


@app.get("/health", tags=["Monitoramento"])
def health_check():
    """Health check do rental-service."""
    return {
        "status": "HEALTHY",
        "service": "rental-service",
        "total_rentals": len(RENTALS_DB),
        "target_catalog_url": catalog_client.base_url,
        "lamport_clock": _lamport_clock
    }


@app.post("/rentals", response_model=RentalResponse, status_code=status.HTTP_201_CREATED, tags=["Locações"])
async def create_rental(
    payload: RentalCreateRequest,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FA-03 / FA-04 / FB-01: Cria uma nova locação atômica de jogo de tabuleiro.
    Elimina condição de corrida (double-booking) delegando a reserva em chamada atômica única
    ao catalog-service via POST /games/{id}/reserve.
    """
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
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        )
    except GameNotFoundError as exc:
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )
    except CatalogCommunicationError as exc:
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha de comunicação inter-serviços: {exc}"
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
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao registrar locação. A reserva do exemplar foi cancelada: {exc}"
        )

    logger.info(f"[LAMPORT={clock}] Aluguel confirmado com sucesso! ID={rental_id}, URN={resp_obj.urn}, Total=R$ {total_price}")
    return resp_obj


@app.get("/rentals", response_model=List[RentalResponse], tags=["Locações"])
def list_rentals():
    """Lista todas as reservas registradas."""
    return [RentalResponse(**r) for r in RENTALS_DB.values()]


@app.get("/rentals/{rental_id}", response_model=RentalResponse, tags=["Locações"])
def get_rental(rental_id: str):
    """Consulta detalhes de uma locação específica."""
    if rental_id not in RENTALS_DB:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locação com ID {rental_id} não encontrada."
        )
    return RentalResponse(**RENTALS_DB[rental_id])


@app.post("/rentals/{rental_id}/return", response_model=RentalResponse, tags=["Locações"])
async def return_rental(
    rental_id: str,
    response: Response,
    x_lamport_clock: Optional[int] = Header(default=None)
):
    """
    FB-01 / FB-03: Finaliza a locação e comunica o catalog-service via /release para liberar o exemplar.
    """
    clock = tick_lamport(x_lamport_clock)
    if rental_id not in RENTALS_DB:
        response.headers["X-Lamport-Clock"] = str(clock)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Locação não encontrada.")

    rental = RENTALS_DB[rental_id]
    if rental["status"] == RentalStatus.COMPLETED:
        response.headers["X-Lamport-Clock"] = str(clock)
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
    except Exception as exc:
        logger.error(f"Erro ao liberar jogo {rental['game_id']} no catálogo: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Não foi possível liberar o jogo no catálogo: {exc}"
        )

    rental["status"] = RentalStatus.COMPLETED
    rental["returned_at"] = datetime.now(timezone.utc).isoformat()
    rental["lamport_clock"] = clock
    response.headers["X-Lamport-Clock"] = str(clock)

    resp_obj = _save_rental(rental)
    logger.info(f"[LAMPORT={clock}] Locação {rental_id} finalizada. Jogo {rental['game_id']} liberado no catálogo.")
    return resp_obj


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
