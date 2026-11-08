# Infraestrutura — Entrega 3

## Ambiente local (Docker)

```bash
docker compose up -d --build
python scripts/test_issue_3.py
```

| Serviço             | Porta host | Papel                                                           |
|---------------------|-----------:|-----------------------------------------------------------------|
| `dynamodb-local`    |       8000 | Amazon DynamoDB em container (`-sharedDb -inMemory`), só em 127.0.0.1 |
| `catalog-service`   |       8001 | Réplica 1 do catálogo (`INSTANCE_ID=catalog-1`)                 |
| `catalog-service-2` |       8003 | Réplica 2 do catálogo (`INSTANCE_ID=catalog-2`), mesma tabela   |
| `rental-service`    |       8002 | Orquestrador de locações                                        |
| `frontend`          |       8080 | Interface web                                                   |

Variáveis de ambiente injetadas nos serviços: `AWS_REGION=sa-east-1`, `DYNAMODB_ENDPOINT_URL`,
`INSTANCE_ID`, `GAMES_TABLE_NAME`, `RENTALS_TABLE_NAME`.

O `rental-service` fala só com a réplica 1 (`catalog-service`). A réplica 2 lê a mesma tabela, mas
ainda não entra no balanceamento: `PATCH /status` e a geração de IDs usam o estado em memória de cada
réplica até a exclusão mútua no DynamoDB (#4/#7). Depois disso, basta dar à réplica 2 o alias
`catalog-service` para o Docker DNS distribuir as chamadas entre as duas.

Na AWS, o nome simbólico `catalog.gamerent.internal` vem do Route 53 (issue #5), não do Docker.

> O `dynamodb-local` roda em memória: os dados somem ao recriar o container.

## AWS (sa-east-1)

### 1. IAM Role da EC2

```bash
./infra/setup_iam.sh <EC2_INSTANCE_ID>
```

Cria a role `GameRentEC2Role` com a política [`iam/gamerent-ec2-policy.json`](iam/gamerent-ec2-policy.json)
(`dynamodb:*` nas tabelas `gamerent_*`; no Route 53, criar e ler zonas e alterar só registros `*.gamerent.internal`; no Cloud Map, só leitura e descoberta), cria o Instance Profile e
o associa à instância. Nenhuma chave de acesso fica na EC2: o boto3 usa as credenciais temporárias da role.

Validação dentro da EC2:

```bash
aws sts get-caller-identity
aws dynamodb list-tables --region sa-east-1
```

### 2. Subir os serviços contra o DynamoDB gerenciado

O [`user_data_ec2.sh`](user_data_ec2.sh) instala Docker/Compose v2 e AWS CLI, clona o repositório e roda:

```bash
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
```

O override [`docker-compose.aws.yml`](../docker-compose.aws.yml) zera `DYNAMODB_ENDPOINT_URL` e liga
`USE_DYNAMODB=true`, então os serviços passam a usar o DynamoDB real em `sa-east-1`.

### 3. Token de administrador

A liberação forçada de um jogo (`POST /games/{id}/release?force=true`) ignora a locação ativa, então na
EC2 ela deve ficar protegida. Defina `ADMIN_TOKEN` antes de subir a stack:

```bash
export ADMIN_TOKEN=$(openssl rand -hex 16)
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
```

Com o token definido, a chamada exige o header `X-Admin-Token`. Os scripts de teste o enviam
automaticamente quando `ADMIN_TOKEN` está no ambiente.

Na AWS (DynamoDB gerenciado, sem `DYNAMODB_ENDPOINT_URL`), se `ADMIN_TOKEN` não estiver definido a
liberação forçada é **recusada com 403**. No desenvolvimento local com DynamoDB Local ela continua
aberta para não quebrar os testes, e o catálogo registra um aviso no log.

### 4. Mensageria Amazon SQS

O `rental-service` conversa com o `catalog-service` por **Amazon SQS**. A IAM Role permite criar as
filas `gamerent_*`, enviar, receber e apagar mensagens; nenhuma URL ou chave de acesso fica no código.
No ambiente local o `docker-compose.yml` sobe `softwaremill/elasticmq-native` (`sqs-local`); na AWS o
`SQS_ENDPOINT_URL` fica vazio e o boto3 usa a região `sa-east-1` com as credenciais da Instance Profile.
As duas réplicas do catálogo consomem a mesma fila (competing consumers), e a exclusão mútua é garantida
pelas escritas condicionais no DynamoDB.
