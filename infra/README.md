# Infraestrutura — Entrega 3

## Ambiente local (Docker)

```bash
docker compose up -d --build
python scripts/test_issue_3.py
```

| Serviço             | Porta host | Papel                                                           |
|---------------------|-----------:|-----------------------------------------------------------------|
| `dynamodb-local`    |       8000 | Amazon DynamoDB em container (`-sharedDb -inMemory`)            |
| `catalog-service`   |       8001 | Réplica 1 do catálogo (`INSTANCE_ID=catalog-1`)                 |
| `catalog-service-2` |       8003 | Réplica 2 do catálogo (`INSTANCE_ID=catalog-2`), mesma tabela   |
| `rental-service`    |       8002 | Orquestrador de locações                                        |
| `frontend`          |       8080 | Interface web                                                   |

Variáveis de ambiente injetadas nos serviços: `AWS_REGION=sa-east-1`, `DYNAMODB_ENDPOINT_URL`,
`INSTANCE_ID`, `GAMES_TABLE_NAME`, `RENTALS_TABLE_NAME`.

As duas réplicas compartilham o alias `catalog-service` na rede `gamerent-net`, então o Docker DNS
devolve os dois IPs e o `rental-service` alcança qualquer uma delas. Na AWS o nome simbólico
`catalog.gamerent.internal` vem do Route 53 (issue #5), não do Docker.

> O `dynamodb-local` roda em memória: os dados somem ao recriar o container.

## AWS (sa-east-1)

### 1. IAM Role da EC2

```bash
./infra/setup_iam.sh <EC2_INSTANCE_ID>
```

Cria a role `GameRentEC2Role` com a política [`iam/gamerent-ec2-policy.json`](iam/gamerent-ec2-policy.json)
(`dynamodb:*` nas tabelas `gamerent_*`, `route53:*`, `servicediscovery:*`), cria o Instance Profile e
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
