"""
Bateria Oficial de Testes Distribuídos — GameRent (Entrega 3)
Coordenação (Exclusão Mútua & Lamport), Nomeação (URNs & DNS) e Consistência (Forte vs Eventual).

Executa os 5 cenários do Definition of Done (DoD) da Entrega 3:
  1. Cadastro de jogo pelo locador com validação de URN e privacidade de GPS (FA-01, CA-04)
  2. Disputa concorrente real com 10 threads simultâneas em paralelo (1x 201, 9x 409) (CA-02, RF-01)
  3. Propagação causal monotônica do Relógio Lógico de Lamport (CA-03, RF-02)
  4. Benchmark comparativo de Consistência Forte vs. Eventual (CA-05, RF-06)
  5. Devolução atômica e ciclo de re-reserva (FB-03, CA-01)
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import statistics
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
# Com ADMIN_TOKEN definido nos serviços, a liberação forçada exige este header
ADMIN_HEADERS = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]} if os.getenv("ADMIN_TOKEN") else None
# Opcional: segunda réplica do catálogo (ex.: http://127.0.0.1:8003 no docker compose).
# Com ela, o teste também disputa a reserva entre réplicas, exercitando a escrita condicional no DynamoDB.
CATALOG_REPLICA_2_URL = os.getenv("CATALOG_REPLICA_2_URL")


def req(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict | list, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            resp_headers = {k.lower(): v for k, v in dict(resp.headers).items()}
            raw = resp.read().decode("utf-8")
            res_body = json.loads(raw) if raw else {}
            return resp.status, res_body, resp_headers
    except urllib.error.HTTPError as e:
        resp_headers = {k.lower(): v for k, v in dict(e.headers).items()}
        raw = e.read().decode("utf-8") if e.fp else ""
        res_body = json.loads(raw) if raw else {}
        return e.code, res_body, resp_headers
    except Exception as e:
        return 0, {"error": str(e)}, {}


def is_ready(url: str) -> bool:
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


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(f"  {text}")
    print("=" * 75)


def main():
    print_banner("BATERIA DE TESTES OFICIAL — GAMERENT (ENTREGA 3)")
    procs = []

    if not is_ready(CATALOG_URL):
        print("[INFO] Iniciando catalog-service...")
        procs.append(start_service("catalog-service"))
    if not is_ready(RENTAL_URL):
        print("[INFO] Iniciando rental-service...")
        procs.append(start_service("rental-service"))

    for _ in range(20):
        if is_ready(CATALOG_URL) and is_ready(RENTAL_URL):
            break
        time.sleep(0.5)

    try:
        # Prepara o estado: força liberação dos jogos 1 e 2
        req(f"{CATALOG_URL}/games/1/release?force=true", "POST", headers=ADMIN_HEADERS)
        req(f"{CATALOG_URL}/games/2/release?force=true", "POST", headers=ADMIN_HEADERS)

        # -------------------------------------------------------------
        # 1. Cadastro de Jogo (FA-01, CA-04)
        # -------------------------------------------------------------
        print("\n[1/5] FA-01: Cadastro de jogo pelo locador com URN e privacidade de GPS...")
        status, created, _ = req(f"{CATALOG_URL}/games", "POST", {
            "title": "7 Wonders Duel",
            "description": "Jogo de civilização e estratégia para 2 jogadores.",
            "category": "Estratégia",
            "price_per_day": 16.5,
            "owner_id": "locador-e3",
            "owner_name": "Juliana Mendes",
            "latitude": -23.5505,
            "longitude": -46.6333,
        })
        assert status == 201, f"Falha ao cadastrar jogo: {status} {created}"
        new_id = created["id"]
        assert created["urn"] == f"urn:gamerent:game:sa-east-1:{new_id}"
        assert created["owner_urn"] == "urn:gamerent:owner:locador-e3"
        assert "latitude" not in created and "longitude" not in created, "VAZAMENTO DE GPS DETECTADO!"
        print(f"  [OK] Jogo #{new_id} criado: URN={created['urn']}, Owner={created['owner_urn']}")

        # -------------------------------------------------------------
        # 2. Concorrência Real com 10 Threads Simultâneas (CA-02, RF-01)
        # -------------------------------------------------------------
        print("\n[2/5] CA-02: Disputa concorrente com 10 threads simultâneas tentando reservar o Jogo #1...")
        target_game_id = 1
        results = []

        def worker(thread_idx: int):
            payload = {
                "renter_name": f"Locatário Concorrente #{thread_idx}",
                "renter_email": f"concorrente{thread_idx}@gamerent.com",
                "game_id": target_game_id,
                "rental_days": 2,
            }
            s, body, h = req(f"{RENTAL_URL}/rentals", "POST", body=payload, headers={"X-Lamport-Clock": "20"})
            return s, body, h

        # Dispara 10 requisições simultâneas em paralelo
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i + 1) for i in range(10)]
            results = [f.result() for f in futures]

        status_counts = {}
        winner_rental = None
        for s, body, h in results:
            status_counts[s] = status_counts.get(s, 0) + 1
            if s == 201:
                winner_rental = body

        print(f"  Placar da Concorrência: {status_counts.get(201, 0)}x 201 Created | {status_counts.get(409, 0)}x 409 Conflict")
        assert status_counts.get(201, 0) == 1, f"Exclusão mútua violada! Esperado exatamente 1 sucesso (201), obtido {status_counts.get(201, 0)}"
        assert status_counts.get(409, 0) == 9, f"Esperado exatamente 9 conflitos (409), obtido {status_counts.get(409, 0)}"
        print(f"  [OK] EXCLUSÃO MÚTUA DISTRIBUÍDA COMPROVADA: Vencedor Rental ID={winner_rental['rental_id']}")

        # -------------------------------------------------------------
        # 2b. Disputa entre réplicas (opcional, exige DynamoDB compartilhado)
        # -------------------------------------------------------------
        if CATALOG_REPLICA_2_URL:
            print("\n[2b] CA-02 multi-réplica: 10 reservas simultâneas do Jogo #2 divididas entre as duas réplicas...")
            replicas = [CATALOG_URL, CATALOG_REPLICA_2_URL]
            req(f"{CATALOG_URL}/games/2/release?force=true", "POST", headers=ADMIN_HEADERS)

            def replica_worker(idx: int):
                base = replicas[idx % 2]
                rid = f"00000000-0000-4000-8000-{idx:012d}"
                s, _, _ = req(f"{base}/games/2/reserve", "POST", {"rental_id": rid, "renter_name": f"Réplica #{idx}"})
                return base, s

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                replica_results = list(executor.map(replica_worker, range(10)))
            ok = [base for base, s in replica_results if s == 200]
            conflicts = sum(1 for _, s in replica_results if s == 409)
            print(f"  Placar entre réplicas: {len(ok)}x 200 | {conflicts}x 409 (vencedora: {ok[0] if ok else '-'})")
            assert len(ok) == 1 and conflicts == 9, f"Exclusão mútua entre réplicas violada: {replica_results}"
            _, g2_r1, _ = req(f"{CATALOG_URL}/games/2?consistency=strong")
            _, g2_r2, _ = req(f"{CATALOG_REPLICA_2_URL}/games/2?consistency=strong")
            assert g2_r1["status"] == g2_r2["status"] == "RENTED", "Réplicas divergem sobre o estado do Jogo #2"
            req(f"{CATALOG_URL}/games/2/release?force=true", "POST", headers=ADMIN_HEADERS)
            print("  [OK] Exclusão mútua garantida pelo DynamoDB também entre réplicas.")

        # -------------------------------------------------------------
        # 3. Relógio Lógico de Lamport (CA-03, RF-02)
        # -------------------------------------------------------------
        print("\n[3/5] CA-03: Verificação de monotonicidade e causalidade do Relógio de Lamport...")
        clock_in = 50
        status, health_data, h_resp = req(f"{RENTAL_URL}/health", headers={"X-Lamport-Clock": str(clock_in)})
        assert status == 200
        clock_out = int(h_resp.get("x-lamport-clock", 0))
        assert clock_out > clock_in, f"Lamport não incrementou monotonicamente ({clock_out} <= {clock_in})"
        print(f"  [OK] Causalidade e monotonicidade verificadas: Entrada={clock_in} -> Saída={clock_out}")

        # -------------------------------------------------------------
        # 4. Benchmark: Consistência Forte vs. Eventual (CA-05, RF-06)
        # -------------------------------------------------------------
        print("\n[4/5] CA-05: Benchmark comparativo de leituras (20 fortes vs. 20 eventuais)...")
        latencies_strong = []
        latencies_eventual = []

        # 20 leituras alternadas
        for i in range(20):
            # Leitura Forte
            t0 = time.perf_counter()
            s_s, _, h_s = req(f"{CATALOG_URL}/games?consistency=strong")
            lat_s = float(h_s.get("x-db-read-latency-ms", (time.perf_counter() - t0) * 1000))
            latencies_strong.append(lat_s)

            # Leitura Eventual
            t0 = time.perf_counter()
            s_e, _, h_e = req(f"{CATALOG_URL}/games?consistency=eventual")
            lat_e = float(h_e.get("x-db-read-latency-ms", (time.perf_counter() - t0) * 1000))
            latencies_eventual.append(lat_e)

        avg_s = statistics.mean(latencies_strong)
        avg_e = statistics.mean(latencies_eventual)
        p95_s = sorted(latencies_strong)[int(len(latencies_strong) * 0.95)]
        p95_e = sorted(latencies_eventual)[int(len(latencies_eventual) * 0.95)]

        print("\n  +-----------+----------+--------------------+----------+")
        print("  | Modo      | Leituras | Média Banco (ms)   | p95 (ms) |")
        print("  +-----------+----------+--------------------+----------+")
        print(f"  | Strong    | 20       | {avg_s:>18.2f} | {p95_s:>8.2f} |")
        print(f"  | Eventual  | 20       | {avg_e:>18.2f} | {p95_e:>8.2f} |")
        print("  +-----------+----------+--------------------+----------+")
        print(f"  [OK] Benchmark concluído com sucesso!")

        # -------------------------------------------------------------
        # 5. Devolução e Ciclo Completo (FB-03, CA-01)
        # -------------------------------------------------------------
        print("\n[5/5] FB-03: Devolução atômica da reserva vencedora e liberação do exemplar...")
        rental_id = winner_rental["rental_id"]
        status, ret_obj, _ = req(f"{RENTAL_URL}/rentals/{rental_id}/return", "POST")
        assert status == 200, f"Falha na devolução: {status} {ret_obj}"
        assert ret_obj["status"] == "COMPLETED"

        # Confirma que voltou para AVAILABLE
        _, g_chk, _ = req(f"{CATALOG_URL}/games/{target_game_id}")
        assert g_chk["status"] == "AVAILABLE", f"Jogo {target_game_id} não voltou para AVAILABLE!"
        print(f"  [OK] Devolução confirmada: Jogo #{target_game_id} liberado no catálogo!")

        # Re-aluga para confirmar ciclo
        status, re_rent, _ = req(f"{RENTAL_URL}/rentals", "POST", {
            "renter_name": "Novo Locatário Pós-Devolução",
            "renter_email": "novo@gamerent.com",
            "game_id": target_game_id,
            "rental_days": 1,
        })
        assert status == 201, f"Falha na re-reserva pós-devolução: {status}"
        print(f"  [OK] Ciclo completo validado: Novo Rental ID={re_rent['rental_id']}")

        print_banner("TODOS OS REQUISITOS E CRITÉRIOS DE ACEITE DA ENTREGA 3 FORAM VALIDADOS COM SUCESSO!")

    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
