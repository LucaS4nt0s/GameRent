"""Self-check para Issue #13 (FA-02: Busca Geográfica com Filtros e Seletor de Consistência)."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8001"
REQUIRED_FIELDS = {
    "urn", "owner_urn", "current_rental_id", "version",
    "lamport_clock", "consistency_mode", "db_read_latency_ms", "served_by_node",
}


def req(path: str) -> tuple[int, dict, dict | list]:
    r = urllib.request.Request(f"{BASE}{path}", method="GET")
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read().decode("utf-8"))


if __name__ == "__main__":
    # 1. GET /games com filtros opcionais (status_filter, category, owner_id) e consistência
    status, headers, items = req("/games?status_filter=AVAILABLE&category=Estrat%C3%A9gia&owner_id=locador-001&consistency=eventual")
    assert status == 200, f"Esperado 200, obtido {status}"
    assert headers.get("X-Consistency-Mode") == "eventual"
    assert "X-DB-Read-Latency-Ms" in headers
    assert len(items) >= 1 and all(g["owner_id"] == "locador-001" and g["status"] == "AVAILABLE" for g in items)
    assert REQUIRED_FIELDS.issubset(items[0].keys())
    assert items[0]["consistency_mode"] == "eventual"
    assert "latitude" not in items[0] and "longitude" not in items[0]

    # 2. GET /games/nearby ordenado por distance_km, sem expor GPS, com filtros e consistência
    s_near, h_near, near = req("/games/nearby?lat=-23.5505&lon=-46.6333&max_km=10&status_filter=AVAILABLE&consistency=strong")
    assert s_near == 200 and h_near.get("X-Consistency-Mode") == "strong"
    dists = [g["distance_km"] for g in near]
    assert dists == sorted(dists), f"Distâncias fora de ordem: {dists}"
    assert all(REQUIRED_FIELDS.issubset(g.keys()) and "latitude" not in g and "longitude" not in g for g in near)

    # 3. GET /games/{id} com consistency=strong e consistency=eventual
    s_g1, h_g1, g1 = req("/games/1?consistency=strong")
    assert s_g1 == 200 and g1["consistency_mode"] == "strong" and REQUIRED_FIELDS.issubset(g1.keys())
    s_g1_ev, h_g1_ev, g1_ev = req("/games/1?consistency=eventual")
    assert s_g1_ev == 200 and g1_ev["consistency_mode"] == "eventual" and "X-DB-Read-Latency-Ms" in h_g1_ev

    print("OK: Todos os critérios de aceite da Issue #13 validados!")
