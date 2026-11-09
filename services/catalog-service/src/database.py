"""Camada de repositório do ``catalog-service`` no Amazon DynamoDB (RF-05 / RF-01).

Substitui o dicionário volátil em memória (``GAMES_DB``) por persistência replicada no
DynamoDB, com suporte transparente a:

- **AWS (``sa-east-1`` Multi-AZ):** usa a cadeia de credenciais padrão do ``boto3``
  (IAM Role da instância EC2), sem injetar chaves fictícias.
- **DynamoDB Local:** via ``DYNAMODB_ENDPOINT_URL`` (ex.: ``http://dynamodb-local:8000``).

Responsabilidades:

1. Criação automática da tabela ``gamerent_games`` (partição: ``id``) caso não exista.
2. *Seed* inicial dos 5 jogos de tabuleiro clássicos (e do acervo de Poços de Caldas)
   quando a tabela estiver vazia — sempre com ``attribute_not_exists(id)`` para nunca
   sobrescrever estado persistido.
3. Escrita condicional atômica (``reserve_game_atomically`` / ``release_game_atomically``)
   que implementa a exclusão mútua distribuída (RF-01): a falha da escrita condicional do
   DynamoDB (``ConditionalCheckFailedException``) é convertida em ``ConditionalCheckFailed``
   para que o ``app.py`` responda HTTP 409 Conflict.
4. Leituras com seletor de consistência (``ConsistentRead`` True/False) para o RF-06.
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from botocore.exceptions import ClientError

from models import Game, GameStatus

logger = logging.getLogger("catalog-service.database")

GAMES_TABLE_NAME = os.getenv("GAMES_TABLE_NAME", "gamerent_games")
AWS_REGION = os.getenv("AWS_REGION", "sa-east-1")
DYNAMODB_ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL") or None
# USE_DYNAMODB força o uso do DynamoDB real da AWS mesmo sem endpoint explícito.
USE_DYNAMODB = os.getenv("USE_DYNAMODB", "").lower() in ("1", "true", "yes")

# -------------------------------------------------------------------------- seed


def build_seed_games() -> "dict[int, Game]":
    """Constrói os 5 jogos de tabuleiro clássicos (seed) mais o acervo de Poços de Caldas.

    Retorna um dicionário novo a cada chamada, com objetos ``Game`` independentes, para que
    o fallback em memória do ``app.py`` e o repositório não compartilhem estado mutável.
    """
    games: dict[int, Game] = {
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
            longitude=-46.6333,  # Região Central de SP
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
            longitude=-46.6560,  # Av. Paulista
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
            longitude=-46.6333,
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
            longitude=-46.6795,  # Itaim Bibi
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
            longitude=-46.6560,
        ),
    }

    # Acervo de Poços de Caldas (MG). IDs a partir de 101 para não colidir com jogos cadastrados
    # pelos locadores; coordenadas aproximadas dos bairros (só o servidor as vê).
    _pocos = [
        (101, "Carcassonne", "Monte cidades, estradas e mosteiros peça por peça. Ótimo para 2 a 5 pessoas.",
         "Família", 14.0, "locador-pc-001", "Fernanda Lima", -21.7880, -46.5617),        # Centro
        (102, "Azul", "Crie o mosaico mais bonito do palácio com azulejos coloridos.",
         "Estratégia", 15.0, "locador-pc-001", "Fernanda Lima", -21.7880, -46.5617),     # Centro
        (103, "Codenames", "Duas equipes, pistas de uma palavra e muita risada. Ideal para grupos.",
         "Festa", 10.0, "locador-pc-002", "Rafael Prado", -21.7983, -46.5590),           # Jardim dos Estados
        (104, "Splendor", "Negocie gemas e conquiste a nobreza do Renascimento.",
         "Estratégia", 13.0, "locador-pc-002", "Rafael Prado", -21.7983, -46.5590),      # Jardim dos Estados
        (105, "Wingspan", "Atraia aves para a sua reserva em um jogo calmo e lindo de ver.",
         "Estratégia", 22.0, "locador-pc-003", "Juliana Ribeiro", -21.7740, -46.5560),   # Country Club
        (106, "Dobble", "Rápido e divertido: ache o símbolo repetido antes de todo mundo.",
         "Infantil", 8.0, "locador-pc-003", "Juliana Ribeiro", -21.7845, -46.5726),      # Vila Cruz
    ]
    for _id, _title, _desc, _cat, _price, _owner_id, _owner, _lat, _lon in _pocos:
        games[_id] = Game(
            id=_id, title=_title, description=_desc, category=_cat, price_per_day=_price,
            status=GameStatus.AVAILABLE, owner_id=_owner_id, owner_name=_owner,
            latitude=_lat, longitude=_lon,
        )
    return games


# ---------------------------------------------------------------------- helpers


class ConditionalCheckFailed(Exception):
    """Conflito de escrita condicional no DynamoDB (equivalente a ``ConditionalCheckFailedException``).

    O ``botocore`` não expõe uma classe Python própria para esse erro do DynamoDB — ele chega
    como ``ClientError`` com ``Error.Code == "ConditionalCheckFailedException"``. Esta exceção
    de domínio torna esse contrato explícito para o ``app.py`` responder 409 Conflict.
    """


def is_conditional_failure(exc: Exception) -> bool:
    """Detecta a falha de escrita condicional do DynamoDB (usada para responder 409)."""
    if isinstance(exc, ConditionalCheckFailed):
        return True
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    return "ConditionalCheckFailedException" in str(type(exc)) or "ConditionalCheckFailedException" in str(exc)


def _scan_all(table, **kwargs) -> list[dict]:
    """Scan paginado: o DynamoDB devolve no máximo 1 MB por chamada, então percorremos
    ``LastEvaluatedKey`` até esgotar a tabela (evita custo e resultados truncados).
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


def _to_game_item(game: Game) -> dict:
    """Serializa um objeto ``Game`` para um item válido do DynamoDB (Decimal, status como string)."""
    item = {**game.model_dump(), "status": game.status.value}
    for k in ("price_per_day", "latitude", "longitude"):
        if k in item and item[k] is not None:
            item[k] = Decimal(str(item[k]))
    return {k: v for k, v in item.items() if v is not None}


# ------------------------------------------------------------------- repository


class GamesRepository:
    """Repositório do catálogo de jogos persistido no DynamoDB (fallback ``None`` = memória)."""

    def __init__(self, seed_games: Optional[Iterable[Game]] = None):
        self._seed_games = list(seed_games or [])
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
                self._table = self._connect_and_seed()
            except Exception as exc:  # noqa: BLE001 — cai para o fallback em memória
                log = logger.error if USE_DYNAMODB else logger.warning
                log(f"DynamoDB indisponível, operando com GAMES_DB em memória: {exc}")
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

    def _connect_and_seed(self):
        ddb = self._build_resource()
        table = self._ensure_table(ddb)
        table.wait_until_exists()
        # Expõe a tabela imediatamente: o seed usa put_game (que consulta self.table) e, sem
        # isto, a property re-entraria em _connect_and_seed causando recursão infinita.
        self._table = table
        try:
            self._seed_if_empty(table)
        except Exception:
            self._table = None
            raise
        return table

    def _ensure_table(self, ddb):
        try:
            if GAMES_TABLE_NAME in [t.name for t in ddb.tables.all()]:
                return ddb.Table(GAMES_TABLE_NAME)
            return ddb.create_table(
                TableName=GAMES_TABLE_NAME,
                KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "N"}],
                BillingMode="PAY_PER_REQUEST",
            )
        except ddb.meta.client.exceptions.ResourceInUseException:
            # Outra réplica do catalog-service criou a tabela ao mesmo tempo.
            return ddb.Table(GAMES_TABLE_NAME)

    def _seed_if_empty(self, table) -> None:
        """Semeia apenas o que falta, sem sobrescrever estado existente.

        A condição ``attribute_not_exists(id)`` garante a idempotência mesmo com duas
        réplicas subindo simultaneamente contra a mesma tabela.
        """
        existing_ids = {
            int(it["id"])
            for it in _scan_all(table, ProjectionExpression="id")
            if "id" in it
        }
        for game in self._seed_games:
            if game.id in existing_ids:
                continue
            try:
                self.put_game(game, condition={"ConditionExpression": "attribute_not_exists(id)"})
            except Exception as exc:  # noqa: BLE001
                if not is_conditional_failure(exc):
                    raise

    # -- escrita ----------------------------------------------------------

    def put_game(self, game: Game, condition: Optional[dict] = None) -> None:
        """Grava o item; ``condition`` = kwargs extras do ``put_item`` (ConditionExpression etc.)."""
        self.table.put_item(Item=_to_game_item(game), **(condition or {}))

    def put_game_if_absent(self, game: Game) -> bool:
        """Grava o jogo apenas se o ``id`` ainda não existir. Retorna ``True`` se gravou."""
        try:
            self.put_game(game, condition={"ConditionExpression": "attribute_not_exists(id)"})
            return True
        except ConditionalCheckFailed:
            return False
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def _update_item(self, key: dict, **kwargs) -> None:
        """Envolve ``update_item`` convertendo a escrita condicional falha em ``ConditionalCheckFailed``."""
        try:
            self.table.update_item(Key=key, **kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalCheckFailed("Escrita condicional rejeitada pelo DynamoDB (conflito).") from exc
            raise

    def reserve_game_atomically(
        self,
        game_id: int,
        rental_id: str,
        incoming_clock: int,
        renter_name: Optional[str] = None,
    ) -> None:
        """Exclusão mútua distribuída (RF-01): reserva atômica via ``UpdateItem`` condicional.

        Só aplica a transição ``AVAILABLE -> RENTED`` se a condição ainda valer no instante da
        escrita. Em caso de disputa, lança ``ConditionalCheckFailed`` (equivalente à
        ``ConditionalCheckFailedException`` do DynamoDB) para o chamador converter em 409.
        """
        names = {"#st": "status"}
        values = {
            ":rented": GameStatus.RENTED.value,
            ":available": GameStatus.AVAILABLE.value,
            ":rid": rental_id,
            ":new_clock": incoming_clock,
            ":inc": 1,
            ":now": datetime.now(timezone.utc).isoformat(),
        }
        update = (
            "SET #st = :rented, current_rental_id = :rid, lamport_clock = :new_clock, "
            "version = version + :inc, updated_at = :now"
        )
        if renter_name is not None:
            values[":rname"] = renter_name
            update += ", current_renter_name = :rname"
        self._update_item(
            {"id": game_id},
            UpdateExpression=update,
            ConditionExpression="attribute_exists(id) AND #st = :available",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def release_game_atomically(
        self,
        game_id: int,
        incoming_clock: int,
        rental_id: Optional[str] = None,
        is_forced: bool = False,
    ) -> None:
        """Liberação atômica (RF-01): devolução/cancelamento restaura o exemplar para ``AVAILABLE``.

        Sem ``is_forced``, valida que o ``rental_id`` informado corresponde à locação ativa.
        """
        names = {"#st": "status"}
        values = {
            ":available": GameStatus.AVAILABLE.value,
            ":new_clock": incoming_clock,
            ":inc": 1,
            ":now": datetime.now(timezone.utc).isoformat(),
        }
        cond = "attribute_exists(id)"
        if is_forced:
            pass
        elif rental_id:
            cond += " AND (current_rental_id = :rid OR attribute_not_exists(current_rental_id))"
            values[":rid"] = rental_id
        else:
            # Sem rental_id, a liberação só é aplicada se não houver locação ativa no instante da
            # escrita. Fecha a janela TOCTOU entre a leitura local (em _core_release) e este update:
            # se outra réplica reservou o exemplar nesse intervalo, a condição falha e a reserva
            # concorrente é preservada (em vez de ter o current_rental_id removido).
            cond += " AND attribute_not_exists(current_rental_id)"
        self._update_item(
            {"id": game_id},
            UpdateExpression=(
                "SET #st = :available, version = version + :inc, lamport_clock = :new_clock, "
                "updated_at = :now REMOVE current_rental_id, current_renter_name"
            ),
            ConditionExpression=cond,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    # -- leitura ----------------------------------------------------------

    def get_item(self, game_id: int, consistent: bool = True) -> Optional[dict]:
        """Item cru do DynamoDB (ou ``None`` se não existir)."""
        return self.table.get_item(Key={"id": game_id}, ConsistentRead=consistent).get("Item")

    def scan_items(self, consistent: bool = True) -> list[dict]:
        """Todos os itens do catálogo (sem filtro)."""
        return _scan_all(self.table, ConsistentRead=consistent)

    def scan_ids(self) -> list[int]:
        """IDs existentes (usado para escolher um ID livre no cadastro)."""
        return [
            int(it["id"])
            for it in _scan_all(self.table, ProjectionExpression="id")
            if "id" in it
        ]


# ------------------------------------------------------------------- singleton

# Instância única usada pelo app.py. O seed é reconstruído a partir de uma cópia
# independente (build_seed_games) para não compartilhar estado mutável com o GAMES_DB.
repository = GamesRepository(build_seed_games().values())
