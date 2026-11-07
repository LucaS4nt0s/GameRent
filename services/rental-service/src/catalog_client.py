import os
import logging
from typing import Optional, Dict, Any
import httpx

import naming

logger = logging.getLogger("rental-service.catalog-client")

class CatalogCommunicationError(Exception):
    """Erro quando a comunicação de rede com o catalog-service falha."""
    pass

class GameNotFoundError(Exception):
    """Erro quando o jogo não existe no catálogo remoto."""
    pass

class GameConflictError(Exception):
    """Erro quando o jogo está indisponível ou já reservado (HTTP 409 Conflict)."""
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code

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
        # Não bloqueia o event loop. O httpx resolve de novo: com vários IPs o log lista os candidatos
        await naming.resolve_async(self.base_url)
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
        # Não bloqueia o event loop. O httpx resolve de novo: com vários IPs o log lista os candidatos
        await naming.resolve_async(self.base_url)
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

    async def reserve_game(
        self,
        game_id: int,
        rental_id: str,
        renter_name: str,
        renter_email: Optional[str] = None,
        lamport_clock: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        FA-03 / FA-04: Reserva atômica de exemplar via chamada RPC síncrona.
        Envia X-Lamport-Clock e trata exclusão mútua distribuída (409 Conflict).
        """
        url = f"{self.base_url}/games/{game_id}/reserve"
        await naming.resolve_async(self.base_url)
        headers = {"Content-Type": "application/json"}
        if lamport_clock is not None:
            headers["X-Lamport-Clock"] = str(lamport_clock)

        payload = {
            "rental_id": rental_id,
            "renter_name": renter_name,
            "renter_email": renter_email
        }
        logger.info(f"Disparando reserva atômica S2S: POST {url} (Rental={rental_id}, Clock={lamport_clock})")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                data = response.json()
                resp_clock = response.headers.get("X-Lamport-Clock")
                if resp_clock and "lamport_clock" not in data:
                    data["lamport_clock"] = int(resp_clock)
                logger.info(f"Reserva do jogo {game_id} confirmada pelo catálogo remoto.")
                return data
            elif response.status_code == 409:
                err_detail = response.json().get("detail", "Jogo indisponível ou já reservado.")
                logger.warning(f"Conflito 409 reportado pelo catálogo para jogo {game_id}: {err_detail}")
                raise GameConflictError(err_detail)
            elif response.status_code == 404:
                err_detail = response.json().get("detail", f"Jogo com ID {game_id} não encontrado.")
                logger.warning(f"Jogo {game_id} não encontrado no catálogo: 404 Not Found")
                raise GameNotFoundError(err_detail)
            else:
                logger.error(f"Catalog-service retornou status inesperado {response.status_code}: {response.text}")
                raise CatalogCommunicationError(f"Erro inesperado no catálogo: status {response.status_code}")

        except (GameConflictError, GameNotFoundError):
            raise
        except httpx.RequestError as exc:
            logger.error(f"Falha de rede na reserva atômica em {url}: {exc}")
            raise CatalogCommunicationError(f"Não foi possível contatar o catalog-service ({exc})")

    async def release_game(
        self,
        game_id: int,
        rental_id: Optional[str] = None,
        lamport_clock: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        FB-01: Liberação atômica de exemplar via chamada RPC síncrona.
        """
        url = f"{self.base_url}/games/{game_id}/release"
        await naming.resolve_async(self.base_url)
        headers = {"Content-Type": "application/json"}
        if lamport_clock is not None:
            headers["X-Lamport-Clock"] = str(lamport_clock)

        payload = {"rental_id": rental_id} if rental_id else None
        logger.info(f"Disparando liberação atômica S2S: POST {url} (Game={game_id})")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                logger.info(f"Liberação do jogo {game_id} confirmada pelo catálogo remoto.")
                return response.json()
            elif response.status_code == 409:
                err_detail = response.json().get("detail", "Operação negada na liberação do jogo.")
                logger.warning(f"Conflito 409 reportado pelo catálogo na liberação do jogo {game_id}: {err_detail}")
                raise GameConflictError(err_detail)
            elif response.status_code == 404:
                raise GameNotFoundError(f"Jogo {game_id} não encontrado no catálogo para liberação.")
            else:
                raise CatalogCommunicationError(f"Erro ao liberar jogo no catálogo: {response.status_code}")

        except (GameConflictError, GameNotFoundError):
            raise
        except httpx.RequestError as exc:
            logger.error(f"Falha de rede na liberação em {url}: {exc}")
            raise CatalogCommunicationError(f"Não foi possível contatar o catalog-service ({exc})")

