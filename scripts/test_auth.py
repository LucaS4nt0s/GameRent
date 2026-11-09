"""Self-check da autenticação/autorização com Cognito (AUTH_PROVIDER=cognito), sem precisar da AWS.

Gera um par de chaves RSA, publica o JWKS num servidor HTTP local e emite id_tokens no mesmo formato
do Amazon Cognito (iss, aud, token_use, cognito:groups). Sobe catalog-service (:8001) e
rental-service (:8002) com AUTH_PROVIDER=cognito e SERVICE_TOKEN e verifica as regras de acesso.

Requer: pip install "PyJWT[crypto]" fastapi uvicorn httpx boto3
SQS: use o ElasticMQ local (`docker compose up -d sqs-local`) ou defina SQS_ENDPOINT_URL.
"""
from __future__ import annotations

import base64
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CATALOG, RENTAL = "http://127.0.0.1:8001", "http://127.0.0.1:8002"
REGION, POOL, CLIENT = "sa-east-1", "sa-east-1_TESTPOOL", "test-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
JWKS_PORT = 8099
SERVICE_TOKEN = "segredo-interno-teste"
KID = "chave-teste"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


PUB = KEY.public_key().public_numbers()
JWKS = {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256", "n": _b64(PUB.n), "e": _b64(PUB.e)}]}


class JwksHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(JWKS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def token(sub: str, email: str, groups: list[str] | None = None, *, key=KEY, aud=CLIENT, use="id", exp_in=3600) -> str:
    now = int(time.time())
    claims = {
        "sub": sub, "email": email, "name": sub.title(), "iss": ISSUER, "aud": aud,
        "token_use": use, "iat": now, "exp": now + exp_in,
    }
    if groups:
        claims["cognito:groups"] = groups
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


def req(url, method="GET", body=None, tok=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            raw = x.read()
            return x.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else {})


def wait(url):
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{url} não subiu")


def start(service: str, port: int):
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", service, "src")
    env = {
        **os.environ,
        "AUTH_PROVIDER": "cognito", "COGNITO_REGION": REGION, "COGNITO_USER_POOL_ID": POOL,
        "COGNITO_CLIENT_ID": CLIENT, "COGNITO_JWKS_URL": f"http://127.0.0.1:{JWKS_PORT}/jwks.json",
        "SERVICE_TOKEN": SERVICE_TOKEN, "CATALOG_SERVICE_URL": CATALOG,
        "SQS_ENDPOINT_URL": os.getenv("SQS_ENDPOINT_URL", "http://127.0.0.1:9324"),
    }
    env.pop("DYNAMODB_ENDPOINT_URL", None)
    env.pop("USE_DYNAMODB", None)
    env.pop("ADMIN_TOKEN", None)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)],
        cwd=src, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def check(label, got, expected):
    ok = got in expected if isinstance(expected, set) else got == expected
    print(f"  {'[OK]' if ok else '[FALHOU]'} {label}: {got}")
    assert ok, f"{label}: esperado {expected}, obtido {got}"


if __name__ == "__main__":
    srv = http.server.HTTPServer(("127.0.0.1", JWKS_PORT), JwksHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    procs = [start("catalog-service", 8001)]
    wait(CATALOG)
    procs.append(start("rental-service", 8002))
    wait(RENTAL)

    ana = token("ana-sub", "ana@exemplo.com")
    bia = token("bia-sub", "bia@exemplo.com")
    admin = token("adm-sub", "admin@exemplo.com", ["admin"])
    try:
        print("[1] Tokens inválidos são recusados")
        body = {"renter_name": "Ana", "renter_email": "ana@exemplo.com", "game_id": 1, "rental_days": 1}
        check("sem token", req(f"{RENTAL}/rentals", "POST", body)[0], 401)
        check("expirado", req(f"{RENTAL}/rentals", "POST", body, token("ana-sub", "a@x", exp_in=-60))[0], 401)
        check("assinado por outra chave", req(f"{RENTAL}/rentals", "POST", body, token("ana-sub", "a@x", key=OTHER_KEY))[0], 401)
        check("audiência errada", req(f"{RENTAL}/rentals", "POST", body, token("ana-sub", "a@x", aud="outro-app"))[0], 401)
        check("access_token em vez de id_token", req(f"{RENTAL}/rentals", "POST", body, token("ana-sub", "a@x", use="access"))[0], 401)
        check("cabeçalho mal formado", req(f"{RENTAL}/rentals", "POST", body, headers={"Authorization": "Token abc"})[0], 401)

        print("[2] O locatário vem do token, não do corpo")
        s, rental = req(f"{RENTAL}/rentals", "POST", {**body, "renter_email": "vitima@exemplo.com"}, ana)
        check("Ana aluga o jogo 1", s, 201)
        check("e-mail gravado é o da Ana", rental["renter_email"], "ana@exemplo.com")

        print("[3] Cada um só vê e devolve as próprias locações")
        s, lst = req(f"{RENTAL}/rentals?renter_email=ana@exemplo.com", tok=bia)
        check("Bia pedindo as locações da Ana recebe só as dela (0)", len(lst), 0)
        check("Bia não vê a locação da Ana", req(f"{RENTAL}/rentals/{rental['rental_id']}", tok=bia)[0], 404)
        check("Bia não devolve a locação da Ana", req(f"{RENTAL}/rentals/{rental['rental_id']}/return", "POST", tok=bia)[0], 404)
        s, lst = req(f"{RENTAL}/rentals", tok=admin)
        check("admin vê todas", len(lst) >= 1, True)
        check("Ana devolve a própria locação", req(f"{RENTAL}/rentals/{rental['rental_id']}/return", "POST", tok=ana)[0], 200)

        print("[4] Anúncios: dono vem do token e só ele altera o status")
        game = {"title": "Azul", "description": "x", "category": "Abstrato", "price_per_day": 9,
                "owner_id": "bia-sub", "owner_name": "Ana", "latitude": -23.5, "longitude": -46.6}
        check("anunciar sem login", req(f"{CATALOG}/games", "POST", game)[0], 401)
        s, g = req(f"{CATALOG}/games", "POST", game, ana)
        check("Ana anuncia", s, 201)
        check("owner_id gravado é o da Ana (não o do corpo)", g["owner_id"], "ana-sub")
        check("Bia não pausa o jogo da Ana", req(f"{CATALOG}/games/{g['id']}/status", "PATCH", {"status": "MAINTENANCE"}, bia)[0], 403)
        check("Ana pausa o próprio jogo", req(f"{CATALOG}/games/{g['id']}/status", "PATCH", {"status": "MAINTENANCE"}, ana)[0], 200)
        check("admin reativa qualquer jogo", req(f"{CATALOG}/games/{g['id']}/status", "PATCH", {"status": "AVAILABLE"}, admin)[0], 200)
        check("catálogo continua público", req(f"{CATALOG}/games")[0], 200)

        print("[5] Rotas internas do catálogo")
        rid = "00000000-0000-4000-8000-000000000099"
        check("reserve direto sem segredo", req(f"{CATALOG}/games/3/reserve", "POST", {"rental_id": rid, "renter_name": "X"}, ana)[0], 403)
        check("reserve com X-Service-Token", req(f"{CATALOG}/games/3/reserve", "POST", {"rental_id": rid, "renter_name": "X"},
                                               headers={"X-Service-Token": SERVICE_TOKEN})[0], 200)
        check("release forçado por usuário comum", req(f"{CATALOG}/games/3/release?force=true", "POST", tok=ana,
                                                     headers={"X-Service-Token": SERVICE_TOKEN})[0], 403)
        check("release forçado por admin", req(f"{CATALOG}/games/3/release?force=true", "POST", tok=admin)[0], 200)

        print("[6] Área administrativa")
        check("discovery sem login", req(f"{CATALOG}/discovery")[0], 401)
        check("discovery como cliente", req(f"{RENTAL}/discovery", tok=ana)[0], 403)
        check("discovery como admin", req(f"{RENTAL}/discovery", tok=admin)[0], 200)
        s, sim = req(f"{RENTAL}/rentals", "POST", {**body, "game_id": 5, "renter_email": "simulador1@gamerent.test"}, admin)
        check("admin pode alugar em nome de outro (simulador)", (s, sim.get("renter_email")), (201, "simulador1@gamerent.test"))

        print("\nOK: Todas as regras de autenticação e autorização validadas!")
    finally:
        for p in procs:
            p.terminate()
        srv.shutdown()
