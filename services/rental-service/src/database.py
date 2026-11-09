"""Camada de repositório do ``rental-service`` no Amazon DynamoDB (RF-05).

Substitui o dicionário volátil em memória (``RENTALS_DB``) por persistência replicada no
DynamoDB, com suporte transparente a:

- **AWS (``sa-east-1`` Multi-AZ):** usa a cadeia de credenciais padrão do ``boto3``
  (IAM Role da instância EC2), sem injetar chaves fictícias.
- **DynamoDB Local:** via ``DYNAMODB_ENDPOINT_URL`` (ex.: ``http://dynamodb-local:8000``).

Responsabilidades:

1. Criação automática da tabela ``gamerent_rentals`` (partição: ``rental_id``) caso não exista.
2. Persistência e leitura das transações de locação (``put_rental``, ``get_rental``,
   ``scan_rentals``), com conversão de tipos (``Decimal``/``int``) entre o DynamoDB e o domínio.
"""

import logging
import os
from decimal import Decimal
from typing import Optional

from botocore.exceptions import ClientError

from models import RentalStatus

logger = logging.getLogger("rental-service.database")

RENTALS_TABLE_NAME = os.getenv("RENTALS_TABLE_NAME", "gamerent_rentals")
AWS_REGION = os.getenv("AWS_REGION", "sa-east-1")
DYNAMODB_ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL") or None
# USE_DYNAMODB força o uso do DynamoDB real da AWS mesmo sem endpoint explícito.
USE_DYNAMODB = os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes")


def _to_item(record: dict) -> dict:
    """Serializa um registro de locação para um item válido do DynamoDB."""
    item = {**record}
    if isinstance(item.get("status"), RentalStatus):
        item["status"] = item["status"].value
    for k in ("daily_rate", "total_price"):
        if k in item and item[k] is not None:
            item[k] = Decimal(str(item[k]))
    return {k: v for k, v in item.items() if v is not None}


def _from_item(item: dict) -> dict:
    """Converte um item do DynamoDB de volta para os tipos de domínio (float/int)."""
    for k in ("daily_rate", "total_price"):
        if k in item and item[k] is not None:
            item[k] = float(item[k])
    for k in ("game_id", "rental_days", "lamport_clock"):
        if k in item and item[k] is not None:
            item[k] = int(item[k])
    if "returned_at" not in item:
        item["returned_at"] = None
    return item


def _scan_all(table, **kwargs) -> list[dict]:
    """Scan paginado: percorre ``LastEvaluatedKey`` até esgotar a tabela (o DynamoDB devolve no
    máximo 1 MB por chamada), evitando custo e resultados truncados em acervos grandes.
    """
    items: list[dict] = []
    kwargs.pop("ExclusiveStartKey", None)
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            return items
        kwargs["ExclusiveStartKey"] = start_key


class RentalsRepository:
    """Repositório das transações de locação persistido no DynamoDB (fallback ``None`` = memória)."""

    def __init__(self):
        self._table = None
        self._enabled = USE_DYNAMODB or bool(DYNAMODB_ENDPOINT_URL)

    # -- ciclo de vida ----------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def table(self):
        """Tabela do DynamoDB (lazy). ``None`` se o banco não estiver configurado/indisponível."""
        if not self._enabled:
            return None
        if self._table is None:
            try:
                self._table = self._connect()
            except Exception as exc:  # noqa: BLE001 — cai para o fallback em memória
                log = logger.error if USE_DYNAMODB else logger.warning
                log(f"DynamoDB indisponível, operando com RENTALS_DB em memória: {exc}")
                self._table = None
        return self._table

    @property
    def connected(self) -> bool:
        return self.table is not None

    def _build_resource(self):
        import boto3

        # dynamodb-local aceita qualquer credencial; na AWS deixamos o boto3 usar a cadeia
        # padrão (IAM Role da EC2), sem injetar chaves fictícias.
        creds = {}
        if DYNAMODB_ENDPOINT_URL:
            creds = {
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "local"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "local"),
            }
        return boto3.resource(
            "dynamodb",
            region_name=AWS_REGION,
            endpoint_url=DYNAMODB_ENDPOINT_URL,
            **creds,
        )

    def _connect(self):
        ddb = self._build_resource()
        try:
            if RENTALS_TABLE_NAME in [t.name for t in ddb.tables.all()]:
                table = ddb.Table(RENTALS_TABLE_NAME)
            else:
                table = ddb.create_table(
                    TableName=RENTALS_TABLE_NAME,
                    KeySchema=[{"AttributeName": "rental_id", "KeyType": "HASH"}],
                    AttributeDefinitions=[{"AttributeName": "rental_id", "AttributeType": "S"}],
                    BillingMode="PAY_PER_REQUEST",
                )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceInUseException":
                # Outra instância do rental-service criou a tabela ao mesmo tempo.
                table = ddb.Table(RENTALS_TABLE_NAME)
            else:
                raise
        table.wait_until_exists()
        return table

    # -- escrita ----------------------------------------------------------

    def put_rental(self, record: dict) -> None:
        """Grava (cria ou sobrescreve) um registro de locação."""
        self.table.put_item(Item=_to_item(record))

    # -- leitura ----------------------------------------------------------

    def get_rental(self, rental_id: str) -> Optional[dict]:
        """Busca uma locação pelo ``rental_id`` (convertida para os tipos de domínio)."""
        item = self.table.get_item(Key={"rental_id": rental_id}).get("Item")
        return _from_item(item) if item else None

    def scan_rentals(
        self,
        renter_email: Optional[str] = None,
        game_id: Optional[int] = None,
        status_filter: Optional[RentalStatus] = None,
    ) -> list[dict]:
        """Varre as locações com filtros opcionais combináveis (renter_email, game_id, status)."""
        from boto3.dynamodb.conditions import Attr

        filter_exp = None
        if renter_email:
            filter_exp = Attr("renter_email").eq(renter_email)
        if game_id is not None:
            cond = Attr("game_id").eq(game_id)
            filter_exp = filter_exp & cond if filter_exp else cond
        if status_filter:
            status_value = status_filter.value if isinstance(status_filter, RentalStatus) else str(status_filter)
            cond = Attr("status").eq(status_value)
            filter_exp = filter_exp & cond if filter_exp else cond

        scan_kwargs = {}
        if filter_exp:
            scan_kwargs["FilterExpression"] = filter_exp
        items = _scan_all(self.table, **scan_kwargs)
        return [_from_item(it) for it in items]


# ------------------------------------------------------------------- singleton

# Instância única usada pelo app.py.
repository = RentalsRepository()
