"""
Self-check e Validação Automatizada para a Issue #14
Fluxo de Reserva e Liberação Atômica de Exemplar (FA-03, FA-04 e FB-01)
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
    print("Bateria de Validacao Automatizada - Issue #14 (Reserva Atomica)")
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

    # Aguarda inicializacao
    for _ in range(15):
        if is_service_ready(CATALOG_URL) and is_service_ready(RENTAL_URL):
            break
        time.sleep(0.5)

    try:
        # 1. Health Checks e Lamport Clock inicial
        print("\n[1/7] Testando Health Checks e Lamport Clocks...")
        c_status, c_data, _ = req(f"{CATALOG_URL}/health")
        r_status, r_data, _ = req(f"{RENTAL_URL}/health")
        assert c_status == 200, f"Catalog health falhou: {c_status}"
        assert r_status == 200, f"Rental health falhou: {r_status}"
        assert "lamport_clock" in c_data, "lamport_clock ausente no catalog health"
        assert "lamport_clock" in r_data, "lamport_clock ausente no rental health"
        print("  [OK] Health checks operacionais com relogios de Lamport.")

        # 2. Teste Direto: POST /games/{id}/reserve (Catalog)
        print("\n[2/7] Testando Reserva Atomica direta no Catalog (POST /games/2/reserve)...")
        req(f"{CATALOG_URL}/games/2/release?force=true", method="POST")
        s_res, g_res, h_res = req(
            f"{CATALOG_URL}/games/2/reserve",
            method="POST",
            body={"rental_id": "test-uuid-002", "renter_name": "KauaN Tester"},
            headers={"X-Lamport-Clock": "5"}
        )
        assert s_res == 200, f"Esperado 200 ao reservar jogo 2 disponivel, obtido {s_res}: {g_res}"
        assert g_res["status"] == "RENTED", f"Esperado status RENTED, obtido {g_res['status']}"
        assert g_res["current_rental_id"] == "test-uuid-002"
        clock_returned = int(h_res.get("x-lamport-clock", 0))
        assert clock_returned > 5, f"Lamport clock ({clock_returned}) nao avancou alem de 5"
        print(f"  [OK] Reserva atomica no catalogo funcionou! URN={g_res['urn']}, Status={g_res['status']}, Lamport={clock_returned}")

        # 2.1 Teste de Idempotencia: Repetir a mesma reserva (mesmo rental_id) deve responder 200 OK
        s_idem, g_idem, _ = req(
            f"{CATALOG_URL}/games/2/reserve",
            method="POST",
            body={"rental_id": "test-uuid-002", "renter_name": "KauaN Tester"}
        )
        assert s_idem == 200, f"Esperado 200 em retentativa idempotente, obtido {s_idem}: {g_idem}"
        print("  [OK] Retentativa de reserva idempotente confirmada com 200 OK.")

        # 3. Teste Direto de Conflito: Repetir reserva no jogo 2 para OUTRO rental_id
        print("\n[3/7] Testando Prevencao de Conflito 409 no Catalogo...")
        s_dup, g_dup, _ = req(
            f"{CATALOG_URL}/games/2/reserve",
            method="POST",
            body={"rental_id": "test-uuid-dup", "renter_name": "Outro Locatario"}
        )
        assert s_dup == 409, f"Esperado 409 ao tentar reservar jogo ja RENTED por outro, obtido {s_dup}"
        print(f"  [OK] Conflito 409 bloqueado com sucesso pelo catalogo: {g_dup.get('detail')}")

        # 4. Teste de Seguranca e Liberacao Atomica: POST /games/{id}/release (Catalog)
        print("\n[4/7] Testando Seguranca e Liberacao Atomica no Catalog (POST /games/2/release)...")
        # 4.1 Tentativa de liberacao sem rental_id deve ser bloqueada com 409
        s_unauth, g_unauth, _ = req(f"{CATALOG_URL}/games/2/release", method="POST")
        assert s_unauth == 409, f"Esperado 409 ao tentar liberar jogo alugado sem rental_id, obtido {s_unauth}"
        print(f"  [OK] Tentativa de liberacao sem rental_id bloqueada com 409: {g_unauth.get('detail')}")

        # 4.2 Tentativa de liberacao com rental_id incorreto deve ser bloqueada com 409
        s_wrong, g_wrong, _ = req(
            f"{CATALOG_URL}/games/2/release",
            method="POST",
            body={"rental_id": "wrong-rental-uuid"}
        )
        assert s_wrong == 409, f"Esperado 409 ao tentar liberar jogo com rental_id invalido, obtido {s_wrong}"
        print(f"  [OK] Tentativa com rental_id divergente bloqueada com 409: {g_wrong.get('detail')}")

        # 4.3 Liberacao com rental_id correto deve ter sucesso
        s_rel, g_rel, _ = req(
            f"{CATALOG_URL}/games/2/release",
            method="POST",
            body={"rental_id": "test-uuid-002"}
        )
        assert s_rel == 200, f"Esperado 200 ao liberar jogo com rental_id correto, obtido {s_rel}"
        assert g_rel["status"] == "AVAILABLE", f"Esperado status AVAILABLE, obtido {g_rel['status']}"
        assert g_rel.get("current_rental_id") is None, "current_rental_id nao foi anulado na liberacao"
        print(f"  [OK] Jogo liberado com sucesso: Status={g_rel['status']}, current_rental_id={g_rel.get('current_rental_id')}")

        # 5. Fluxo End-to-End: POST /rentals no Rental-Service (Aluguel Atomico Completo)
        print("\n[5/7] Testando Fluxo Integrado S2S (POST /rentals -> POST /games/1/reserve)...")
        req(f"{CATALOG_URL}/games/1/release?force=true", method="POST")
        rental_payload = {
            "renter_name": "KauaN Santos",
            "renter_email": "kauan@gamerent.com",
            "game_id": 1,
            "rental_days": 3
        }
        s_rent, r_obj, h_rent = req(
            f"{RENTAL_URL}/rentals",
            method="POST",
            body=rental_payload,
            headers={"X-Lamport-Clock": "10"}
        )
        assert s_rent == 201, f"Esperado 201 Created na locacao, obtido {s_rent}: {r_obj}"
        assert "rental_id" in r_obj and r_obj["rental_id"]
        assert r_obj["urn"].startswith("urn:gamerent:rental:")
        assert r_obj["game_urn"] == "urn:gamerent:game:sa-east-1:1"
        assert r_obj["daily_rate"] == 15.0
        assert r_obj["total_price"] == 45.0
        assert r_obj["status"] == "CONFIRMED"
        assert r_obj["lamport_clock"] > 10
        assert "x-lamport-clock" in h_rent
        rental_id = r_obj["rental_id"]
        print(f"  [OK] Locacao criada com sucesso! ID={rental_id}")
        print(f"       URN: {r_obj['urn']}")
        print(f"       Game URN: {r_obj['game_urn']}")
        print(f"       Total: R$ {r_obj['total_price']} ({r_obj['rental_days']} dias x R$ {r_obj['daily_rate']})")
        print(f"       Lamport Clock: {r_obj['lamport_clock']}")

        # 6. Teste de Exclusao Mutua End-to-End: Double-Booking no Rental-Service
        print("\n[6/7] Testando Concorrencia/Double-Booking via POST /rentals...")
        s_conflict, c_obj, _ = req(f"{RENTAL_URL}/rentals", method="POST", body=rental_payload)
        assert s_conflict == 409, f"Esperado 409 Conflict no double-booking, obtido {s_conflict}: {c_obj}"
        print(f"  [OK] Double-booking bloqueado com 409 Conflict: {c_obj.get('detail')}")

        # 7. Teste de Devolucao e Re-reserva
        print("\n[7/7] Testando Devolucao (POST /rentals/{id}/return) e Re-reserva subsequente...")
        s_ret, ret_obj, _ = req(f"{RENTAL_URL}/rentals/{rental_id}/return", method="POST")
        assert s_ret == 200, f"Esperado 200 na devolucao, obtido {s_ret}"
        assert ret_obj["status"] == "COMPLETED"
        assert ret_obj.get("returned_at") is not None

        # Confirma que jogo 1 voltou para AVAILABLE no catalogo
        _, g_cat_check, _ = req(f"{CATALOG_URL}/games/1")
        assert g_cat_check["status"] == "AVAILABLE", f"Jogo 1 deveria estar AVAILABLE apos devolucao, obtido {g_cat_check['status']}"

        # Agora deve ser possivel alugar novamente
        s_rent_again, r_again, _ = req(f"{RENTAL_URL}/rentals", method="POST", body=rental_payload)
        assert s_rent_again == 201, f"Esperado 201 na re-reserva apos devolucao, obtido {s_rent_again}"
        print(f"  [OK] Devolucao e re-reserva concluidas com sucesso! Novo Rental={r_again['rental_id']}")

        print("\n" + "=" * 70)
        print("TODOS OS CRITERIOS DE ACEITE DA ISSUE #14 FORAM ATENDIDOS COM SUCESSO!")
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
