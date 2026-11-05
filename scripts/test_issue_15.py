"""
Self-check e Validação Automatizada para a Issue #15
Painel 'Meus Aluguéis', Histórico e Devolução de Jogo (FB-02 & FB-03)
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://127.0.0.1:8001")
RENTAL_URL = os.getenv("RENTAL_SERVICE_URL", "http://127.0.0.1:8002")


def req(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict | list, dict]:
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
    print("Bateria de Validacao Automatizada - Issue #15 (Meus Alugueis e Devolucao)")
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
        # Prepara estado: libera jogo 1 e jogo 2
        req(f"{CATALOG_URL}/games/1/release", method="POST")
        req(f"{CATALOG_URL}/games/2/release", method="POST")

        # 1. Criação de cenários de teste (Locatários e Jogos distintos)
        print("\n[1/6] Criando locações de teste para locatários distintos...")
        # Locação A: Ana aluga jogo 1 por 2 dias
        s_a, r_a, _ = req(f"{RENTAL_URL}/rentals", method="POST", body={
            "renter_name": "Ana Paula",
            "renter_email": "ana@gamerent.com",
            "game_id": 1,
            "rental_days": 2
        })
        assert s_a == 201, f"Falha ao criar locação A: {s_a}"
        id_a = r_a["rental_id"]

        # Devolve locação A para que jogo 1 fique disponível para outra locação
        s_ret_a, r_ret_a, _ = req(f"{RENTAL_URL}/rentals/{id_a}/return", method="POST")
        assert s_ret_a == 200 and r_ret_a["status"] == "COMPLETED", f"Falha na devolução A: {s_ret_a}"

        # Locação B: Ana aluga jogo 1 novamente (agora por 4 dias, status CONFIRMED)
        s_b, r_b, _ = req(f"{RENTAL_URL}/rentals", method="POST", body={
            "renter_name": "Ana Paula",
            "renter_email": "ana@gamerent.com",
            "game_id": 1,
            "rental_days": 4
        })
        assert s_b == 201, f"Falha ao criar locação B: {s_b}"
        id_b = r_b["rental_id"]

        # Locação C: Bruno aluga jogo 2 por 3 dias (status CONFIRMED)
        s_c, r_c, _ = req(f"{RENTAL_URL}/rentals", method="POST", body={
            "renter_name": "Bruno Lima",
            "renter_email": "bruno@gamerent.com",
            "game_id": 2,
            "rental_days": 3
        })
        assert s_c == 201, f"Falha ao criar locação C: {s_c}"
        id_c = r_c["rental_id"]
        print("  [OK] Massa de dados de teste criada (Locação A=COMPLETED, B=CONFIRMED, C=CONFIRMED).")

        # 2. Teste FB-02: Filtro por renter_email (Painel 'Meus Aluguéis')
        print("\n[2/6] Testando FB-02: Filtro por renter_email (Painel 'Meus Aluguéis')...")
        s_ana, list_ana, h_ana = req(f"{RENTAL_URL}/rentals?renter_email=ana@gamerent.com")
        assert s_ana == 200, f"Falha na listagem de Ana: {s_ana}"
        assert all(r["renter_email"] == "ana@gamerent.com" for r in list_ana), "Vazou locação de outro locatário!"
        assert any(r["rental_id"] == id_a for r in list_ana), "Locação A não encontrada para Ana"
        assert any(r["rental_id"] == id_b for r in list_ana), "Locação B não encontrada para Ana"
        assert not any(r["rental_id"] == id_c for r in list_ana), "Locação C de Bruno apareceu indevidamente para Ana!"
        assert "x-lamport-clock" in h_ana, "Header X-Lamport-Clock ausente"
        print(f"  [OK] Filtro por renter_email validado: {len(list_ana)} locações encontradas para Ana.")

        # 3. Teste FB-02: Filtro por game_id (Histórico do Locador)
        print("\n[3/6] Testando FB-02: Filtro por game_id (Histórico do Locador)...")
        s_g1, list_g1, _ = req(f"{RENTAL_URL}/rentals?game_id=1")
        assert s_g1 == 200, f"Falha no histórico do jogo 1: {s_g1}"
        assert all(r["game_id"] == 1 for r in list_g1), "Vazou locação de outro jogo!"
        assert len(list_g1) >= 2, f"Esperado ao menos 2 locações para jogo 1, obtido {len(list_g1)}"

        s_g2, list_g2, _ = req(f"{RENTAL_URL}/rentals?game_id=2")
        assert s_g2 == 200, f"Falha no histórico do jogo 2: {s_g2}"
        assert all(r["game_id"] == 2 for r in list_g2)
        assert any(r["rental_id"] == id_c for r in list_g2)
        print(f"  [OK] Filtro por game_id validado: Histórico auditável por exemplar físico.")

        # 4. Teste FB-02: Filtro por status e Filtros Combinados
        print("\n[4/6] Testando Filtro por status e Filtros Combinados...")
        s_comp, list_comp, _ = req(f"{RENTAL_URL}/rentals?status=COMPLETED")
        assert s_comp == 200
        assert all(r["status"] == "COMPLETED" for r in list_comp)
        assert any(r["rental_id"] == id_a for r in list_comp)

        # Combinado: Ana + CONFIRMED -> deve retornar apenas a Locação B
        s_comb, list_comb, _ = req(f"{RENTAL_URL}/rentals?renter_email=ana@gamerent.com&status=CONFIRMED")
        assert s_comb == 200
        assert len(list_comb) == 1 and list_comb[0]["rental_id"] == id_b
        print(f"  [OK] Filtro combinado validado: Locação ativa da Ana identificada com precisão ({id_b}).")

        # 5. Teste FB-03: Devolução de Jogo Alugado e Restauração no Catálogo
        print("\n[5/6] Testando FB-03: Devolução de Jogo (POST /rentals/{id}/return)...")
        s_ret_b, r_ret_b, h_ret_b = req(f"{RENTAL_URL}/rentals/{id_b}/return", method="POST")
        assert s_ret_b == 200, f"Falha na devolução da locação B: {s_ret_b}"
        assert r_ret_b["status"] == "COMPLETED", f"Esperado status COMPLETED, obtido {r_ret_b['status']}"
        assert r_ret_b.get("returned_at") is not None, "Timestamp returned_at ausente na devolução!"
        assert "x-lamport-clock" in h_ret_b

        # Verifica que o jogo 1 voltou para AVAILABLE no catálogo
        _, g1_check, _ = req(f"{CATALOG_URL}/games/1")
        assert g1_check["status"] == "AVAILABLE", f"Jogo 1 deveria estar AVAILABLE após devolução, status atual: {g1_check['status']}"
        print(f"  [OK] Devolução FB-03 concluída: Status=COMPLETED, returned_at={r_ret_b['returned_at']}")
        print(f"  [OK] Catálogo sincronizado: Jogo 1 voltou para AVAILABLE.")

        # 6. Teste de Idempotência da Devolução
        print("\n[6/6] Testando Idempotência de devolução repetida...")
        s_idem, r_idem, _ = req(f"{RENTAL_URL}/rentals/{id_b}/return", method="POST")
        assert s_idem == 200, f"Devolução repetida deveria retornar 200 idempotente, obtido {s_idem}"
        assert r_idem["status"] == "COMPLETED"
        assert r_idem["returned_at"] == r_ret_b["returned_at"]
        print("  [OK] Idempotência comprovada: nenhuma alteração indevida em devolução duplicada.")

        print("\n" + "=" * 70)
        print("TODOS OS CRITERIOS DE ACEITE DA ISSUE #15 FORAM ATENDIDOS COM SUCESSO!")
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
