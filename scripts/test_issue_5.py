"""Self-check para Issue #5 (CA-04: Esquema de URNs e Service Discovery).

Pré-requisito: catalog-service em :8001 e rental-service em :8002 (docker compose up -d --build).
Valida os URNs com o próprio parser do serviço (naming.parse_urn).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services" / "catalog-service" / "src"))
import naming  # noqa: E402

CATALOG = "http://127.0.0.1:8001"
RENTAL = "http://127.0.0.1:8002"


def req(url: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def check(kind: str, value: str) -> dict:
    parsed = naming.parse_urn(value)  # ValueError se fora do esquema
    assert parsed["type"] == kind, f"Esperado URN de {kind}, veio {value!r}"
    return parsed


def wait_healthy(base: str, attempts: int = 30) -> dict:
    """O `compose up` retorna antes de o serviço aceitar conexões."""
    for _ in range(attempts):
        try:
            status, body = req(f"{base}/health")
            if status == 200:
                return body
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError(f"{base} não ficou saudável a tempo")


if __name__ == "__main__":
    # 1. /health expõe URN e INSTANCE_ID do nó
    for base, service in ((CATALOG, "catalog-service"), (RENTAL, "rental-service")):
        health = wait_healthy(base)
        node = check("node", health["node_urn"])
        assert node["service_name"] == service
        assert health["node_urn"] == naming.node_urn(service, health["instance_id"])
    print("[1/4] /health com node_urn e instance_id nos dois serviços")

    # 2. /discovery com metadados de nomeação e ao menos um nome simbólico resolvido via DNS.
    #    No rental-service o alvo inclui o host de CATALOG_SERVICE_URL, que precisa resolver
    #    para as chamadas S2S funcionarem (catalog-service no Docker, catalog.gamerent.internal na AWS).
    for base, service in ((CATALOG, "catalog-service"), (RENTAL, "rental-service")):
        status, disc = req(f"{base}/discovery")
        assert status == 200 and disc["service"] == service
        check("node", disc["node_urn"])
        assert set(disc["urn_schema"]) == {"node", "game", "rental", "owner"}
        for entry in disc["dns"]:
            assert {"hostname", "resolved_ips", "resolved", "status"} <= entry.keys()
        # Campos compartilhados com o /discovery do PR #24 (issue #16)
        assert {"local_ip", "dns_target", "dns_resolution", "dynamodb", "timestamp"} <= disc.keys()
        assert disc["dns_resolution"]["status"] in ("RESOLVED", "UNRESOLVED")
        assert disc["dynamodb"]["mode"] in ("AWS_DYNAMODB", "LOCAL_DYNAMODB", "IN_MEMORY_FALLBACK")
        resolved = [e for e in disc["dns"] if e["resolved"]]
        print(f"      {service}: " + ("; ".join(f"{e['hostname']} -> {e['resolved_ips']}" for e in resolved) or "nenhum nome resolvido"))
        if service == "rental-service":
            assert resolved, "rental-service não resolveu o host do catálogo via DNS"
    print("[2/4] /discovery nos dois serviços")

    # 3. Jogos e locadores com URNs padronizados
    status, games = req(f"{CATALOG}/games")
    assert status == 200 and games
    for g in games:
        assert int(check("game", g["urn"])["game_id"]) == g["id"]
        check("owner", g["owner_urn"])
        check("node", g["served_by_node"])
    print(f"[3/4] {len(games)} jogos com urn:gamerent:game / owner")

    # 4. Reserva recebe urn:gamerent:rental:{uuid} e o game_urn canônico do catálogo
    available = next((g for g in games if g["status"] == "AVAILABLE"), None)
    assert available, "Nenhum jogo AVAILABLE para testar a locação"
    status, rental = req(f"{RENTAL}/rentals", "POST", {
        "renter_name": "Self-check #5", "renter_email": "selfcheck5@exemplo.com",
        "game_id": available["id"], "rental_days": 1,
    })
    assert status == 201, f"Locação falhou: {status} {rental}"
    try:
        assert check("rental", rental["urn"])["rental_id"] == rental["rental_id"]
        assert rental["game_urn"] == available["urn"]
        check("node", rental["served_by_node"])
        print(f"[4/4] Locação {rental['urn']}")
    finally:
        req(f"{RENTAL}/rentals/{rental['rental_id']}/return", "POST")

    print("OK: Todos os critérios de aceite da Issue #5 (CA-04) validados!")
