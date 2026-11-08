import asyncio
import json
import logging
import os
import threading
import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

import boto3

logger = logging.getLogger("rental-service.catalog-client")


class CatalogCommunicationError(Exception):
    """Erro quando a comunicação de mensageria SQS com o catalog-service falha."""
    pass


class GameNotFoundError(Exception):
    """Erro quando o jogo não existe no catálogo remoto."""
    pass


class GameConflictError(Exception):
    """Erro quando o jogo está indisponível ou já reservado (409 Conflict)."""
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class CatalogClient:
    """
    Cliente de mensageria assíncrona baseado em Amazon SQS responsável
    pela comunicação inter-serviços (Rental-Service -> Catalog-Service).
    """

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 6.0):
        self.base_url = base_url or os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8001")
        self.timeout = timeout_seconds
        self.endpoint = os.getenv("SQS_ENDPOINT_URL") or None
        self.region = os.getenv("AWS_REGION", "sa-east-1")
        self.req_queue_name = os.getenv("CATALOG_REQUESTS_QUEUE_NAME", "gamerent_catalog_requests")
        self.resp_queue_name = os.getenv("RENTAL_RESPONSES_QUEUE_NAME", "gamerent_rental_responses")

        creds = {"aws_access_key_id": "local", "aws_secret_access_key": "local"} if self.endpoint else {}
        self.sqs = boto3.client("sqs", endpoint_url=self.endpoint, region_name=self.region, **creds)

        self.req_queue_url: Optional[str] = None
        self.resp_queue_url: Optional[str] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

        self._worker_thread = threading.Thread(target=self._response_worker, daemon=True)
        self._worker_thread.start()
        logger.info(f"CatalogClient configurado com Amazon SQS (filas: {self.req_queue_name} -> {self.resp_queue_name})")

    def _normalize_url(self, queue_url: str) -> str:
        if self.endpoint and "://" in queue_url:
            end_p = urlparse(self.endpoint)
            q_p = urlparse(queue_url)
            return urlunparse(q_p._replace(scheme=end_p.scheme, netloc=end_p.netloc))
        return queue_url

    def _get_queue_url(self, name: str) -> str:
        try:
            url = self.sqs.get_queue_url(QueueName=name)["QueueUrl"]
        except Exception:
            try:
                url = self.sqs.create_queue(QueueName=name)["QueueUrl"]
            except Exception:
                # Corrida entre processos: outra instância pode ter criado a fila neste instante
                url = self.sqs.get_queue_url(QueueName=name)["QueueUrl"]
        return self._normalize_url(url)

    def _ensure_queues(self):
        with self._lock:
            if not self.req_queue_url:
                self.req_queue_url = self._get_queue_url(self.req_queue_name)
            if not self.resp_queue_url:
                self.resp_queue_url = self._get_queue_url(self.resp_queue_name)

    def _response_worker(self):
        while True:
            if not self.resp_queue_url:
                try:
                    self._ensure_queues()
                except Exception:
                    threading.Event().wait(1)
                    continue
            try:
                resp = self.sqs.receive_message(
                    QueueUrl=self.resp_queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=2,
                )
                for msg in resp.get("Messages", []):
                    receipt = msg["ReceiptHandle"]
                    try:
                        data = json.loads(msg["Body"])
                        corr_id = data.get("correlation_id")
                        with self._lock:
                            fut = self._pending.get(corr_id) if corr_id else None
                        if fut is not None and self._loop:
                            self._loop.call_soon_threadsafe(
                                lambda f=fut, d=data: f.set_result(d) if not f.done() else None
                            )
                    except Exception as err:
                        logger.error(f"Erro ao processar mensagem SQS: {err}")
                    finally:
                        self.sqs.delete_message(QueueUrl=self.resp_queue_url, ReceiptHandle=receipt)
            except Exception:
                threading.Event().wait(1)

    async def _send_and_wait(self, action: str, payload: dict) -> Dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        self._ensure_queues()
        corr_id = str(uuid.uuid4())
        future = self._loop.create_future()
        with self._lock:
            self._pending[corr_id] = future

        msg_body = {
            "correlation_id": corr_id,
            "reply_to": self.resp_queue_url,
            "action": action,
            "payload": payload,
        }

        try:
            self.sqs.send_message(
                QueueUrl=self.req_queue_url,
                MessageBody=json.dumps(msg_body),
            )
            resp = await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError:
            raise CatalogCommunicationError("Timeout aguardando resposta do catalog-service via Amazon SQS")
        except Exception as exc:
            if isinstance(exc, (GameConflictError, GameNotFoundError, CatalogCommunicationError)):
                raise
            raise CatalogCommunicationError(f"Falha de mensageria SQS com catalog-service: {exc}")
        finally:
            with self._lock:
                self._pending.pop(corr_id, None)

        status_code = resp.get("status", 500)
        if status_code == 200:
            data = resp.get("data", {})
            if "lamport_clock" in resp and "lamport_clock" not in data:
                data["lamport_clock"] = resp["lamport_clock"]
            return data
        elif status_code == 409:
            raise GameConflictError(resp.get("detail", "Jogo indisponível ou já reservado."))
        elif status_code == 404:
            raise GameNotFoundError(resp.get("detail", "Jogo com ID informado não encontrado no catálogo."))
        else:
            raise CatalogCommunicationError(resp.get("detail", f"Erro no catalog-service: status {status_code}"))

    async def reserve_game(
        self,
        game_id: int,
        rental_id: str,
        renter_name: str,
        renter_email: Optional[str] = None,
        lamport_clock: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Reserva atômica de exemplar via Amazon SQS."""
        logger.info(f"Disparando reserva atômica via SQS: Jogo={game_id}, Rental={rental_id}, Clock={lamport_clock}")
        return await self._send_and_wait("reserve", {
            "game_id": game_id,
            "rental_id": rental_id,
            "renter_name": renter_name,
            "renter_email": renter_email,
            "lamport_clock": lamport_clock,
        })

    async def release_game(
        self,
        game_id: int,
        rental_id: Optional[str] = None,
        lamport_clock: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Liberação atômica de exemplar via Amazon SQS."""
        logger.info(f"Disparando liberação atômica via SQS: Jogo={game_id}, Rental={rental_id}, Clock={lamport_clock}")
        return await self._send_and_wait("release", {
            "game_id": game_id,
            "rental_id": rental_id,
            "lamport_clock": lamport_clock,
        })

    async def get_game(self, game_id: int) -> Dict[str, Any]:
        """Consulta dados de jogo via Amazon SQS."""
        return await self._send_and_wait("get_game", {"game_id": game_id})

    async def set_game_status(self, game_id: int, new_status: str) -> bool:
        """Atualização de status via Amazon SQS."""
        res = await self._send_and_wait("set_status", {"game_id": game_id, "status": new_status})
        return res is not None
