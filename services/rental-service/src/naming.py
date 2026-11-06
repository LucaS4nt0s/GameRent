"""Esquema formal de nomeação do GameRent (Entrega 3 — Requisito 5, Nomeação).

Todo recurso distribuído recebe um URN no namespace ``urn:gamerent``:

    Serviços/Nós : urn:gamerent:node:{service_name}:{instance_id}
    Jogos        : urn:gamerent:game:{region}:{game_id}
    Reservas     : urn:gamerent:rental:{uuid_v4}
    Locadores    : urn:gamerent:owner:{owner_id}

Também concentra a resolução de nomes simbólicos (Docker DNS localmente, Route 53 /
Cloud Map na AWS) para que os logs mostrem nome -> IP privado.

Este arquivo é idêntico em catalog-service e rental-service (cada serviço tem sua própria
imagem Docker); mantenha os dois em sincronia.
"""
import logging
import os
import re
import socket
import uuid
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("gamerent.naming")

NAMESPACE = "urn:gamerent"
DEFAULT_REGION = "sa-east-1"
INTERNAL_DOMAIN = "gamerent.internal"

_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_URN_PATTERNS = {
    "node": re.compile(rf"^{NAMESPACE}:node:(?P<service_name>{_SEGMENT}):(?P<instance_id>{_SEGMENT})$"),
    "game": re.compile(rf"^{NAMESPACE}:game:(?P<region>{_SEGMENT}):(?P<game_id>\d+)$"),
    "rental": re.compile(
        rf"^{NAMESPACE}:rental:(?P<rental_id>[0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}})$"
    ),
    "owner": re.compile(rf"^{NAMESPACE}:owner:(?P<owner_id>{_SEGMENT})$"),
}


def region() -> str:
    return os.getenv("AWS_REGION") or DEFAULT_REGION


def instance_id() -> str:
    """Identidade do nó: INSTANCE_ID explícito ou o hostname do container/EC2."""
    return os.getenv("INSTANCE_ID") or socket.gethostname()


def node_urn(service_name: str, instance: Optional[str] = None) -> str:
    return f"{NAMESPACE}:node:{service_name}:{instance or instance_id()}"


def game_urn(game_id: int, game_region: Optional[str] = None) -> str:
    return f"{NAMESPACE}:game:{game_region or region()}:{game_id}"


def rental_urn(rental_id: str) -> str:
    return f"{NAMESPACE}:rental:{uuid.UUID(str(rental_id))}"


def owner_urn(owner_id: str) -> str:
    return f"{NAMESPACE}:owner:{owner_id}"


def parse_urn(urn: str) -> dict:
    """Decompõe um URN do GameRent em ``{"type": ..., <campos>}``; ValueError se inválido."""
    for kind, pattern in _URN_PATTERNS.items():
        match = pattern.match(urn or "")
        if match:
            return {"type": kind, **match.groupdict()}
    raise ValueError(f"URN fora do esquema {NAMESPACE}: {urn!r}")


def is_valid_urn(urn: str, kind: Optional[str] = None) -> bool:
    try:
        return kind is None or parse_urn(urn)["type"] == kind
    except ValueError:
        return False


def host_of(target: str) -> str:
    """Aceita ``http://host:porta/...``, ``host:porta`` ou ``host`` e devolve só o host."""
    if "://" in target:
        return urlparse(target).hostname or target
    return target.split(":", 1)[0]


def resolve(target: str) -> dict:
    """Resolve um nome simbólico via DNS (socket.getaddrinfo) e registra a tradução nos logs."""
    host = host_of(target)
    try:
        ips = sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
        logger.info(f"[DNS] {host} -> {', '.join(ips)}")
        return {"hostname": host, "resolved_ips": ips, "resolved": True, "error": None}
    except socket.gaierror as exc:
        logger.warning(f"[DNS] Falha ao resolver {host}: {exc}")
        return {"hostname": host, "resolved_ips": [], "resolved": False, "error": str(exc)}


def local_ips() -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror:
        return []


def discovery_info(service_name: str, dns_targets: list[str], lamport_clock: Optional[int]) -> dict:
    """Metadados de nomeação do nó atual, servidos em GET /discovery."""
    return {
        "service": service_name,
        "node_urn": node_urn(service_name),
        "instance_id": instance_id(),
        "region": region(),
        "hostname": socket.gethostname(),
        "local_ips": local_ips(),
        "internal_domain": INTERNAL_DOMAIN,
        "dns": [resolve(t) for t in dns_targets],
        "lamport_clock": lamport_clock,
        "urn_schema": {
            "node": f"{NAMESPACE}:node:{{service_name}}:{{instance_id}}",
            "game": f"{NAMESPACE}:game:{{region}}:{{game_id}}",
            "rental": f"{NAMESPACE}:rental:{{uuid_v4}}",
            "owner": f"{NAMESPACE}:owner:{{owner_id}}",
        },
    }
