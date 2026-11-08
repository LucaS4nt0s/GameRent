"""
Bateria de Testes Automatizados — Issue #6: Relógios Lógicos de Lamport (RF-02 / CA-03)
Valida monotonicidade, relação de causalidade (happens-before), sincronização S2S e thread-safety.
"""

import concurrent.futures
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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    src_dir = os.path.join(BASE_DIR, "services", subfolder, "src")
    env = os.environ.copy()
    env["CATALOG_SERVICE_URL"] = "http://127.0.0.1:8001"
    return subprocess.Popen([sys.executable, "app.py"], cwd=src_dir, env=env)


def test_unit_lamport_clock():
    print("\n[1/5] Testes Unitários de Algoritmo e Concorrência Thread-Safe...")
    cat_src = os.path.join(BASE_DIR, "services", "catalog-service", "src")
    if cat_src not in sys.path:
        sys.path.insert(0, cat_src)

    from lamport_clock import LamportClock

    # Teste 1.1: Inicialização e Evento Local
    lc = LamportClock(initial_time=0)
    assert lc.get_time() == 0, f"Tempo inicial esperado 0, obtido {lc.get_time()}"
    t1 = lc.tick()
    assert t1 == 1 and lc.get_time() == 1, "Evento local deve incrementar em +1"
    t2 = lc.tick()
    assert t2 == 2, "Segundo evento local deve incrementar para 2"

    # Teste 1.2: Sincronização com Mensagem Externa com timestamp maior (L = max(L, L_msg) + 1)
    t3 = lc.tick(incoming_time=10)
    assert t3 == 11 and lc.get_time() == 11, f"Esperado 11 apos receber mensagem 10, obtido {t3}"

    # Teste 1.3: Sincronização com Mensagem Externa com timestamp menor (L_msg < L)
    t4 = lc.tick(incoming_time=5)
    assert t4 == 12, f"Mensagem com carimbo defasado deve incrementar relógio local em +1, obtido {t4}"

    # Teste 1.4: Concorrência Extrema (50 threads x 100 ticks = 5000)
    lc.reset(0)
    num_threads = 50
    ticks_per_thread = 100

    def worker():
        for _ in range(ticks_per_thread):
            lc.tick()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker) for _ in range(num_threads)]
        concurrent.futures.wait(futures)

    final_time = lc.get_time()
    expected_time = num_threads * ticks_per_thread
    assert final_time == expected_time, f"Race condition detectada no LamportClock! Esperado {expected_time}, obtido {final_time}"
    print(f"  [OK] Thread-safety comprovado: {num_threads} threads concorrentes geraram exatamente {final_time} ticks sem perda.")


def main():
    print("=" * 75)
    print("  BATERIA DE VALIDAÇÃO OFICIAL — ISSUE #6: RELÓGIO LÓGICO DE LAMPORT")
    print("=" * 75)

    test_unit_lamport_clock()

    started_procs = []
    if not is_service_ready(CATALOG_URL):
        print("\n[INFO] Iniciando Catalog-Service (porta 8001)...")
        p_cat = start_service("catalog-service")
        started_procs.append(p_cat)

    if not is_service_ready(RENTAL_URL):
        print("[INFO] Iniciando Rental-Service (porta 8002)...")
        p_rent = start_service("rental-service")
        started_procs.append(p_rent)

    for _ in range(20):
        if is_service_ready(CATALOG_URL) and is_service_ready(RENTAL_URL):
            break
        time.sleep(0.5)

    try:
        # Prepara estado: força liberação dos jogos de teste
        req(f"{CATALOG_URL}/games/1/release?force=true", method="POST")
        req(f"{CATALOG_URL}/games/2/release?force=true", method="POST")

        # 2. Monotonicidade e Salto Causal via HTTP no Health Check
        print("\n[2/5] Testando Salto Causal e Propagação de Header em GET /health...")
        input_clock = 100
        s_cat, body_cat, h_cat = req(f"{CATALOG_URL}/health", headers={"X-Lamport-Clock": str(input_clock)})
        assert s_cat == 200, f"Health check falhou: {s_cat}"
        cat_resp_clock = int(h_cat.get("x-lamport-clock", 0))
        assert cat_resp_clock > input_clock, f"Header de resposta ({cat_resp_clock}) deve ser > {input_clock}"
        assert body_cat.get("lamport_clock") == cat_resp_clock, "Payload JSON e Header HTTP devem convergir"
        print(f"  [OK] Catalog sincronizou causalmente: Entrada={input_clock} -> Resposta={cat_resp_clock}")

        s_rent, body_rent, h_rent = req(f"{RENTAL_URL}/health", headers={"X-Lamport-Clock": str(cat_resp_clock)})
        assert s_rent == 200
        rent_resp_clock = int(h_rent.get("x-lamport-clock", 0))
        assert rent_resp_clock > cat_resp_clock
        print(f"  [OK] Rental sincronizou causalmente: Entrada={cat_resp_clock} -> Resposta={rent_resp_clock}")

        # 3. Telemetria no Endpoint /discovery
        print("\n[3/5] Testando Exposição de Lamport no Endpoint /discovery...")
        s_disc, b_disc, h_disc = req(f"{CATALOG_URL}/discovery", headers={"X-Lamport-Clock": "500"})
        assert s_disc == 200
        disc_clock = int(h_disc.get("x-lamport-clock", 0))
        assert disc_clock >= 501
        assert b_disc.get("lamport_clock") == disc_clock
        print(f"  [OK] /discovery reflete telemetria de Lamport: Clock={disc_clock}")

        # 4. Encadeamento Causal Completo S2S (Happens-Before em Aluguel Atômico)
        print("\n[4/5] Testando Encadeamento Causal S2S: Cliente -> Rental -> Catalog -> Cliente...")
        client_initial_clock = 1000
        rental_payload = {
            "renter_name": "Lamport Tester",
            "renter_email": "lamport@gamerent.com",
            "game_id": 1,
            "rental_days": 2,
        }
        s_res, b_res, h_res = req(
            f"{RENTAL_URL}/rentals",
            method="POST",
            body=rental_payload,
            headers={"X-Lamport-Clock": str(client_initial_clock)},
        )
        assert s_res == 201, f"Aluguel falhou: {s_res} {b_res}"
        rental_clock = b_res["lamport_clock"]
        header_clock = int(h_res.get("x-lamport-clock", 0))
        assert rental_clock > client_initial_clock, f"Lamport final ({rental_clock}) deve ser > inicial ({client_initial_clock})"
        assert header_clock == rental_clock, "Header e payload devem ser idênticos"

        # Verifica se o jogo no catálogo foi atualizado com carimbo causal
        s_g, b_g, _ = req(f"{CATALOG_URL}/games/1")
        assert s_g == 200
        cat_game_clock = b_g["lamport_clock"]
        assert cat_game_clock >= client_initial_clock, f"Jogo no catalogo ({cat_game_clock}) reflete causalidade da reserva"
        print(f"  [OK] Happens-Before comprovado em transação S2S:")
        print(f"       Cliente ({client_initial_clock}) -> Catálogo Jogo ({cat_game_clock}) -> Recibo Final ({rental_clock})")

        # 5. Devolução com Avanço Causal
        print("\n[5/5] Testando Avanço Causal na Devolução (POST /rentals/{id}/return)...")
        rental_id = b_res["rental_id"]
        s_ret, b_ret, h_ret = req(
            f"{RENTAL_URL}/rentals/{rental_id}/return",
            method="POST",
            headers={"X-Lamport-Clock": str(rental_clock + 10)},
        )
        assert s_ret == 200, f"Devolução falhou: {s_ret} {b_ret}"
        return_clock = b_ret["lamport_clock"]
        assert return_clock > rental_clock + 10
        print(f"  [OK] Devolução avançou relógio causal: Entrada={rental_clock + 10} -> Resposta={return_clock}")

        print("\n" + "=" * 75)
        print("  TODOS OS CRITÉRIOS DE ACEITE DA ISSUE #6 FORAM ATENDIDOS COM SUCESSO!")
        print("=" * 75)

    finally:
        for p in started_procs:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
