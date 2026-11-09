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

### 4. Login com Amazon Cognito e regras de acesso

Os dois serviços leem `AUTH_PROVIDER`:

| Valor | Quando usar | Comportamento |
|---|---|---|
| `none` (padrão) | desenvolvimento e testes locais | rotas abertas, como antes; quem chama informa `renter_email`/`owner_id` |
| `cognito` | EC2 / produção | rotas de escrita exigem `Authorization: Bearer <id_token>` do Cognito |

Com `cognito`, o token é validado nos próprios serviços (assinatura RS256 pelas chaves JWKS do pool, emissor,
audiência = App client, `token_use = id` e expiração), e as regras ficam assim:

| Rota | Quem pode |
|---|---|
| `GET /games`, `/games/nearby`, `/games/{id}`, `/health` | qualquer pessoa |
| `POST /games` | usuário logado; o `owner_id` gravado é o `sub` do token |
| `PATCH /games/{id}/status` | dono do anúncio ou admin |
| `POST /rentals` | usuário logado; `renter_email` vem do token (admin pode informar outro, usado no simulador) |
| `GET /rentals`, `GET /rentals/{id}`, `POST /rentals/{id}/return` | o próprio locatário ou admin |
| `GET /discovery` | admin |
| `POST /games/{id}/reserve` e `/release` | só o `rental-service` (`X-Service-Token`) ou admin; bloqueadas no nginx |
| `POST /games/{id}/release?force=true` | admin (grupo `admin` ou `X-Admin-Token`) |

Admin = usuário no grupo `admin` do User Pool. O `docker-compose.aws.yml` liga `AUTH_PROVIDER=cognito` e
**se recusa a subir** sem `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `SERVICE_TOKEN`, `VITE_COGNITO_DOMAIN` e
`VITE_COGNITO_REDIRECT_URI`.

**Criando o User Pool (uma vez, no console da AWS, região sa-east-1):**

1. **Cognito → User pools → Create user pool.** Tipo *Traditional web application*, login por **e-mail**.
   Atributos obrigatórios: `email` e `name`.
2. **App client:** público, **sem client secret**, fluxo *Authorization code grant* com PKCE, escopos
   `openid email profile`.
   - *Allowed callback URLs* e *Allowed sign-out URLs*: o endereço do site, com a barra no final
     (ex.: `http://<ip-publico>:8080/`). Fora de `localhost`, o Cognito só aceita `https`, então na EC2
     use um domínio com HTTPS (por exemplo, um Application Load Balancer com certificado do ACM) ou rode o
     login de demonstração apenas localmente.
3. **Domain:** crie um domínio do Cognito (ex.: `jogai-gamerent`), que vira
   `jogai-gamerent.auth.sa-east-1.amazoncognito.com`.
4. **Groups → Create group** `admin` e adicione os usuários administradores.
5. Anote o *User pool ID* e o *Client ID*.

**Subindo na EC2:**

```bash
export COGNITO_USER_POOL_ID=sa-east-1_XXXXXXXXX
export COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
export VITE_COGNITO_DOMAIN=jogai-gamerent.auth.sa-east-1.amazoncognito.com
export VITE_COGNITO_REDIRECT_URI=https://<seu-dominio>/
export SERVICE_TOKEN=$(openssl rand -hex 32)
export ADMIN_TOKEN=$(openssl rand -hex 16)
export CORS_ORIGINS=https://<seu-dominio>
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
```

Guarde esses valores fora do repositório (por exemplo, num arquivo `.env` na EC2, que já está no
`.gitignore`). Para validar as regras sem a AWS: `python scripts/test_auth.py`, que gera tokens no formato do
Cognito com uma chave local.

### 5. Mensageria Amazon SQS

O `rental-service` conversa com o `catalog-service` por **Amazon SQS**. A IAM Role permite criar as
filas `gamerent_*`, enviar, receber e apagar mensagens; nenhuma URL ou chave de acesso fica no código.
No ambiente local o `docker-compose.yml` sobe `softwaremill/elasticmq-native` (`sqs-local`); na AWS o
`SQS_ENDPOINT_URL` fica vazio e o boto3 usa a região `sa-east-1` com as credenciais da Instance Profile.
As duas réplicas do catálogo consomem a mesma fila (competing consumers), e a exclusão mútua é garantida
pelas escritas condicionais no DynamoDB.


### 6. CloudFront na frente da EC2 (HTTPS)

O Cognito só aceita callback `https` fora de `localhost`, e a EC2 serve HTTP. O CloudFront resolve isso:
o navegador fala HTTPS com o CloudFront, e ele busca o site na EC2 por HTTP.

**Origem (EC2):**

| Campo | Valor |
|---|---|
| Origin domain | DNS público da EC2. Use um **Elastic IP**: sem ele o endereço muda a cada stop/start e o CloudFront passa a dar 504 |
| Protocol | **HTTP only** (a EC2 não tem certificado; "HTTPS only" ou "Match viewer" dá 504) |
| HTTP port | `80`, com `FRONTEND_PORT=80` no `.env` (ou `8080` se mantiver a porta padrão) |

**Security Group da EC2:** libere a porta da origem para a lista de prefixos gerenciada
`com.amazonaws.global.cloudfront.origin-facing`. Se a regra estiver só com "Meu IP", o site abre para quem
criou a regra (acesso direto pelo IP) e dá **504 para todo mundo pelo CloudFront**.

**Comportamentos (behaviors):**

| Caminho | Cache policy | Origin request policy | Métodos |
|---|---|---|---|
| `/api/*` | `CachingDisabled` | `AllViewerExceptHostHeader` (repassa o `Authorization` com o token do Cognito) | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| padrão (`*`) | `CachingOptimized` | nenhuma | GET, HEAD |

Viewer protocol policy: *Redirect HTTP to HTTPS*. O nginx já manda `no-cache` no `index.html`, cache longo
em `/assets/` (arquivos com hash) e `no-store` nas respostas da API.

Depois de criar a distribuição, use `https://<id>.cloudfront.net/` em `VITE_COGNITO_REDIRECT_URI`,
`CORS_ORIGINS` e nas *Allowed callback/sign-out URLs* do App client do Cognito.

**504 Gateway Timeout:** o CloudFront não alcançou a EC2. Confira, nesta ordem: endereço da origem
atualizado, protocolo HTTP only, porta igual à do `FRONTEND_PORT`, Security Group liberando o CloudFront e
`docker compose ps` com tudo `healthy`. Um teste rápido: `curl -I http://<ip-da-ec2>:<porta>/` de fora da AWS.

### 7. Atualizar o deploy

Na primeira vez, o [`user_data_ec2.sh`](user_data_ec2.sh) instala tudo e clona o repositório em
`/opt/gamerent` (branch padrão, `main`). Crie o `.env` a partir de [`.env.example`](../.env.example) e, para
cada nova versão:

```bash
cd /opt/gamerent && sudo bash infra/deploy.sh
```

O script baixa a `main`, reconstrói as imagens, sobe a stack e espera os healthchecks de todos os serviços
(catálogo, locações e front-end). Se algo não ficar saudável em 3 minutos, ele mostra os últimos logs e sai
com erro. Os logs dos containers têm rotação (10 MB × 3 arquivos por serviço).
