"""Autenticação e autorização dos serviços GameRent.

Este arquivo é idêntico em catalog-service e rental-service; mantenha os dois em sincronia.

Modos (variável AUTH_PROVIDER):
  - "none" (padrão): desenvolvimento e testes locais. Nenhuma rota exige login; quem chama
    informa renter_email / owner_id no corpo, como antes.
  - "cognito": produção. Rotas de escrita exigem `Authorization: Bearer <id_token>` emitido pelo
    Amazon Cognito User Pool. O token é validado localmente (assinatura RS256 pelas chaves JWKS do
    pool, emissor, audiência = App client, token_use = "id" e expiração). Quem está no grupo
    ADMIN_GROUP (padrão "admin") é administrador.

Chamadas entre serviços (rental-service -> catalog-service /reserve e /release) usam o segredo
compartilhado SERVICE_TOKEN no header X-Service-Token. Sem SERVICE_TOKEN, essas rotas ficam
abertas (apenas em desenvolvimento; um aviso é registrado no log).
"""
import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Header, HTTPException, status

logger = logging.getLogger("gamerent.auth")

AUTH_PROVIDER = (os.getenv("AUTH_PROVIDER") or "none").strip().lower()
ADMIN_GROUP = os.getenv("ADMIN_GROUP", "admin")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN") or None
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or None

COGNITO_REGION = os.getenv("COGNITO_REGION") or os.getenv("AWS_REGION") or "sa-east-1"
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
COGNITO_ISSUER = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
# Só para testes: aponta as chaves públicas para outro endereço (o emissor continua o do Cognito)
COGNITO_JWKS_URL = os.getenv("COGNITO_JWKS_URL") or f"{COGNITO_ISSUER}/.well-known/jwks.json"

if AUTH_PROVIDER not in ("none", "cognito"):
    raise RuntimeError(f"AUTH_PROVIDER inválido: {AUTH_PROVIDER!r} (use 'none' ou 'cognito')")
if AUTH_PROVIDER == "cognito" and not (COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID):
    raise RuntimeError("AUTH_PROVIDER=cognito exige COGNITO_USER_POOL_ID e COGNITO_CLIENT_ID")
if AUTH_PROVIDER == "none":
    logger.warning("AUTH_PROVIDER=none: rotas sem login (modo de desenvolvimento). Use 'cognito' em produção.")
if SERVICE_TOKEN is None:
    logger.warning("SERVICE_TOKEN não definido: rotas internas entre serviços ficam abertas (modo de desenvolvimento).")

_jwks_client = None


@dataclass
class User:
    sub: str
    email: str
    name: str
    groups: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return ADMIN_GROUP in self.groups


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _secret_matches(given: Optional[str], expected: Optional[str]) -> bool:
    return bool(given) and bool(expected) and hmac.compare_digest(given, expected)


def verify_cognito_token(token: str) -> User:
    """Valida um id_token do Cognito e devolve o usuário. Lança HTTP 401 se inválido."""
    global _jwks_client
    import jwt  # PyJWT[crypto]

    try:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(COGNITO_JWKS_URL, cache_keys=True)
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID,
            issuer=COGNITO_ISSUER,
            options={"require": ["exp", "iat", "sub", "token_use"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Sessão expirada. Entre novamente.")
    except Exception as exc:
        logger.warning(f"Token rejeitado: {exc}")
        raise _unauthorized("Token de acesso inválido.")
    if claims.get("token_use") != "id":
        raise _unauthorized("Use o id_token do Cognito.")
    return User(
        sub=claims["sub"],
        email=(claims.get("email") or "").lower(),
        name=claims.get("name") or claims.get("given_name") or claims.get("email") or claims["sub"],
        groups=list(claims.get("cognito:groups") or []),
    )


def _user_from_header(authorization: Optional[str]) -> Optional[User]:
    if AUTH_PROVIDER != "cognito" or not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Use o header Authorization: Bearer <token>.")
    return verify_cognito_token(token.strip())


# ------------------------------------------------------------------ dependências do FastAPI

def optional_user(authorization: Optional[str] = Header(default=None)) -> Optional[User]:
    """Usuário do token, se houver. Nunca exige login."""
    return _user_from_header(authorization)


def require_user(authorization: Optional[str] = Header(default=None)) -> Optional[User]:
    """Com Cognito, exige login. Em AUTH_PROVIDER=none devolve None (rota aberta)."""
    user = _user_from_header(authorization)
    if AUTH_PROVIDER == "cognito" and user is None:
        raise _unauthorized("Entre na sua conta para continuar.")
    return user


def require_admin(
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> Optional[User]:
    """Admin = grupo ADMIN_GROUP no Cognito, ou X-Admin-Token igual a ADMIN_TOKEN.

    Em AUTH_PROVIDER=none sem ADMIN_TOKEN, a rota fica aberta (desenvolvimento).
    """
    if _secret_matches(x_admin_token, ADMIN_TOKEN):
        return None
    user = _user_from_header(authorization)
    if user is not None and user.is_admin:
        return user
    if AUTH_PROVIDER == "none" and ADMIN_TOKEN is None:
        return None
    if user is None:
        raise _unauthorized("Entre com uma conta de administrador.")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores.")


def require_service_or_admin(
    authorization: Optional[str] = Header(default=None),
    x_service_token: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> None:
    """Rotas internas (catálogo): só o rental-service (SERVICE_TOKEN) ou um administrador."""
    if SERVICE_TOKEN is None:
        return
    if _secret_matches(x_service_token, SERVICE_TOKEN) or _secret_matches(x_admin_token, ADMIN_TOKEN):
        return
    user = _user_from_header(authorization)
    if user is not None and user.is_admin:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rota interna entre serviços.")


def cors_settings() -> dict:
    """CORS_ORIGINS=https://site.com,https://outro.com restringe as origens; padrão '*'.

    O token vai no header Authorization (não em cookie), então credenciais de navegador não são
    necessárias: allow_credentials fica desligado.
    """
    raw = os.getenv("CORS_ORIGINS", "*")
    origins = [o.strip() for o in raw.split(",") if o.strip()] or ["*"]
    return {
        "allow_origins": origins,
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "PATCH", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-Lamport-Clock", "X-Admin-Token"],
        "expose_headers": ["X-Lamport-Clock", "X-Consistency-Mode", "X-DB-Read-Latency-Ms", "X-Served-By-Node"],
    }
