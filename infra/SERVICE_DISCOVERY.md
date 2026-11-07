# Nomeação e Service Discovery — Entrega 3 (issue #5)

## Esquema formal de URNs

Implementado em `services/*/src/naming.py` (mesmo arquivo nos dois serviços).

| Recurso      | Formato                                          | Exemplo                                                       |
|--------------|--------------------------------------------------|---------------------------------------------------------------|
| Serviço/Nó   | `urn:gamerent:node:{service_name}:{instance_id}` | `urn:gamerent:node:catalog-service:catalog-1`                 |
| Jogo         | `urn:gamerent:game:{region}:{game_id}`           | `urn:gamerent:game:sa-east-1:3`                               |
| Reserva      | `urn:gamerent:rental:{uuid}` (gerado com uuid4)                  | `urn:gamerent:rental:4db0ddd6-3f6c-40d7-a62d-eef18e768ce2`    |
| Locador      | `urn:gamerent:owner:{owner_id}`                  | `urn:gamerent:owner:locador-001`                              |

`instance_id` vem da variável `INSTANCE_ID` (ou do hostname do container). `region` vem de `AWS_REGION`.

Onde aparecem:

- `GET /health` → `node_urn`, `instance_id`
- `GET /discovery` → URN do nó, região, hostname, IPs locais, esquema de URNs e resolução DNS dos nomes simbólicos
- `GET /games*` → `urn`, `owner_urn`, `served_by_node`
- `POST /rentals`, `GET /rentals*` → `urn`, `game_urn`, `served_by_node`

## Resolução de nomes

| Ambiente | Nome do catálogo                 | Quem resolve                     |
|----------|----------------------------------|----------------------------------|
| Docker   | `catalog-service`                | Docker DNS (rede `gamerent-net`) |
| AWS      | `catalog.gamerent.internal`      | Route 53 Private Hosted Zone     |

Os serviços registram cada tradução nome → IP com `socket.getaddrinfo`:

```
[CATALOG-SERVICE] [DNS] catalog-service -> 172.18.0.3, 172.18.0.4
[RENTAL-SERVICE] [DNS] catalog-service -> 172.18.0.3, 172.18.0.4
```

O catálogo resolve seus próprios nomes ao iniciar (`DNS_DISCOVERY_TARGETS`, padrão
`catalog.gamerent.internal,catalog-service`). O `rental-service` resolve o host de `CATALOG_SERVICE_URL`
antes de cada chamada inter-serviços (de forma assíncrona, sem travar o event loop). O log mostra os
IPs candidatos; o httpx faz a própria resolução, então, se o nome tiver vários IPs, a conexão pode ir
para qualquer um deles.

Valores livres (como `owner_id` com `@` ou espaço, ou um `INSTANCE_ID` com `:`) são codificados com
`%XX` (RFC 8141) para que todo URN gerado passe em `naming.parse_urn`.

## Provisionando na AWS

Pré-requisito: IAM Role da EC2 com `route53:*` (issue #3, `infra/setup_iam.sh`).

```bash
./infra/setup_route53.sh <EC2_INSTANCE_ID>
```

O script habilita DNS na VPC, cria/reaproveita a zona privada `gamerent.internal` e faz UPSERT de
`catalog.gamerent.internal` e `rental.gamerent.internal` apontando para o IP privado da EC2. Depois,
suba o `rental-service` com `CATALOG_SERVICE_URL=http://catalog.gamerent.internal:8001`.

> Alternativa: um namespace DNS privado no AWS Cloud Map (`aws servicediscovery create-private-dns-namespace`)
> cria a mesma zona no Route 53 e permite registrar instâncias por API. Para uma única EC2, a zona privada
> direta é mais simples e tem o mesmo efeito na resolução.

## Contrato do `GET /discovery`

O endpoint segue o contrato da issue #16 (`service`, `node_urn`, `instance_id`, `hostname`, `local_ip`,
`dns_target`, `dns_resolution{target_hostname, resolved_ips, status: RESOLVED|UNRESOLVED}`,
`lamport_clock`, `dynamodb{connected, table_name, mode}`, `timestamp`), montado a partir do `naming.py`.
Os campos da issue #5 vêm como acréscimos: `region`, `local_ips`, `internal_domain`, `dns[]` (resolução
de cada nome simbólico do nó) e `urn_schema`.

Cada resolução tem limite de `DNS_TIMEOUT_S` (padrão 2 s), então um nome inexistente não trava o endpoint
nem as chamadas S2S. Consultar o endpoint sincroniza o relógio de Lamport com o header `X-Lamport-Clock`.
