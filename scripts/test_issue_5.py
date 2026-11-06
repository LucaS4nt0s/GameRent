"""Self-check para Issue #5 (CA-04: Esquema de URNs e Service Discovery).

Pré-requisito: catalog-service em :8001 e rental-service em :8002 (docker compose up -d --build).
"""
import json
import re
import urllib.error
import urllib.request

CATALOG = "http://localhost:8001"
RENTAL = "http://localhost:8002"

URN = {
    "node": re.compile(r"^urn:gamerent:node:[A-Za-z0-9][A-Za-z0-9._-]*:[A-Za-z0-9][A-Za-z0-9._-]*$"),
    "game": re.compile(r"^urn:gamerent:game:[a-z0-9-]+:\d+$"),
    "owner": re.compile(r"^urn:gamerent:owner:[A-Za-z0-9][A-Za-z0-9._-]*$"),
    "rental": re.compile(r"^urn:gamerent:rental:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
}


def req(url: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def check(kind: str, value: str) -> None:
    assert URN[kind].match(value or ""), f"URN de {kind} fora do padrão: {value!r}"


if __name__ == "__main__":
    # 1. /health expõe URN e INSTANCE_ID do nó
    for base, service in ((CATALOG, "catalog-service"), (RENTAL, "rental-service")):
        status, health = req(f"{base}/health")
        assert status == 200
        check("node", health["node_urn"])
        assert health["node_urn"] == f"urn:gamerent:node:{service}:{health['instance_id']}"
    print("[1/4] /health com node_urn e instance_id nos dois serviços")

    # 2. /discovery com metadados de nomeação e resolução DNS
    for base, service in ((CATALOG, "catalog-service"), (RENTAL, "rental-service")):
        status, disc = req(f"{base}/discovery")
        assert status == 200 and disc["service"] == service
        check("node", disc["node_urn"])
        assert set(disc["urn_schema"]) == {"node", "game", "rental", "owner"}
        assert disc["dns"], "Nenhum alvo DNS informado"
        for entry in disc["dns"]:
            assert {"hostname", "resolved_ips", "resolved"} <= entry.keys()
        resolved = [e for e in disc["dns"] if e["resolved"]]
        print(f"      {service}: " + "; ".join(f"{e['hostname']} -> {e['resolved_ips']}" for e in resolved))
    print("[2/4] /discovery nos dois serviços")

    # 3. Jogos e locadores com URNs padronizados
    status, games = req(f"{CATALOG}/games")
    assert status == 200 and games
    for g in games:
        check("game", g["urn"])
        check("owner", g["owner_urn"])
        check("node", g["served_by_node"])
        assert g["urn"].endswith(f":{g['id']}")
    print(f"[3/4] {len(games)} jogos com urn:gamerent:game / owner")

    # 4. Reserva recebe urn:gamerent:rental:{uuid_v4}
    available = next(g for g in games if g["status"] == "AVAILABLE")
    status, rental = req(f"{RENTAL}/rentals", "POST", {
        "renter_name": "Self-check #5", "renter_email": "selfcheck5@exemplo.com",
        "game_id": available["id"], "rental_days": 1,
    })
    assert status == 201, f"Locação falhou: {status} {rental}"
    check("rental", rental["urn"])
    assert rental["urn"] == f"urn:gamerent:rental:{rental['rental_id']}"
    assert rental["game_urn"] == available["urn"]
    check("node", rental["served_by_node"])
    req(f"{RENTAL}/rentals/{rental['rental_id']}/return", "POST")
    print(f"[4/4] Locação {rental['urn']}")

    print("OK: Todos os critérios de aceite da Issue #5 (CA-04) validados!")
