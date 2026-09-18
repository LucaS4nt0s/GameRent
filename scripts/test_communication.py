"""
Script de Teste de Comunicação Inter-Serviços — GameRent (Entrega 2)

Este script pode ser executado apontando para localhost ou para o IP público da AWS EC2!
Uso:
    python scripts/test_communication.py
    python scripts/test_communication.py --host ec2-xx-xx-xx-xx.compute-1.amazonaws.com
"""

import sys
import argparse
import urllib.request
import urllib.error
import json
import time

def make_request(url: str, method: str = "GET", data: dict = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data else None

    try:
        with urllib.request.urlopen(req, data=body, timeout=5) as response:
            status_code = response.getcode()
            res_body = json.loads(response.read().decode("utf-8"))
            return status_code, res_body
    except urllib.error.HTTPError as e:
        res_body = json.loads(e.read().decode("utf-8")) if e.fp else {}
        return e.code, res_body
    except Exception as e:
        return 0, {"error": str(e)}

def print_section(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)

def run_tests(host: str, catalog_port: int, rental_port: int):
    catalog_url = f"http://{host}:{catalog_port}"
    rental_url = f"http://{host}:{rental_port}"

    print(f"🚀 Iniciando Bateria de Testes Distribuídos...")
    print(f"👉 Catalog Service: {catalog_url}")
    print(f"👉 Rental Service:  {rental_url}\n")

    # 1. Health Checks
    print_section("1. Teste de Health Check dos Nós")
    c_status, c_data = make_request(f"{catalog_url}/health")
    print(f"[CATALOG-SERVICE] Health: HTTP {c_status} -> {c_data}")

    r_status, r_data = make_request(f"{rental_url}/health")
    print(f"[RENTAL-SERVICE]  Health: HTTP {r_status} -> {r_data}")

    if c_status != 200 or r_status != 200:
        print("\n❌ ERRO: Um ou ambos os serviços não estão saudáveis. Verifique se estão rodando!")
        sys.exit(1)

    # 2. Teste de Geolocalização Relativa (Requisito Arquitetural Entrega 1)
    print_section("2. Teste de Geolocalização Relativa em Memória (Catalog)")
    lat, lon = -23.5505, -46.6333  # Centro de SP
    geo_status, geo_data = make_request(f"{catalog_url}/games/nearby?lat={lat}&lon={lon}&max_km=20")
    print(f"Requisição: GET /games/nearby?lat={lat}&lon={lon}&max_km=20")
    print(f"Resultado: HTTP {geo_status} (Encontrados: {len(geo_data)} jogos)")
    for g in geo_data[:3]:
        print(f"  - [{g['id']}] {g['title']} | Distância: {g['distance_km']} km | Status: {g['status']}")

    # 3. Teste de Comunicação Inter-Serviços (S2S: Rental -> Catalog)
    print_section("3. Teste de Comunicação Síncrona S2S (Rental -> Catalog)")
    rental_payload = {
        "renter_name": "Maria Eduarda Teste",
        "renter_email": "maria@gamerent.com",
        "game_id": 1,  # Catan (inicialmente AVAILABLE)
        "rental_days": 4
    }
    print(f"Requisição: POST {rental_url}/rentals")
    print(f"Payload enviado ao Rental-Service: {json.dumps(rental_payload, indent=2)}")
    
    rent_status, rent_data = make_request(f"{rental_url}/rentals", method="POST", data=rental_payload)
    print(f"Resposta: HTTP {rent_status}")
    print(f"Corpo retornado: {json.dumps(rent_data, indent=2)}")

    if rent_status == 201:
        print("\n✅ SUCESSO: Chamada inter-serviço validada e aluguel confirmado com sucesso!")
        rental_id = rent_data.get("rental_id")
    else:
        print(f"\n⚠️ Status inesperado na criação: {rent_status}")
        rental_id = None

    # 4. Teste de Consistência e Conflito (Double-Booking no mesmo jogo)
    print_section("4. Teste de Validação de Disponibilidade (Evitar Conflito)")
    print("Tentando alugar o mesmo jogo (ID 1) novamente...")
    dup_status, dup_data = make_request(f"{rental_url}/rentals", method="POST", data=rental_payload)
    print(f"Resposta obtida: HTTP {dup_status}")
    print(f"Detalhe: {dup_data.get('detail')}")
    if dup_status == 409:
        print("✅ SUCESSO: O sistema barrou corretamente a tentativa de locação concorrente (HTTP 409)!")

    # 5. Teste de Jogo Inexistente
    print_section("5. Teste de Consulta a Recurso Inexistente")
    bad_payload = {
        "renter_name": "Usuário Teste",
        "renter_email": "teste@exemplo.com",
        "game_id": 9999,
        "rental_days": 2
    }
    bad_status, bad_data = make_request(f"{rental_url}/rentals", method="POST", data=bad_payload)
    print(f"Tentando alugar jogo 9999 -> Resposta: HTTP {bad_status} ({bad_data.get('detail')})")
    if bad_status == 404:
        print("✅ SUCESSO: O serviço tratou o erro 404 adequadamente através da rede!")

    # 6. Teste de Devolução do Jogo (Liberando o recurso)
    if rental_id:
        print_section("6. Teste de Devolução / Liberação do Recurso")
        ret_status, ret_data = make_request(f"{rental_url}/rentals/{rental_id}/return", method="POST")
        print(f"Devolvendo reserva {rental_id} -> HTTP {ret_status}")
        # Conferindo no catálogo
        chk_status, chk_data = make_request(f"{catalog_url}/games/1")
        print(f"Status atual do jogo no catálogo: {chk_data.get('status')}")
        if chk_data.get('status') == "AVAILABLE":
            print("✅ SUCESSO: Jogo liberado no catálogo remoto via chamada REST!")

    print_section("RESUMO DOS TESTES")
    print("🎉 Todos os testes de comunicação inter-serviços foram executados!")
    print("Capture esses outputs para anexar como evidência no relatório da Entrega 2.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Teste de Comunicação GameRent")
    parser.add_argument("--host", default="localhost", help="Host dos serviços (ex: localhost ou IP público EC2)")
    parser.add_argument("--catalog-port", type=int, default=8001, help="Porta do catalog-service")
    parser.add_argument("--rental-port", type=int, default=8002, help="Porta do rental-service")
    args = parser.parse_args()

    run_tests(args.host, args.catalog_port, args.rental_port)
