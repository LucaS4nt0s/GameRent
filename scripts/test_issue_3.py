"""Self-check para Issue #3 (Infra Docker com DynamoDB Local + múltiplas réplicas do catalog-service).

Pré-requisito: docker compose up -d --build
Valida que:
  1. dynamodb-local responde na porta 8000;
  2. as duas réplicas do catálogo (8001 e 8003) estão saudáveis e têm identidades distintas;
  3. um jogo cadastrado na réplica 1 é lido pela réplica 2 (estado compartilhado no DynamoDB).
"""
import json
import time
import urllib.error
import urllib.request

DYNAMODB = "http://127.0.0.1:8000"
REPLICA_1 = "http://127.0.0.1:8001"
REPLICA_2 = "http://127.0.0.1:8003"


def _decode(raw: str) -> dict | list | str:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return raw


def req(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict | list | str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, _decode(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, _decode(e.read().decode("utf-8"))


def wait_healthy(base: str, attempts: int = 30) -> dict:
    for _ in range(attempts):
        try:
            status, body = req(f"{base}/health")
            if status == 200:
                return body
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(1)
    raise AssertionError(f"{base} não ficou saudável a tempo")


if __name__ == "__main__":
    # 1. DynamoDB Local acessível (qualquer requisição HTTP sem assinatura devolve 400, mas prova que está de pé)
    try:
        status, _ = req(DYNAMODB)
    except urllib.error.URLError as exc:
        raise AssertionError(f"dynamodb-local inacessível em {DYNAMODB}: {exc}")
    assert status in (200, 400), f"dynamodb-local respondeu {status}"
    print(f"[1/3] dynamodb-local de pé em {DYNAMODB}")

    # 2. Duas réplicas saudáveis com URNs de nó distintos
    h1, h2 = wait_healthy(REPLICA_1), wait_healthy(REPLICA_2)
    assert h1["node_urn"] != h2["node_urn"], f"Réplicas com a mesma identidade: {h1['node_urn']}"
    print(f"[2/3] Réplicas ativas: {h1['node_urn']} | {h2['node_urn']}")

    # 3. Escrita na réplica 1, leitura forte na réplica 2
    title = f"Azul (infra-check {int(time.time())})"
    status, created = req(f"{REPLICA_1}/games", "POST", {
        "title": title,
        "description": "Jogo criado pelo self-check da issue #3",
        "category": "Abstrato",
        "price_per_day": 14.0,
        "owner_id": "locador-infra",
        "owner_name": "Self-check",
        "latitude": -23.5505,
        "longitude": -46.6333,
    })
    assert status == 201, f"Cadastro na réplica 1 falhou: {status} {created}"

    status, games = req(f"{REPLICA_2}/games?consistency=strong")
    assert status == 200, f"Leitura na réplica 2 falhou: {status}"
    match = [g for g in games if g["title"] == title]
    assert match, "Jogo cadastrado na réplica 1 não aparece na réplica 2 — o DynamoDB não está compartilhado"
    assert match[0]["served_by_node"] == h2["node_urn"]
    print(f"[3/3] Jogo {match[0]['urn']} gravado por catalog-1 e lido por catalog-2")

    print("OK: Todos os critérios locais da Issue #3 validados!")
