import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("rental-service.catalog-client")

class CatalogCommunicationError(Exception):
    """Erro quando a comunicação de rede com o catalog-service falha."""
    pass

class GameNotFoundError(Exception):
    """Erro quando o jogo não existe no catálogo remoto."""
    pass

class CatalogClient:
    """
    Cliente REST/RPC responsável pela comunicação síncrona
    entre o Rental-Service e o Catalog-Service.
    """
    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 5.0):
        self.base_url = base_url or os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001")
        self.timeout = timeout_seconds
        logger.info(f"CatalogClient configurado para apontar para: {self.base_url}")

    async def get_game(self, game_id: int) -> Dict[str, Any]:
        """
        Realiza chamada síncrona HTTP GET para obter detalhes e status do jogo.
        """
        url = f"{self.base_url}/games/{game_id}"
        logger.info(f"Disparando chamada RPC/REST síncrona: GET {url}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)

            if response.status_code == 200:
                logger.info(f"Resposta recebida com sucesso do catalog-service para jogo {game_id}: 200 OK")
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"Catalog-service reportou que o jogo {game_id} não existe: 404 Not Found")
                raise GameNotFoundError(f"Jogo com ID {game_id} não encontrado no catálogo.")
            else:
                logger.error(f"Catalog-service retornou status inesperado {response.status_code}: {response.text}")
                raise CatalogCommunicationError(f"Erro no serviço de catálogo: status {response.status_code}")

        except httpx.RequestError as exc:
            logger.error(f"Falha de rede ao tentar contatar o catalog-service em {url}: {exc}")
            raise CatalogCommunicationError(f"Não foi possível contatar o catalog-service ({exc})")

    async def set_game_status(self, game_id: int, new_status: str) -> bool:
        """
        Atualiza o status do jogo no catálogo remoto para RENTED ou AVAILABLE.
        """
        url = f"{self.base_url}/games/{game_id}/status"
        logger.info(f"Disparando chamada RPC/REST síncrona: PATCH {url} com status={new_status}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(url, json={"status": new_status})

            if response.status_code == 200:
                logger.info(f"Status do jogo {game_id} atualizado com sucesso no catálogo remoto.")
                return True
            else:
                logger.warning(f"Falha ao atualizar status no catálogo. Código: {response.status_code}")
                return False
        except httpx.RequestError as exc:
            logger.error(f"Falha de rede na atualização de status em {url}: {exc}")
            raise CatalogCommunicationError(f"Erro de comunicação ao atualizar catálogo: {exc}")
