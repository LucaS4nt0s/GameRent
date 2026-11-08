"""
Validação da Comunicação Inter-Serviços via Amazon SQS.
Testa o fluxo completo de reserva, exclusão mútua e devolução via mensageria SQS.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001")
RENTAL_URL = os.getenv("RENTAL_SERVICE_URL", "http://localhost:8002")
ADMIN_HEADERS = {"X-Admin-Token": os.environ["ADMIN_TOKEN"]} if os.getenv("ADMIN_TOKEN") else None


def req(url: str, method: str = "GET", body: dict = None, headers: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8")) if e.fp else {}


def main():
    print("🚀 Teste de Mensageria Inter-Serviços com Amazon SQS")

    # 1. Health check
    s_c, c_data = req(f"{CATALOG_URL}/health")
    s_r, r_data = req(f"{RENTAL_URL}/health")
    assert s_c == 200, f"Catalog indisponível: {s_c}"
    assert s_r == 200, f"Rental indisponível: {s_r}"
    print(f"✅ Health checks OK: Catalog (relógio={c_data['lamport_clock']}), Rental (relógio={r_data['lamport_clock']})")

    # Garante que o jogo 1 está livre
    req(f"{CATALOG_URL}/games/1/release?force=true", method="POST", headers=ADMIN_HEADERS)

    # 2. Criação de aluguel via Rental -> SQS -> Catalog
    print("\n[1/4] Testando criação de locação via mensagem Amazon SQS...")
    payload = {
        "renter_name": "Usuário SQS Teste",
        "renter_email": "sqs@gamerent.com",
        "game_id": 1,
        "rental_days": 3
    }
    status, rent_data = req(f"{RENTAL_URL}/rentals", method="POST", body=payload)
    assert status == 201, f"Falha ao criar aluguel via SQS: {status} -> {rent_data}"
    rental_id = rent_data["rental_id"]
    print(f"✅ Aluguel criado com sucesso via SQS! ID={rental_id}, Total=R$ {rent_data['total_price']}")

    # 3. Exclusão mútua (409 Conflict) via SQS
    print("\n[2/4] Testando concorrência/bloqueio de double-booking via SQS...")
    dup_status, dup_data = req(f"{RENTAL_URL}/rentals", method="POST", body=payload)
    assert dup_status == 409, f"Deveria retornar 409, retornou {dup_status}: {dup_data}"
    print("✅ Double-booking bloqueado corretamente com 409 Conflict via SQS!")

    # 4. Jogo inexistente (404 Not Found) via SQS
    print("\n[3/4] Testando consulta a jogo inexistente via SQS...")
    bad_payload = {**payload, "game_id": 99999}
    bad_status, bad_data = req(f"{RENTAL_URL}/rentals", method="POST", body=bad_payload)
    assert bad_status == 404, f"Deveria retornar 404, retornou {bad_status}: {bad_data}"
    print("✅ Jogo inexistente rejeitado com 404 Not Found via SQS!")

    # 5. Devolução de aluguel via SQS
    print("\n[4/4] Testando devolução de exemplar via mensagem SQS...")
    ret_status, ret_data = req(f"{RENTAL_URL}/rentals/{rental_id}/return", method="POST")
    assert ret_status == 200, f"Falha na devolução: {ret_status} -> {ret_data}"
    assert ret_data["status"] == "COMPLETED"

    # Confirma que jogo está AVAILABLE novamente no catálogo
    _, game = req(f"{CATALOG_URL}/games/1")
    assert game["status"] == "AVAILABLE", f"Jogo deveria estar AVAILABLE, está {game['status']}"
    print(f"✅ Devolução concluída via SQS e jogo 1 liberado para AVAILABLE!")

    print("\n🎉 Todos os testes de mensageria Amazon SQS passaram com sucesso!")


if __name__ == "__main__":
    main()
