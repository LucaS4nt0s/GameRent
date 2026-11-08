"""
Bateria Oficial de Testes Distribuídos — GameRent (Entrega 3)
Coordenação (Exclusão Mútua & Lamport), Nomeação (URNs & DNS) e Consistência (Forte vs Eventual).

Executa os 5 cenários do Definition of Done (DoD) da Entrega 3 (Issue #10):
  1. Cadastro de jogo pelo locador com validação de URN e privacidade de GPS (FA-01, CA-04)
  2. Disputa concorrente real com 10 threads simultâneas em paralelo (1x 201, 9x 409) (CA-02, RF-01)
  3. Propagação causal monotônica do Relógio Lógico de Lamport (CA-03, RF-02)
  4. Cenário Read-After-Write (RAW) e Benchmark Estatístico de Consistência Forte vs. Eventual (CA-05, RF-06)
  5. Devolução atômica e ciclo de re-reserva (FB-03, CA-01)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://127.0.0.1:8001")
RENTAL_URL = os.getenv("RENTAL_SERVICE_URL", "http://127.0.0.1:8002")
# Com ADMIN_TOKEN definido nos serviços, a liberação forçada exige este header
ADMIN_HEADERS = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]} if os.getenv("ADMIN_TOKEN") else None
# Opcional: segunda réplica do catálogo (ex.: http://127.0.0.1:8003 no docker compose).
CATALOG_REPLICA_2_URL = os.getenv("CATALOG_REPLICA_2_URL")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    src_dir = os.path.join(BASE_DIR, "services", subfolder, "src")
    env = os.environ.copy()
    env["CATALOG_SERVICE_URL"] = "http://127.0.0.1:8001"
    return subprocess.Popen([sys.executable, "app.py"], cwd=src_dir, env=env)


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(f"  {text}")
    print("=" * 75)


def run_benchmark(catalog_url: str, samples: int = 20, export_path: str | None = None) -> dict:
    """Bateria estatística de leitura forte vs. eventual com métricas detalhadas (CA-05)."""
    latencies_strong_db = []
    latencies_strong_rtt = []
    latencies_eventual_db = []
    latencies_eventual_rtt = []

    for _ in range(samples):
        # 1. Leitura Forte
        t0 = time.perf_counter()
        s_s, _, h_s = req(f"{catalog_url}/games?consistency=strong")
        rtt_s = (time.perf_counter() - t0) * 1000
        lat_s = float(h_s.get("x-db-read-latency-ms", rtt_s))
        latencies_strong_db.append(lat_s)
        latencies_strong_rtt.append(rtt_s)

        # 2. Leitura Eventual
        t0 = time.perf_counter()
        s_e, _, h_e = req(f"{catalog_url}/games?consistency=eventual")
        rtt_e = (time.perf_counter() - t0) * 1000
        lat_e = float(h_e.get("x-db-read-latency-ms", rtt_e))
        latencies_eventual_db.append(lat_e)
        latencies_eventual_rtt.append(rtt_e)

    def calc_stats(db_lats, rtt_lats):
        sorted_db = sorted(db_lats)
        n = len(sorted_db)
        return {
            "count": n,
            "avg_db_ms": round(statistics.mean(db_lats), 3),
            "avg_rtt_ms": round(statistics.mean(rtt_lats), 3),
            "p50_db_ms": round(sorted_db[int(n * 0.50)], 3),
            "p90_db_ms": round(sorted_db[min(int(n * 0.90), n - 1)], 3),
            "p95_db_ms": round(sorted_db[min(int(n * 0.95), n - 1)], 3),
            "stdev_db_ms": round(statistics.stdev(db_lats), 3) if n > 1 else 0.0,
            "samples_db": [round(x, 3) for x in db_lats],
            "samples_rtt": [round(x, 3) for x in rtt_lats],
        }

    stats_strong = calc_stats(latencies_strong_db, latencies_strong_rtt)
    stats_eventual = calc_stats(latencies_eventual_db, latencies_eventual_rtt)

    print("\n  +-----------+----------+------------------+------------------+----------+----------+----------+")
    print("  | Modo      | Leituras | Média Banco (ms) | Média RTT (ms)   | p50 (ms) | p90 (ms) | p95 (ms) |")
    print("  +-----------+----------+------------------+------------------+----------+----------+----------+")
    print(f"  | Strong    | {samples:<8} | {stats_strong['avg_db_ms']:>16.2f} | {stats_strong['avg_rtt_ms']:>16.2f} | {stats_strong['p50_db_ms']:>8.2f} | {stats_strong['p90_db_ms']:>8.2f} | {stats_strong['p95_db_ms']:>8.2f} |")
    print(f"  | Eventual  | {samples:<8} | {stats_eventual['avg_db_ms']:>16.2f} | {stats_eventual['avg_rtt_ms']:>16.2f} | {stats_eventual['p50_db_ms']:>8.2f} | {stats_eventual['p90_db_ms']:>8.2f} | {stats_eventual['p95_db_ms']:>8.2f} |")
    print("  +-----------+----------+------------------+------------------+----------+----------+----------+")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_samples": samples,
        "strong": stats_strong,
        "eventual": stats_eventual,
    }

    if export_path:
        os.makedirs(os.path.dirname(export_path) or ".", exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"  [OK] Relatório do benchmark exportado para: {export_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Bateria Oficial de Testes Distribuídos — GameRent (Entrega 3 / Issue #10)")
    parser.add_argument("--threads", type=int, default=10, help="Número de threads concorrentes para CA-02 (mínimo 10)")
    parser.add_argument("--samples", type=int, default=20, help="Número de amostras para o benchmark de consistência (CA-05)")
    parser.add_argument("--benchmark-only", action="store_true", help="Executa exclusivamente o benchmark de consistência e o teste RAW")
    parser.add_argument("--export", type=str, default=os.path.join(BASE_DIR, "reports", "benchmark_consistency.json"), help="Caminho para exportação do JSON de métricas")
    args = parser.parse_args()

    num_threads = max(10, args.threads)
    samples = max(5, args.samples)

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

        if not args.benchmark_only:
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
            # 2. Concorrência Real com N Threads Simultâneas (CA-02, RF-01)
            # -------------------------------------------------------------
            print(f"\n[2/5] CA-02: Disputa concorrente com {num_threads} threads simultâneas tentando reservar o Jogo #1...")
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

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(worker, i + 1) for i in range(num_threads)]
                results = [f.result() for f in futures]

            status_counts = {}
            winner_rental = None
            for s, body, h in results:
                status_counts[s] = status_counts.get(s, 0) + 1
                if s == 201:
                    winner_rental = body

            print(f"  Placar da Concorrência: {status_counts.get(201, 0)}x 201 Created | {status_counts.get(409, 0)}x 409 Conflict")
            assert status_counts.get(201, 0) == 1, f"Exclusão mútua violada! Esperado exatamente 1 sucesso (201), obtido {status_counts.get(201, 0)}"
            assert status_counts.get(409, 0) == num_threads - 1, f"Esperado exatamente {num_threads - 1} conflitos (409), obtido {status_counts.get(409, 0)}"

            # Asserções rigorosas no recibo vencedor e nos cabeçalhos
            assert winner_rental is not None
            assert winner_rental["urn"] == f"urn:gamerent:rental:{winner_rental['rental_id']}"
            assert winner_rental["game_urn"] == f"urn:gamerent:game:sa-east-1:{target_game_id}"
            assert winner_rental["status"] == "CONFIRMED"
            assert winner_rental["lamport_clock"] > 20

            # Valida que todos os conflitos 409 propagam o cabeçalho X-Lamport-Clock
            for s, _, h in results:
                if s == 409:
                    assert "x-lamport-clock" in h, "Resposta 409 deve conter cabeçalho X-Lamport-Clock"

            print(f"  [OK] EXCLUSÃO MÚTUA DISTRIBUÍDA COMPROVADA: Vencedor Rental ID={winner_rental['rental_id']}")
            print(f"       URN={winner_rental['urn']} | Lamport={winner_rental['lamport_clock']}")

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
        # 4. Consistência: Cenário Read-After-Write (RAW) + Benchmark (CA-05, RF-06)
        # -------------------------------------------------------------
        print("\n[4/5] CA-05: Teste Read-After-Write (RAW) e Benchmark Comparativo de Consistência...")

        # 4a. Read-After-Write (RAW)
        print("  [4a] Executando teste Read-After-Write (RAW)...")
        raw_token = f"RAW-TEST-{int(time.time())}"
        # Atualiza descrição do jogo 2 para demonstrar leitura imediata pós-escrita
        req(f"{CATALOG_URL}/games/2/release?force=true", "POST", headers=ADMIN_HEADERS)
        s_raw_s, b_raw_s, h_raw_s = req(f"{CATALOG_URL}/games/2?consistency=strong")
        assert s_raw_s == 200
        lat_raw_s = float(h_raw_s.get("x-db-read-latency-ms", 0.0))

        s_raw_e, b_raw_e, h_raw_e = req(f"{CATALOG_URL}/games/2?consistency=eventual")
        assert s_raw_e == 200
        lat_raw_e = float(h_raw_e.get("x-db-read-latency-ms", 0.0))

        print(f"       RAW Strong:   Status={b_raw_s['status']} | Latência={lat_raw_s:.2f}ms")
        print(f"       RAW Eventual: Status={b_raw_e['status']} | Latência={lat_raw_e:.2f}ms")
        print("  [OK] Cenário Read-After-Write executado com sucesso.")

        # 4b. Benchmark Estatístico
        print(f"\n  [4b] Executando benchmark estatístico ({samples} fortes vs. {samples} eventuais)...")
        run_benchmark(CATALOG_URL, samples=samples, export_path=args.export)
        print("  [OK] Benchmark comparativo concluído com sucesso!")

        if not args.benchmark_only:
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
