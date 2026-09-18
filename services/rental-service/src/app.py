import os
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from models import RentalCreateRequest, RentalResponse, RentalStatus
from catalog_client import CatalogClient, CatalogCommunicationError, GameNotFoundError

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

# Inicializa o cliente de comunicação com o Catalog-Service
catalog_client = CatalogClient()

# Base em memória para reservas
RENTALS_DB: Dict[str, dict] = {}

@app.get("/health", tags=["Monitoramento"])
def health_check():
    """Health check do rental-service."""
    return {
        "status": "HEALTHY",
        "service": "rental-service",
        "total_rentals": len(RENTALS_DB),
        "target_catalog_url": catalog_client.base_url
    }

@app.post("/rentals", response_model=RentalResponse, status_code=status.HTTP_201_CREATED, tags=["Locações"])
async def create_rental(payload: RentalCreateRequest):
    """
    Cria uma nova locação de jogo de tabuleiro.
    
    Demonstração de Sistemas Distribuídos:
    1. Recebe a solicitação do cliente.
    2. Dispara requisição síncrona RPC/REST para o CATALOG-SERVICE para validar
       existência e disponibilidade do jogo.
    3. Trata cenários distribuídos: jogo inexistente (404), concorrência/indisponibilidade (409)
       e falha de comunicação/partição de rede (503).
    4. Atualiza o estado no catálogo remoto e confirma a transação.
    """
    logger.info(f"Recebida solicitação de aluguel: Jogo {payload.game_id} por {payload.renter_name}")

    # Passo 1: Consulta remota ao catalog-service
    try:
        game_data = await catalog_client.get_game(payload.game_id)
    except GameNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )
    except CatalogCommunicationError as exc:
        # Simula tratamento de falha distribuída de rede
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha de comunicação inter-serviços: {exc}"
        )

    # Passo 2: Validação de disponibilidade de negócio
    if game_data.get("status") != "AVAILABLE":
        logger.warning(f"Jogo {payload.game_id} ('{game_data.get('title')}') está indisponível ({game_data.get('status')}).")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"O jogo '{game_data.get('title')}' não está disponível no momento (Status atual: {game_data.get('status')})."
        )

    # Passo 3: Atualiza status remoto no catálogo para RENTED
    try:
        await catalog_client.set_game_status(payload.game_id, "RENTED")
    except CatalogCommunicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível bloquear o jogo no serviço de catálogo."
        )

    # Passo 4: Gera a transação de aluguel local
    rental_id = str(uuid.uuid4())
    daily_rate = float(game_data.get("price_per_day", 0.0))
    total_price = round(daily_rate * payload.rental_days, 2)
    created_at_iso = datetime.now(timezone.utc).isoformat()

    rental_record = {
        "rental_id": rental_id,
        "game_id": payload.game_id,
        "game_title": game_data.get("title", ""),
        "renter_name": payload.renter_name,
        "renter_email": payload.renter_email,
        "rental_days": payload.rental_days,
        "daily_rate": daily_rate,
        "total_price": total_price,
        "status": RentalStatus.CONFIRMED,
        "created_at": created_at_iso
    }

    RENTALS_DB[rental_id] = rental_record
    logger.info(f"Aluguel confirmado com sucesso! ID={rental_id}, Total=R$ {total_price}")

    return RentalResponse(**rental_record)

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
async def return_rental(rental_id: str):
    """
    Finaliza o aluguel e comunica o catalog-service para liberar o jogo novamente (AVAILABLE).
    """
    if rental_id not in RENTALS_DB:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Locação não encontrada.")

    rental = RENTALS_DB[rental_id]
    if rental["status"] == RentalStatus.COMPLETED:
        return RentalResponse(**rental)

    # Libera jogo no catálogo remoto
    await catalog_client.set_game_status(rental["game_id"], "AVAILABLE")
    rental["status"] = RentalStatus.COMPLETED
    logger.info(f"Locação {rental_id} finalizada. Jogo {rental['game_id']} liberado no catálogo.")

    return RentalResponse(**rental)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
