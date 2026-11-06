"""
Self-check e Validação Automatizada para a Issue #16
Endpoint /discovery e Telemetria Distribuída para o App (FC-01)
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://127.0.0.1:8001")
RENTAL_URL = os.getenv("RENTAL_SERVICE_URL", "http://127.0.0.1:8002")


def req(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8") if body else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            resp_headers = {k.lower(): v for k, v in dict(resp.headers).items()}
            res_body = json.loads(resp.read().decode("utf-8"))
            return resp.status, res_body, resp_headers
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in dict(e.headers).items()}
        res_body = json.loads(e.read().decode("utf-8")) if e.fp else {}
        return e.code, res_body, resp_headers
    except Exception as e:
        return 0, {"error": str(e)}, {}


def is_service_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_service(subfolder: str):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(base_dir, "services", subfolder, "src")
    env = os.environ.copy()
    env["CATALOG_SERVICE_URL"] = "http://127.0.0.1:8001"
    return subprocess.Popen([sys.executable, "app.py"], cwd=src_dir, env=env)


def main():
    print("=" * 70)
    print("Bateria de Validacao Automatizada - Issue #16 (Endpoint /discovery e Telemetria)")
    print("=" * 70)

    started_procs = []
    if not is_service_ready(CATALOG_URL):
        print("[INFO] Iniciando Catalog-Service (porta 8001)...")
        p_cat = start_service("catalog-service")
        started_procs.append(p_cat)

    if not is_service_ready(RENTAL_URL):
        print("[INFO] Iniciando Rental-Service (porta 8002)...")
        p_rent = start_service("rental-service")
        started_procs.append(p_rent)

    for _ in range(15):
        if is_service_ready(CATALOG_URL) and is_service_ready(RENTAL_URL):
            break
        time.sleep(0.5)

    try:
        # 1. Validação de /health atualizado nos dois nós
        print("\n[1/5] Testando GET /health com identidade URN e Lamport...")
        s_c_health, c_health, _ = req(f"{CATALOG_URL}/health")
        s_r_health, r_health, _ = req(f"{RENTAL_URL}/health")

        assert s_c_health == 200, f"Falha no catalog health: {s_c_health}"
        assert s_r_health == 200, f"Falha no rental health: {s_r_health}"

        # Valida campos de nomeação URN e instância no health
        assert c_health["node_urn"].startswith("urn:gamerent:node:catalog-service:"), f"node_urn inválido no catalog: {c_health.get('node_urn')}"
        assert r_health["node_urn"].startswith("urn:gamerent:node:rental-service:"), f"node_urn inválido no rental: {r_health.get('node_urn')}"
        assert "instance_id" in c_health and c_health["instance_id"]
        assert "instance_id" in r_health and r_health["instance_id"]
        assert "lamport_clock" in c_health and isinstance(c_health["lamport_clock"], int)
        assert "lamport_clock" in r_health and isinstance(r_health["lamport_clock"], int)
        # Garante retrocompatibilidade
        assert "total_games" in c_health
        assert "total_rentals" in r_health
        print("  [OK] GET /health atualizado em ambos os nós com URNs e Lamport.")
        print(f"       Catalog Node URN: {c_health['node_urn']}")
        print(f"       Rental Node URN:  {r_health['node_urn']}")

        # 2. Validação do GET /discovery no Catalog-Service
        print("\n[2/5] Testando GET /discovery no Catalog-Service...")
        s_c_disc, c_disc, _ = req(f"{CATALOG_URL}/discovery")
        assert s_c_disc == 200, f"Falha no catalog discovery: {s_c_disc}"
        assert c_disc["service"] == "catalog-service"
        assert c_disc["node_urn"].startswith("urn:gamerent:node:catalog-service:")
        assert "hostname" in c_disc and c_disc["hostname"]
        assert "local_ip" in c_disc and c_disc["local_ip"]
        assert "dns_target" in c_disc
        assert "dns_resolution" in c_disc
        assert c_disc["dns_resolution"]["status"] in ("RESOLVED", "UNRESOLVED")
        assert isinstance(c_disc["dns_resolution"]["resolved_ips"], list)
        assert "dynamodb" in c_disc
        assert c_disc["dynamodb"]["table_name"] == "gamerent_games"
        assert c_disc["dynamodb"]["mode"] in ("AWS_DYNAMODB", "LOCAL_DYNAMODB", "IN_MEMORY_FALLBACK")
        assert "timestamp" in c_disc
        print(f"  [OK] Discovery Catalog validado:")
        print(f"       Node URN:       {c_disc['node_urn']}")
        print(f"       Local Host/IP:  {c_disc['hostname']} ({c_disc['local_ip']})")
        print(f"       DNS Target:     {c_disc['dns_target']} -> Status: {c_disc['dns_resolution']['status']} (IPs: {c_disc['dns_resolution']['resolved_ips']})")
        print(f"       DynamoDB Table: {c_disc['dynamodb']['table_name']} (Mode: {c_disc['dynamodb']['mode']})")

        # 3. Validação do GET /discovery no Rental-Service
        print("\n[3/5] Testando GET /discovery no Rental-Service...")
        s_r_disc, r_disc, _ = req(f"{RENTAL_URL}/discovery")
        assert s_r_disc == 200, f"Falha no rental discovery: {s_r_disc}"
        assert r_disc["service"] == "rental-service"
        assert r_disc["node_urn"].startswith("urn:gamerent:node:rental-service:")
        assert "dns_resolution" in r_disc
        assert r_disc["dns_resolution"]["status"] in ("RESOLVED", "UNRESOLVED")
        assert r_disc["dynamodb"]["table_name"] == "gamerent_rentals"
        print(f"  [OK] Discovery Rental validado:")
        print(f"       Node URN:       {r_disc['node_urn']}")
        print(f"       DNS Target:     {r_disc['dns_target']} -> Status: {r_disc['dns_resolution']['status']} (IPs: {r_disc['dns_resolution']['resolved_ips']})")
        print(f"       DynamoDB Table: {r_disc['dynamodb']['table_name']} (Mode: {r_disc['dynamodb']['mode']})")

        # 4. Teste de Sincronização e Telemetria do Relógio de Lamport
        print("\n[4/5] Testando propagação e telemetria de Relógio Lógico no /discovery...")
        s_lamp, disc_lamp, h_lamp = req(f"{RENTAL_URL}/discovery", headers={"X-Lamport-Clock": "100"})
        assert s_lamp == 200
        clock_returned = disc_lamp["lamport_clock"]
        assert clock_returned > 100, f"Lamport clock ({clock_returned}) deveria ser > 100"
        header_clock = int(h_lamp.get("x-lamport-clock", 0))
        assert header_clock > 100, f"Header X-Lamport-Clock ({header_clock}) deveria ser > 100"
        print(f"  [OK] Lamport Clock telemetria confirmada: Entrada=100 -> Saída={clock_returned} (Header={header_clock})")

        # 5. Teste de Resiliência de Resolução DNS
        print("\n[5/5] Testando resiliência da resolução DNS com target tolerante...")
        # A resolução foi executada sem erros 500 mesmo se o host não existir no DNS local
        assert c_disc["dns_resolution"]["status"] in ("RESOLVED", "UNRESOLVED")
        assert r_disc["dns_resolution"]["status"] in ("RESOLVED", "UNRESOLVED")
        print("  [OK] Resolução DNS resiliente comprovada (sem exceções não tratadas).")

        print("\n" + "=" * 70)
        print("TODOS OS CRITERIOS DE ACEITE DA ISSUE #16 FORAM ATENDIDOS COM SUCESSO!")
        print("=" * 70)

    finally:
        for p in started_procs:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
