"""Self-check para Issue #12 (FA-01 POST /games & FA-05 PATCH /games/{id}/status)."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8001"


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(body).encode("utf-8") if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def ensure_service():
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=1) as resp:
            if resp.status == 200:
                return None
    except Exception:
        pass
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(base_dir, "services", "catalog-service", "src")
    p = subprocess.Popen([sys.executable, "app.py"], cwd=src_dir)
    for _ in range(15):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        time.sleep(0.5)
    return p


if __name__ == "__main__":
    proc = ensure_service()
    try:
        # 1. POST /games -> 201 Created, URN válido, sem vazar latitude/longitude
        status, created = req("POST", "/games", {
            "title": "Azul",
            "description": "Jogo de azulejos portugueses.",
            "category": "Abstrato",
            "price_per_day": 14.0,
            "owner_id": "locador-010",
            "owner_name": "João Silva",
            "latitude": -23.5505,
            "longitude": -46.6333,
        })
        assert status == 201, f"Esperado 201, obtido {status}"
        assert created["urn"] == f"urn:gamerent:game:sa-east-1:{created['id']}"
        assert created["owner_urn"] == "urn:gamerent:owner:locador-010"
        assert created["status"] == "AVAILABLE" and created["version"] == 1 and created["lamport_clock"] >= 1
        assert "latitude" not in created and "longitude" not in created

        # 2. Aparece em GET /games e GET /games/nearby
        _, all_games = req("GET", "/games")
        assert any(g["id"] == created["id"] for g in all_games)
        _, nearby = req("GET", "/games/nearby?lat=-23.5505&lon=-46.6333&max_km=5")
        assert any(g["id"] == created["id"] for g in nearby)

        # 3. Alternar status AVAILABLE <-> MAINTENANCE, bloquear RENTED -> MAINTENANCE (409), MAINTENANCE -> RENTED (409) e permitir devolução RENTED -> AVAILABLE (200)
        s_maint, g_maint = req("PATCH", f"/games/{created['id']}/status", {"status": "MAINTENANCE"})
        assert s_maint == 200 and g_maint["status"] == "MAINTENANCE"
        s_maint_rent, _ = req("PATCH", f"/games/{created['id']}/status", {"status": "RENTED"})
        assert s_maint_rent == 409, f"Esperado 409 para jogo MAINTENANCE -> RENTED, obtido {s_maint_rent}"
        s_conflict, _ = req("PATCH", "/games/4/status", {"status": "MAINTENANCE"})
        assert s_conflict == 409, f"Esperado 409 para jogo RENTED -> MAINTENANCE, obtido {s_conflict}"
        s_return, g_return = req("PATCH", "/games/4/status", {"status": "AVAILABLE"})
        assert s_return == 200 and g_return["status"] == "AVAILABLE", f"Devolução RENTED -> AVAILABLE falhou: {s_return}"
        req("PATCH", "/games/4/status", {"status": "RENTED"})
        print("OK: Todos os critérios de aceite da Issue #12 validados!")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
